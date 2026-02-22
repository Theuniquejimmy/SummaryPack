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
from openai import OpenAI
from ebooklib import epub

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; text-align: center; font-size: 20px; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    div[data-testid="column"] button { padding-top: 10px; padding-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)
<style>
    /* ... your existing styles ... */
    .audio-container {
        background: #1a1c24;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #00d4ff;
        margin: 10px 0;
    }
</style>

# --- 2. API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

if not COMIC_VINE_KEY or not GEMINI_KEY:
    st.error("Missing API Keys! Check environment variables.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_KEY)
nvidia_client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY) if NVIDIA_API_KEY else None

# --- 3. HELPER FUNCTIONS ---

def load_history():
    if os.path.exists("comic_history.json"):
        try:
            with open("comic_history.json", "r") as f: return json.load(f)
        except: return []
    return []

def save_history(history_list):
    try:
        with open("comic_history.json", "w") as f: json.dump(history_list, f)
    except: pass

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
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    needs_search = len(plot.strip()) < 50
    base_title = series_name.split(' (')[0]
    search_target = f"{base_title} {alt_name} issue {issue_num}" if alt_name else f"{series_name} issue {issue_num}"
    
    prompt = f"You are an expert comic book historian. Write a detailed 500-800 word deep-dive summary into {series_name} #{issue_num}."
    if needs_search:
        prompt += f"\nCRITICAL: Use your GOOGLE SEARCH TOOL to find the plot for: '{search_target}'. Ensure events are specifically for issue #{issue_num}."
    else:
        prompt += f"\nSOURCE PLOT: {plot}"
    prompt += f"\nCreators: {creators}\nCharacters: {chars}\nFormat with headings: Context, Detailed Plot, Key Moments, Significance."

    models_to_try = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-pro-preview"]
    for model_name in models_to_try:
        wait_time = 6
        for attempt in range(2):
            try:
                from google.genai import types
                config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())] if needs_search else None)
                resp = ai_client.models.generate_content(model=model_name, contents=prompt, config=config)
                return resp.text
            except Exception as e:
                if "429" in str(e):
                    time.sleep(wait_time + random.uniform(1, 3))
                    wait_time *= 2
                else: break
    return "AI Error: Model Timeout."

def create_epub(title, content, cover_url=None):
    book = epub.EpubBook()
    book.set_identifier(title.replace(" ", "_").replace("#", ""))
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
    # Fixed TTS logic: returns the audio bytes directly
    communicate = edge_tts.Communicate(text, voice)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

def create_audio(text, voice_choice):
    if not text: return None
    clean_text = re.sub(r'[^a-zA-Z0-9\s.,!?]', '', text).strip()[:4000]
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(generate_neural_audio(clean_text, voice_choice))
        return data
    except Exception as e:
        st.error(f"TTS Error: {e}")
        return None

