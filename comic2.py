import streamlit as st
import requests
import os
import re
import asyncio
import edge_tts
import base64
import json
import time
import io
import markdown
import random
import zipfile
import streamlit.components.v1 as components
from google import genai
from ebooklib import epub

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; text-align: center; font-size: 20px; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    .chat-bubble { background: #1a1c24; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 3px solid #00d4ff; font-size: 14px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not COMIC_VINE_KEY or not GEMINI_KEY:
    st.error("Missing API Keys! Check environment variables.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_KEY)

# --- 3. HELPER FUNCTIONS ---

def safe_prev():
    try:
        val = st.session_state.issue_num.strip()
        curr = int(val) if val else 1
        if curr > 1:
            st.session_state.issue_num = str(curr - 1)
            st.session_state.auto = True
    except: st.session_state.issue_num = "1"

def safe_next():
    try:
        val = st.session_state.issue_num.strip()
        curr = int(val) if val else 1
        st.session_state.issue_num = str(curr + 1)
        st.session_state.auto = True
    except: st.session_state.issue_num = "1"

@st.cache_data
def fetch_volumes(query):
    url = "https://comicvine.gamespot.com/api/search/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "query": query, "resources": "volume", "limit": 50}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        results = res.get('results', [])
        results.sort(key=lambda x: int(re.search(r'\d+', str(x.get('start_year', 9999))).group()) if re.search(r'\d+', str(x.get('start_year', 9999))) else 9999)
        return results
    except: return []

@st.cache_data
def get_issue_data(volume_id, issue_num):
    url = "https://comicvine.gamespot.com/api/issues/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "filter": f"volume:{volume_id},issue_number:{issue_num}", "field_list": "name,deck,description,character_credits,person_credits,image"}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        return res.get('results', [])[0] if res.get('results') else None
    except: return None

@st.cache_data(show_spinner=False)
def generate_ai_summary(issue_data, series_name, issue_num, alt_name=""):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    needs_search = len(plot.strip()) < 50
    base_title = series_name.split(' (')[0]
    search_target = f"{base_title} {alt_name} issue {issue_num}" if alt_name else f"{series_name} issue {issue_num}"
    
    prompt = f"Expert comic historian. Write 500-800 word deep-dive into {series_name} #{issue_num}."
    if needs_search:
        prompt += f"\nUSE GOOGLE SEARCH for: '{search_target}'. Only summarize issue #{issue_num} specifically."
    else:
        prompt += f"\nPLOT: {plot}"
    prompt += f"\nCharacters: {chars}\nHeadings: Context, Detailed Plot, Key Moments, Significance."

    # Starting with the ultra-stable 2.5 Flash
    models = ["gemini-2.5-flash", "gemini-3.1-pro-preview"]
    for m in models:
        wait = 5
        for att in range(2):
            try:
                from google.genai import types
                cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())] if needs_search else None)
                resp = ai_client.models.generate_content(model=m, contents=prompt, config=cfg)
                return resp.text
            except:
                time.sleep(wait + random.uniform(1, 2))
                wait *= 2
    return "Error generating summary."

def create_epub(title, content, cover_url=None):
    book = epub.EpubBook()
    book.set_identifier(title.replace(" ", "_"))
    book.set_title(title)
    book.set_language('en')
    book.add_author("Comic Vault Analyzer")
    if cover_url:
        try:
            img_data = requests.get(cover_url).content
            book.set_cover("cover.jpg", img_data)
        except: pass
    c1 = epub.EpubHtml(title=title, file_name='chap_01.xhtml', lang='en')
    c1.content = f'<h2>{title}</h2>' + markdown.markdown(content)
    book.add_item(c1)
    book.toc = (epub.Link('chap_01.xhtml', title, 'intro'),)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav', c1]
    out = io.BytesIO(); epub.write_epub(out, book)
    return out.getvalue()

async def generate_neural_audio(text, voice):
    communicate = edge_tts.Communicate(text, voice)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio": audio_data += chunk["data"]
    return audio_data

def create_audio(text, voice_choice):
    if not text: return None
    clean = re.sub(r'[^a-zA-Z0-9\s.,!?]', '', text).strip()[:4000]
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        return loop.run_until_complete(generate_neural_audio(clean, voice_choice))
    except: return None

# --- 4. SESSION STATE ---
if "history" not in st.session_state: st.session_state.history = []
if "issue_num" not in st.session_state: st.session_state.issue_num = "1"
if "current_summary" not in st.session_state: st.session_state.current_summary = None
if "batch_done" not in st.session_state: st.session_state.batch_done = False
if "auto" not in st.session_state: st.session_state.auto = False
if "chat_history" not in st.session_state: st.session_state.chat_history = []

