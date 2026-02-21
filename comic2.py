import streamlit as st
import requests
import os
import re
import asyncio
import edge_tts
import base64
import streamlit.components.v1 as components
from google import genai
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

# --- SESSION STATE ---
if "history" not in st.session_state:
    st.session_state.history = []
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
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "filter": f"volume:{volume_id},issue_number:{issue_num}", "field_list": "name,deck,description,character_credits,image"}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        return res.get('results', [])[0] if res.get('results') else None
    except Exception: return None

def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "No data")[:5000]
    
    prompt = f"""
    Act as a passionate, encyclopedic comic book historian. Your goal is to write a highly detailed, comprehensive deep-dive into {series_name} #{issue_num}. 
    
    The raw data below might be brief, but you MUST use your extensive internal knowledge of comic lore to expand on it. Structure your response using Markdown headings for these exact sections:
    
    ### 🌍 Context & Background
    Explain what was happening in the comic universe and the character's life leading up to this issue. Who is the creative team, and what era/run is this?
    
    ### 📖 Detailed Plot Summary
    Provide an exhaustive, multi-paragraph recounting of the issue's events. Do not just give a blurb; narrate the key actions, conflicts, and character dynamics.
    
    ### 💥 Key Moments
    Use bullet points to list the most iconic panels, character beats, or reveals in this specific issue.
    
    ### 🏛️ Legacy & Significance
    Why does this issue matter? Discuss its impact, first appearances, or how it sets up the future (without spoiling specific future plotlines).
    
    RULES:
    - Your output MUST be a substantial, long-form read (at least 500-800 words).
    - Be enthusiastic, professional, and authoritative.
    - Do NOT be constrained by the briefness of the "Plot Snippet".
    
    RAW DATA:
    Series: {series_name}
    Issue: {issue_num}
    Plot Snippet: {plot}
    Characters Involved: {chars}
    """
    
    try:
        resp = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return resp.text
    except Exception:
        if nvidia_client:
            st.caption("ℹ️ *Using NVIDIA Backup*")
            comp = nvidia_client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct", 
                messages=[{"role": "user", "content": prompt}]
            )
            return comp.choices[0].message.content
        return "AI Error"

# --- NEURAL TTS HELPER ---
async def generate_neural_audio(text, voice, filename="summary_temp.mp3"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def create_audio(text, voice_choice):
    if not text or len(text.strip()) == 0:
        return None
        
    # Safely strip out all the Markdown symbols (like #, *) and emojis so the TTS doesn't crash
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
    st.header("🕰️ History")
    h_series = ""
    if st.session_state.history:
        sel_h = st.selectbox("Recent:", ["Select..."] + list(reversed(st.session_state.history)))
        if sel_h != "Select...":
            h_series = sel_h.split(" #")[0]
            st.session_state.issue_num = sel_h.split(" #")[1]
        st.button("🗑️ Clear", on_click=clear_history, use_container_width=True)
    
    st.divider()
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
    st.header("Search")
    query = st.text_input("Series", value=h_series)
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

# --- DISPLAY ---
if query and 'vid' in locals() and trigger:
    st.session_state.auto_analyze = False
    with st.spinner("Analyzing & Generating Audio..."):
        data = get_issue_data(vid, st.session_state.issue_num)
        if data:
            summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num)
            st.session_state.current_summary = summary
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            
            if st.session_state.current_title not in st.session_state.history:
                st.session_state.history.append(st.session_state.current_title)
            
            if summary:
                selected_voice_code = voice_map[sel_voice_label]
                audio_bytes = create_audio(summary, selected_voice_code)
                st.session_state.audio_bytes = audio_bytes
                if audio_bytes:
                    st.session_state.b64_audio = base64.b64encode(audio_bytes).decode()
                else:
                    st.session_state.b64_audio = None
            else:
                st.session_state.audio_bytes = None
                st.session_state.b64_audio = None
        else:
            st.error("Issue not found.")

if st.session_state.current_summary:
    col_a, col_b = st.columns([1, 2])
    with col_a:
        if st.session_state.current_img: 
            st.image(st.session_state.current_img)
    with col_b:
        st.subheader(st.session_state.current_title)
        with st.container(border=True): 
            st.markdown(st.session_state.current_summary)
        
        # Custom Realtime Audio Player UI
        st.divider()
        st.caption("🎧 **Listen to the Deep Dive**")
        
        if st.session_state.b64_audio:
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
            
            # Download Button
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
