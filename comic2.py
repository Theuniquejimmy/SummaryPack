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
import streamlit.components.v1 as components
from google import genai
from openai import OpenAI
from ebooklib import epub

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; text-align: center; font-size: 20px; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    div[data-testid="column"] button { padding-top: 10px; padding-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- PERSISTENT HISTORY HELPERS ---
HISTORY_FILE = "comic_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history_list):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history_list, f)
    except Exception:
        pass

# --- SESSION STATE ---
if "history" not in st.session_state:
    st.session_state.history = load_history()
if "search_query" not in st.session_state:
    st.session_state.search_query = ""
if "issue_num" not in st.session_state:
    st.session_state.issue_num = "1"
if "alt_name" not in st.session_state:
    st.session_state.alt_name = ""
if "auto_analyze" not in st.session_state:
    st.session_state.auto_analyze = False
if "current_summary" not in st.session_state:
    st.session_state.current_summary = None
if "current_img" not in st.session_state:
    st.session_state.current_img = None
if "current_title" not in st.session_state:
    st.session_state.current_title = None
if "audio_bytes" not in st.session_state:
    st.session_state.audio_bytes = None
if "b64_audio" not in st.session_state:
    st.session_state.b64_audio = None
if "needs_audio" not in st.session_state:
    st.session_state.needs_audio = False

# --- CALLBACKS ---
def prev_issue():
    try:
        curr = int(st.session_state.issue_num)
        if curr > 1:
            st.session_state.issue_num = str(curr - 1)
            st.session_state.auto_analyze = True
    except ValueError: pass

def next_issue():
    try:
        curr = int(st.session_state.issue_num)
        st.session_state.issue_num = str(curr + 1)
        st.session_state.auto_analyze = True
    except ValueError: pass

def clear_history():
    st.session_state.history = []
    save_history([])

def load_from_history():
    sel_h = st.session_state.history_selector
    if sel_h and sel_h != "Select...":
        parts = sel_h.split(" #")
        st.session_state.search_query = parts[0]
        st.session_state.issue_num = parts[1]
        st.session_state.auto_analyze = True

# --- API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

if not COMIC_VINE_KEY or not GEMINI_KEY:
    st.error("Missing API Keys! Please check your environment variables.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_KEY)
nvidia_client = OpenAI(
  base_url="https://integrate.api.nvidia.com/v1",
  api_key=NVIDIA_API_KEY
) if NVIDIA_API_KEY else None

# --- HELPERS ---
@st.cache_data
def fetch_volumes(query):
    url = "https://comicvine.gamespot.com/api/search/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "query": query, "resources": "volume", "limit": 50}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        results = res.get('results', [])
        results.sort(key=lambda x: int(re.search(r'\d+', str(x.get('start_year', 9999))).group()) if re.search(r'\d+', str(x.get('start_year', 9999))) else 9999)
        return results
    except Exception: return []

@st.cache_data
def get_issue_data(volume_id, issue_num):
    url = "https://comicvine.gamespot.com/api/issues/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "filter": f"volume:{volume_id},issue_number:{issue_num}", "field_list": "name,deck,description,character_credits,person_credits,image"}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        return res.get('results', [])[0] if res.get('results') else None
    except Exception: return None

@st.cache_data(show_spinner=False)
def generate_ai_summary(issue_data, series_name, issue_num, alt_name=""):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    
    needs_search = len(plot.strip()) < 50
    base_title = series_name.split(' (')[0]
    search_target = f"{base_title} {alt_name} issue {issue_num}" if alt_name else f"{series_name} issue {issue_num}"
    
    prompt = f"You are an expert comic book historian. Write a highly detailed, 500+ word deep-dive summary into {series_name} #{issue_num}."
    
    if needs_search:
        prompt += f"""
        CRITICAL: Local database is empty. ACTIVELY GOOGLE SEARCH the plot for: "{search_target}".
        TIPS: Cross-reference with creators: {creators}. If year-based search fails, try searching by Volume numbers.
        Do not apologize. ONLY summarize issue #{issue_num}. Do not summarize full story arcs.
        """
    else:
        prompt += f"\nUse this plot: {plot}"
        
    prompt += f"\nCharacters involved: {chars}\nFormat with headings: Context, Detailed Plot, Key Moments, Significance."
    
    wait_time = 10 
    for attempt in range(3):
        try:
            from google.genai import types
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())] if needs_search else None
            )
            resp = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config=config)
            return resp.text
        except Exception as e:
            if "429" in str(e):
                time.sleep(wait_time)
                wait_time *= 2  
            else: break 
    return "AI Error: Failed to generate summary."