# --- 5. UI SIDEBAR ---
with st.sidebar:
    st.header("🔍 Search")
    query = st.text_input("Series", key="search_query")
    if query:
        vols = fetch_volumes(query)
        if vols:
            vol_map = {f"{v['name']} ({v['start_year']})": v['id'] for v in vols}
            sel_vol = st.selectbox("Volume", vol_map.keys())
            vid = vol_map[sel_vol]
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1: st.button("◄", on_click=safe_prev, use_container_width=True)
            with c2: st.text_input("Issue", key="issue_num")
            with c3: st.button("►", on_click=safe_next, use_container_width=True)
            st.text_input("Wiki/Vol Override", key="alt_name")
            trigger = st.button("Analyze", use_container_width=True) or st.session_state.auto
        else: st.warning("Not found."); trigger = False
    else: trigger = False
    
    st.divider()
    st.header("📦 Batch Processor")
    b_range = st.text_input("Range (e.g., 1-5)")
    if st.button("Start Batch"):
        if '-' in b_range and 'vid' in locals():
            try:
                s, e = map(int, b_range.split('-'))
                prog = st.progress(0); stat = st.empty()
                if not os.path.exists("exports"): os.makedirs("exports")
                for i, curr in enumerate(range(s, e + 1)):
                    stat.text(f"Processing #{curr}...")
                    b_data = get_issue_data(vid, str(curr))
                    if b_data:
                        b_sum = generate_ai_summary(b_data, sel_vol, str(curr), st.session_state.alt_name)
                        b_epub = create_epub(f"{sel_vol} #{curr}", b_sum, b_data.get('image', {}).get('medium_url'))
                        with open(f"exports/{sel_vol.replace(' ','_')}_{curr}.epub", "wb") as f: f.write(b_epub)
                    prog.progress((i + 1) / (e - s + 1)); time.sleep(random.uniform(3, 5))
                st.session_state.batch_done = True; stat.success("Batch Complete!")
            except Exception as ex: st.error(f"Error: {ex}")

    if st.session_state.batch_done:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for f in os.listdir("exports"): z.write(os.path.join("exports", f), f)
        st.download_button("🗜️ Download ZIP", buf.getvalue(), "batch.zip", "application/zip", use_container_width=True)

    st.divider()
    voice_map = {"Christopher (Deep)": "en-US-ChristopherNeural", "Ryan (British)": "en-GB-RyanNeural"}
    sel_voice = st.selectbox("Narrator", options=list(voice_map.keys()))

# --- 6. MAIN EXECUTION ---

# Create the tabs globally so they are always accessible
tab1, tab2 = st.tabs(["📖 Summary & Audio", "💬 Interrogator Chat"])

if query and trigger:
    st.session_state.auto = False
    with st.spinner("Analyzing..."):
        data = get_issue_data(vid, st.session_state.issue_num)
        if data:
            summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num, st.session_state.get("alt_name", ""))
            st.session_state.current_summary = summary
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            st.session_state.needs_audio = True; st.session_state.audio_bytes = None
            st.session_state.chat_history = [] # Reset chat when a NEW book is analyzed
        else: st.error("Issue not found.")

# --- TAB 1: SUMMARY LOGIC ---
with tab1:
    if st.session_state.current_summary:
        col_a, col_b = st.columns([1, 2])
        with col_a: 
            if st.session_state.current_img: st.image(st.session_state.current_img)
        with col_b:
            st.subheader(st.session_state.current_title)
            st.markdown(st.session_state.current_summary)
            
            if st.session_state.get("needs_audio"):
                with st.spinner("🎙️ Generating audio..."):
                    audio_data = create_audio(st.session_state.current_summary, voice_map[sel_voice])
                    if audio_data: st.session_state.audio_bytes = audio_data
                    st.session_state.needs_audio = False
                st.rerun()
            
            if st.session_state.get("audio_bytes"):
                b64 = base64.b64encode(st.session_state.audio_bytes).decode()
                audio_html = f"""
                <div style="background-color: #1a1c24; padding: 15px; border-radius: 10px; border-left: 4px solid #00d4ff;">
                    <audio id="c-player" style="width: 100%;"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 10px; color: white; font-family: sans-serif;">
                        <button onclick="document.getElementById('c-player').play()" style="background:#00d4ff;border:none;border-radius:5px;padding:5px 15px;cursor:pointer;font-weight:bold;">PLAY</button>
                        <button onclick="document.getElementById('c-player').pause()" style="background:#333;border:none;border-radius:5px;padding:5px 15px;cursor:pointer;color:white;">PAUSE</button>
                    </div>
                </div>
                """
                components.html(audio_html, height=120)
            
            st.divider()
            eb = create_epub(st.session_state.current_title, st.session_state.current_summary, st.session_state.current_img)
            st.download_button("📖 Download EPUB", eb, f"{st.session_state.current_title}.epub", "application/epub+zip", use_container_width=True)
    else:
        st.info("👈 Use the sidebar to search and analyze a comic to see its summary here!")

# --- TAB 2: CHAT LOGIC (ALWAYS OPEN) ---
with tab2:
    if st.session_state.current_title:
        st.caption(f"Currently Discussing: {st.session_state.current_title}")
    else:
        st.caption("General Chat Mode: Ask me anything about comics!")
    
    for chat in st.session_state.chat_history:
        role_label = "🦸 You" if chat['role'] == 'user' else "🤖 Interrogator"
        st.markdown(f"<div class='chat-bubble'><b>{role_label}:</b><br>{chat['content']}</div>", unsafe_allow_html=True)
    
    user_input = st.chat_input("Message the Interrogator...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        
        with st.spinner("Consulting the archives..."):
            # If a summary exists, use it as context. Otherwise, just go general.
            context = st.session_state.current_summary if st.session_state.current_summary else "General comic knowledge."
            chat_prompt = f"You are a comic expert. Context: {context}\n\nUser Question: {user_input}"
            
            try:
                response = ai_client.models.generate_content(model="gemini-2.0-flash", contents=chat_prompt)
                st.session_state.chat_history.append({"role": "assistant", "content": response.text})
                st.rerun()
            except Exception as e:
                st.error(f"Chat failed: {e}")
