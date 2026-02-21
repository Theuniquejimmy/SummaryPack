import streamlit as st
import requests
import os
import re
import io
import asyncio
import edge_tts  # New requirement: pip install edge-tts
from google import genai
from groq import Groq

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; text-align: center; font-size: 20px; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
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

# --- CALLBACKS ---
def prev_issue():
    try:
        curr = int(st.session_state.issue_num)
        if curr > 1:
            st.session_state.issue_num = str(curr - 1)
            st.session_state.auto_analyze = True
    except: pass

def next_issue():
    try:
        curr = int(st.session_state.issue_num)
        st.session_state.issue_num = str(curr + 1)
        st.session_state.auto_analyze = True
    except: pass

# --- API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GROQ_KEY = os.environ.get("GROQ_KEY")

ai_client = genai.Client(api_key=GEMINI_KEY)
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

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
    except: return []

@st.cache_data
def get_issue_data(volume_id, issue_num):
    url = "https://comicvine.gamespot.com/api/issues/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "filter": f"volume:{volume_id},issue_number:{issue_num}", "field_list": "name,deck,description,character_credits,image"}
    try:
        res = requests.get(url, params=params, headers={"User-Agent": "ComicVault/1.0"}).json()
        return res.get('results', [])[0] if res.get('results') else None
    except: return None

def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "No data")[:5000]
    prompt = f"Expert comic historian deep-dive: {series_name} #{issue_num}. Sections: Context, Plot, Key Moments, Significance. No spoilers. No Markdown. Plot: {plot}. Characters: {chars}"
    try:
        resp = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return resp.text
    except:
        if groq_client:
            comp = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}])
            return comp.choices[0].message.content
        return "AI Error"

# --- EDGE TTS ASYNC FUNCTION ---
async def generate_edge_audio(text, voice, speed):
    # speed format: "+0%", "+20%", "-10%"
    speed_str = f"{'+' if speed >= 1 else ''}{int((speed-1)*100)}%"
    communicate = edge_tts.Communicate(text, voice, rate=speed_str)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# --- MAIN UI ---
st.title("📚 Comic Vault Analyzer")

with st.sidebar:
    st.header("Voice Settings")
    # Popular high-quality Edge voices
    voice_map = {
        "Guy (Male/Authoritative)": "en-US-GuyNeural",
        "Ava (Female/Clear)": "en-US-AvaNeural",
        "Andrew (Male/Deep)": "en-US-AndrewNeural",
        "Emma (Female/Friendly)": "en-GB-EmmaNeural"
    }
    sel_voice_label = st.selectbox("Narrator", options=list(voice_map.keys()))
    v_speed = st.slider("Reading Speed", 0.5, 2.0, 1.0, 0.1)
    
    st.divider()
    st.header("Search")
    query = st.text_input("Series")
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
            st.session_state.current_summary = generate_ai_summary(data, sel_vol, st.session_state.issue_num)
            st.session_state.current_img = data.get('image', {}).get('medium_url')
            st.session_state.current_title = f"{sel_vol} #{st.session_state.issue_num}"
            
            # Generate Edge-TTS Audio
            clean_text = st.session_state.current_summary.replace("**", "").replace("- ", "")
            st.session_state.audio_bytes = asyncio.run(generate_edge_audio(clean_text, voice_map[sel_voice_label], v_speed))

if st.session_state.current_summary:
    col_a, col_b = st.columns([1, 2])
    with col_a:
        if st.session_state.current_img: st.image(st.session_state.current_img)
    with col_b:
        st.subheader(st.session_state.current_title)
        with st.container(border=True): st.markdown(st.session_state.current_summary)
        
        # Audio Player
        if "audio_bytes" in st.session_state:
            st.audio(st.session_state.audio_bytes, format='audio/mp3')