# --- 4. SESSION STATE ---
if "history" not in st.session_state: st.session_state.history = load_history()
if "issue_num" not in st.session_state: st.session_state.issue_num = "1"
if "current_summary" not in st.session_state: st.session_state.current_summary = None
if "batch_done" not in st.session_state: st.session_state.batch_done = False

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
            with c1: st.button("◄", on_click=lambda: st.session_state.update({"issue_num": str(int(st.session_state.issue_num)-1), "auto":True}))
            with c2: st.text_input("Issue", key="issue_num")
            with c3: st.button("►", on_click=lambda: st.session_state.update({"issue_num": str(int(st.session_state.issue_num)+1), "auto":True}))
            st.text_input("Wiki/Vol Override", key="alt_name")
            trigger = st.button("Analyze", use_container_width=True) or st.session_state.get("auto", False)
        else: st.warning("Not found."); trigger = False
    else: trigger = False
    
    st.divider()
    st.header("📦 Batch Processor")
    batch_range = st.text_input("Issue Range (e.g., 1-5)")
    if st.button("Start Batch run"):
        if '-' in batch_range and 'vid' in locals():
            try:
                s, e = map(int, batch_range.split('-'))
                prog = st.progress(0); stat = st.empty()
                if not os.path.exists("exports"): os.makedirs("exports")
                for i, curr in enumerate(range(s, e + 1)):
                    stat.text(f"Processing #{curr}...")
                    b_data = get_issue_data(vid, str(curr))
                    if b_data:
                        b_sum = generate_ai_summary(b_data, sel_vol, str(curr), st.session_state.alt_name)
                        b_epub = create_epub(f"{sel_vol} #{curr}", b_sum, b_data.get('image', {}).get('medium_url'))
                        with open(f"exports/{sel_vol.replace(' ','_')}_{curr}.epub", "wb") as f: f.write(b_epub)
                    prog.progress((i + 1) / (e - s + 1))
                    time.sleep(random.uniform(3, 5))
                st.session_state.batch_done = True
                stat.success(f"Batch Complete!")
            except Exception as ex: st.error(f"Batch Error: {ex}")

    # Zip Download Button (Appears only after batch)
    if st.session_state.batch_done:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for f in os.listdir("exports"):
                z.write(os.path.join("exports", f), f)
        st.download_button("🗜️ Download All (ZIP)", buf.getvalue(), "comic_vault_batch.zip", "application/zip", use_container_width=True)
        if st.button("Clear Exports"):
            for f in os.listdir("exports"): os.remove(os.path.join("exports", f))
            st.session_state.batch_done = False
            st.rerun()

    st.divider()
    voice_map = {"Christopher (Deep)": "en-US-ChristopherNeural", "Ryan (British)": "en-GB-RyanNeural", "Natasha (AU)": "en-AU-NatashaNeural"}
    sel_voice = st.selectbox("Narrator", options=list(voice_map.keys()))

# --- 6. MAIN EXECUTION ---
if query and trigger:
    st.session_state.auto = False
    with st.spinner("Analyzing..."):
        data = get_issue_data(vid, st.session_state.issue_num)
        if data:
            summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num, st.session_state.get("alt_name", ""))
            st.session_state.current_summary = summary
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            if st.session_state.current_title not in st.session_state.history:
                st.session_state.history.append(st.session_state.current_title); save_history(st.session_state.history)
            st.session_state.needs_audio = True
            st.session_state.audio_bytes = None # Clear old audio
        else: st.error("Issue not found.")

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
                if audio_data:
                    st.session_state.audio_bytes = audio_data
                st.session_state.needs_audio = False
            st.rerun()
        
     if st.session_state.get("audio_bytes"):
            # Convert bytes to base64 so HTML can read it
            b64_audio = base64.b64encode(st.session_state.audio_bytes).decode()
            
            # Custom HTML5 Player with Speed Control
            audio_html = f"""
            <div style="background-color: #1a1c24; padding: 15px; border-radius: 10px; border-left: 4px solid #00d4ff;">
                <audio id="comic-narrator" style="width: 100%;">
                    <source src="data:audio/mp3;base64,{b64_audio}" type="audio/mp3">
                </audio>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 10px; color: white; font-family: sans-serif;">
                    <button onclick="document.getElementById('comic-narrator').play()" style="background: #00d4ff; border: none; border-radius: 5px; padding: 5px 15px; cursor: pointer; font-weight: bold;">PLAY</button>
                    <button onclick="document.getElementById('comic-narrator').pause()" style="background: #333; border: none; border-radius: 5px; padding: 5px 15px; cursor: pointer; color: white;">PAUSE</button>
                    <div style="flex-grow: 1; margin: 0 20px;">
                        <label style="font-size: 12px; display: block; margin-bottom: 5px;">Playback Speed: <span id="speed-val">1.0x</span></label>
                        <input type="range" id="speed-slider" min="0.5" max="2.0" step="0.1" value="1.0" style="width: 100%; cursor: pointer;">
                    </div>
                </div>
            </div>

            <script>
                var audio = document.getElementById('comic-narrator');
                var slider = document.getElementById('speed-slider');
                var display = document.getElementById('speed-val');

                slider.oninput = function() {{
                    audio.playbackRate = this.value;
                    display.innerHTML = this.value + 'x';
                }};
            </script>
            """
            components.html(audio_html, height=120)
            
        st.divider()
        eb = create_epub(st.session_state.current_title, st.session_state.current_summary, st.session_state.current_img)
        st.download_button("📖 Download EPUB", eb, f"{st.session_state.current_title}.epub", "application/epub+zip", use_container_width=True)

