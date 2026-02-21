import streamlit as st
import requests
import os
import re
import asyncio
import edge_tts
import base64
import json
import streamlit.components.v1 as components
from duckduckgo_search import DDGS
from google import genai
from google.genai import types
from openai import OpenAI

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
    # Pulling 'person_credits' to get the exact writers and artists
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "filter": f"volume:{volume_id},issue_number:{issue_num}", "field_list": "name,deck,description,character_credits,person_credits,image"}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        return res.get('results', [])[0] if res.get('results') else None
    except Exception: return None

def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    
    # Grab whatever Comic Vine gave us
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    
    # --- THE WIKI-LOCKED DUCKDUCKGO FAILSAFE ---
    if len(plot.strip()) < 50:
        st.toast("🔍 Comic Vine plot missing! Scraping the Fandom Wiki...")
        try:
            search_query = f"site:fandom.com {series_name} #{issue_num} {creators} synopsis"
            ddg_results = DDGS().text(search_query, max_results=3)
            if ddg_results:
                web_plot = " ".join([res['body'] for res in ddg_results])
                plot = f"WIKI SEARCH RESULTS (Use this to figure out the plot): {web_plot}"
            else:
                plot = "No wiki data found. Do your best to recall."
        except Exception as e:
            plot = "Search failed. Do your best to recall the events."
    
    prompt = f"""
    Act as a passionate, encyclopedic comic book historian. Your goal is to write a highly detailed, comprehensive deep-dive into {series_name} #{issue_num}. 
    
    CRITICAL INSTRUCTION: Pay close attention to the release year in the series name ({series_name}) and the creative team ({creators}). 
    Do not confuse this with other volumes or eras of the same title. Use the "Plot Snippet" below as your absolute source of truth for what happens in this issue.
    
    Structure your response using Markdown headings for these exact sections:
    
    ### 🌍 Context & Background
    Explain what was happening in the comic universe leading up to this issue. Who is the creative team, and what run is this?
    
    ### 📖 Detailed Plot Summary
    Provide an exhaustive, multi-paragraph recounting of the issue's exact events. 
    
    ### 💥 Key Moments
    Use bullet points to list the most iconic panels, character beats, or reveals in this specific issue.
    
    ### 🏛️ Legacy & Significance
    Why does this issue matter? Discuss its impact or how it sets up the future.
    
    RULES:
    - Output must be 500-800 words.
    - Be enthusiastic and authoritative.
    
    RAW DATA:
    Series: {series_name}
    Issue: {issue_num}
    Creators: {creators}
    Characters Involved: {chars}
    Plot Snippet: {plot}
    """
    
    try:
        # Try Gemini First with Google Search built-in
        resp = ai_client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
        return resp.text
    except Exception as e:
        # Failsafe to NVIDIA if Gemini is out of credits
        if nvidia_client:
            st.caption("ℹ️ *Gemini unavailable. Using NVIDIA Backup...*")
            try:
                comp = nvidia_client.chat.completions.create(
                    model="meta/llama-3.1-70b-instruct", 
                    messages=[{"role": "user", "content": prompt}]
                )
                return comp.choices[0].message.content
            except Exception as nvidia_err:
                 return f"NVIDIA Error: {nvidia_err}"
        return "AI Error: Both primary and backup APIs failed."

# --- NEURAL TTS HELPER ---
async def generate_neural_audio(text, voice, filename="summary_temp.mp3"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def create_audio(text, voice_choice):
    if not text or len(text.strip()) == 0:
        return None
        
    clean_text = re.sub(r'[^a-zA-Z0-9\s.,!?\'"-]', '', text).strip()[:4000]
    filename = "summary_temp.mp3"
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_neural_audio(clean_text, voice_choice, filename))
        
        with open(filename, "rb") as f:
            audio_data = f.read()
            
        os.remove(filename)
        return audio_data
    except Exception as e:
        st.error(f"TTS Error: {e}")
        return None

# --- UI ---
st.title("📚 Comic Vault Analyzer")