def create_epub(title, content):
    book = epub.EpubBook()
    book.set_identifier(title.replace(" ", "_").replace("#", ""))
    book.set_title(title)
    book.set_language('en')
    book.add_author("Comic Vault Analyzer")
    c1 = epub.EpubHtml(title=title, file_name='chap_01.xhtml', lang='en')
    html_body = markdown.markdown(content)
    c1.content = f'<h2>{title}</h2>{html_body}'
    book.add_item(c1)
    book.toc = (epub.Link('chap_01.xhtml', title, title),)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav', c1]
    out_stream = io.BytesIO()
    epub.write_epub(out_stream, book)
    return out_stream.getvalue()

async def generate_neural_audio(text, voice, filename="summary_temp.mp3"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def create_audio(text, voice_choice):
    if not text or len(text.strip()) == 0: return None
    clean_text = re.sub(r'[^a-zA-Z0-9\s.,!?\'"-]', '', text).strip()[:4000]
    filename = "summary_temp.mp3"
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_neural_audio(clean_text, voice_choice, filename))
        with open(filename, "rb") as f: audio_data = f.read()
        os.remove(filename)
        return audio_data
    except Exception: return None

# --- UI ---
st.title("📚 Comic Vault Analyzer")

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
            with c1: st.button("◄", on_click=prev_issue, use_container_width=True)
            with c2: st.text_input("Issue", key="issue_num")
            with c3: st.button("►", on_click=next_issue, use_container_width=True)
            st.text_input("Wiki/Vol Override (Optional)", key="alt_name")
            trigger = st.button("Analyze", use_container_width=True) or st.session_state.auto_analyze
        else: st.warning("Not found.")
    else: trigger = False

    st.divider()
    voice_map = {"Christopher (Deep)": "en-US-ChristopherNeural", "Aria (Clear)": "en-US-AriaNeural", "Ryan (British)": "en-GB-RyanNeural"}
    sel_voice_label = st.selectbox("Narrator", options=list(voice_map.keys()))
    
    st.divider()
    if st.session_state.history:
        st.selectbox("Recent:", ["Select..."] + list(reversed(st.session_state.history)), key="history_selector", on_change=load_from_history)
        st.button("🗑️ Clear", on_click=clear_history, use_container_width=True)

# --- EXECUTION ---
if query and 'vid' in locals() and trigger:
    st.session_state.auto_analyze = False
    with st.spinner("Analyzing comic archives..."):
        data = get_issue_data(vid, st.session_state.issue_num)
        if data:
            if len(str(data.get('deck') or data.get('description') or "").strip()) < 50:
                st.toast("🔍 Activating Gemini Google Search...")
            summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num, st.session_state.alt_name)
            st.session_state.current_summary = summary
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            if st.session_state.current_title not in st.session_state.history:
                st.session_state.history.append(st.session_state.current_title); save_history(st.session_state.history)
            st.session_state.audio_bytes = None; st.session_state.b64_audio = None
            if summary: st.session_state.needs_audio = True
        else: st.error("Issue not found.")

if st.session_state.current_summary:
    col_a, col_b = st.columns([1, 2])
    with col_a: 
        if st.session_state.current_img: st.image(st.session_state.current_img)
    with col_b:
        st.subheader(st.session_state.current_title)
        with st.container(border=True): st.markdown(st.session_state.current_summary)
        
        if st.session_state.needs_audio:
            with st.spinner("🎙️ Recording narrator..."):
                audio_bytes = create_audio(st.session_state.current_summary, voice_map[sel_voice_label])
                st.session_state.audio_bytes = audio_bytes
                if audio_bytes: st.session_state.b64_audio = base64.b64encode(audio_bytes).decode()
                st.session_state.needs_audio = False
            st.rerun()
        elif st.session_state.b64_audio:
            st.audio(st.session_state.audio_bytes, format="audio/mp3")
            
        st.divider()
        epub_bytes = create_epub(st.session_state.current_title, st.session_state.current_summary)
        st.download_button(label="📖 Download EPUB", data=epub_bytes, file_name=f"{st.session_state.current_title}.epub", mime="application/epub+zip", use_container_width=True)