with st.sidebar:
    # 1. SEARCH AT THE TOP
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
            
            trigger = st.button("Analyze", use_container_width=True) or st.session_state.auto_analyze
        else: st.warning("Not found.")
    else:
        trigger = False

    st.divider()
    
    # 2. VOICE SETTINGS IN THE MIDDLE
    st.header("Voice Settings")
    voice_map = {
        "Christopher (Deep, Cinematic)": "en-US-ChristopherNeural",
        "Aria (Clear, Professional)": "en-US-AriaNeural",
        "Guy (Casual, Conversational)": "en-US-GuyNeural",
        "Jenny (Friendly, Upbeat)": "en-US-JennyNeural",
        "Steffan (Authoritative, Clear)": "en-US-SteffanNeural",
        "Ryan (British, Sophisticated)": "en-GB-RyanNeural",
        "Natasha (Australian, Smooth)": "en-AU-NatashaNeural"
    }
    sel_voice_label = st.selectbox("Narrator", options=list(voice_map.keys()))
    
    st.divider()

    # 3. HISTORY AT THE BOTTOM
    st.header("🕰️ History")
    if st.session_state.history:
        st.selectbox("Recent:", ["Select..."] + list(reversed(st.session_state.history)), key="history_selector", on_change=load_from_history)
        st.button("🗑️ Clear", on_click=clear_history, use_container_width=True)
    else:
        st.caption("No recent history.")

# --- STEP 1: FETCH DATA & GENERATE TEXT ONLY ---
if query and 'vid' in locals() and trigger:
    st.session_state.auto_analyze = False
    
    with st.spinner("Analyzing comic archives..."):
        data = get_issue_data(vid, st.session_state.issue_num)
        if data:
            summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num)
            st.session_state.current_summary = summary
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            
            # Save history persistently
            if st.session_state.current_title not in st.session_state.history:
                st.session_state.history.append(st.session_state.current_title)
                save_history(st.session_state.history)
            
            st.session_state.audio_bytes = None
            st.session_state.b64_audio = None
            if summary:
                st.session_state.needs_audio = True
        else:
            st.error("Issue not found.")
            st.session_state.current_summary = None

# --- STEP 2: DISPLAY TEXT IMMEDIATELY ---
if st.session_state.current_summary:
    col_a, col_b = st.columns([1, 2])
    with col_a:
        if st.session_state.current_img: 
            st.image(st.session_state.current_img)
    with col_b:
        st.subheader(st.session_state.current_title)
        with st.container(border=True): 
            st.markdown(st.session_state.current_summary)
        
        st.divider()
        st.caption("🎧 **Listen to the Deep Dive**")
        
        # --- STEP 3: GENERATE AUDIO IN THE BACKGROUND ---
        if st.session_state.needs_audio:
            with st.spinner("🎙️ Recording narrator voice..."):
                selected_voice_code = voice_map[sel_voice_label]
                audio_bytes = create_audio(st.session_state.current_summary, selected_voice_code)
                st.session_state.audio_bytes = audio_bytes
                
                if audio_bytes:
                    st.session_state.b64_audio = base64.b64encode(audio_bytes).decode()
                
                st.session_state.needs_audio = False
            
            st.rerun()

        # --- STEP 4: DISPLAY THE PLAYER ---
        elif st.session_state.b64_audio:
            current_theme = {
                'player': '#1a1c24',
                'accent': '#00d4ff',
                'text': '#ffffff'
            }
            
            realtime_player_html = f"""
            <!DOCTYPE html>
            <html>
            <head><style>body {{ margin: 0; padding: 0; background-color: transparent; }} .player-box {{ background-color: {current_theme['player']}; padding: 15px; border-radius: 10px; border-left: 4px solid {current_theme['accent']}; font-family: sans-serif; color: {current_theme['text']}; }}</style></head>
            <body>
                <div class="player-box">
                    <audio id="narrator-audio" controls autoplay style="width: 100%;"><source src="data:audio/mp3;base64,{st.session_state.b64_audio}" type="audio/mp3"></audio>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 12px;">
                        <label for="speed-slider" style="font-size: 0.95rem; font-weight: 500;">🏃 Playback Speed: <span id="speed-display">1.0x</span></label>
                        <input type="range" id="speed-slider" min="0.5" max="2.0" step="0.1" value="1.0" style="width: 50%; cursor: pointer;">
                    </div>
                </div>
                <script>
                    const audio = document.getElementById("narrator-audio");
                    const slider = document.getElementById("speed-slider");
                    const display = document.getElementById("speed-display");
                    slider.addEventListener("input", function() {{ audio.playbackRate = this.value; display.textContent = parseFloat(this.value).toFixed(1) + "x"; }});
                </script>
            </body>
            </html>
            """
            components.html(realtime_player_html, height=120)
            
            safe_title = "".join([c for c in st.session_state.current_title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
            st.download_button(
                label="💾 Download Audio File",
                data=st.session_state.audio_bytes,
                file_name=f"{safe_title}.mp3",
                mime="audio/mp3",
                use_container_width=True
            )
        else:
            st.warning("⚠️ Audio could not be generated.")
