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

# --- THE ALL-IN-ONE GEMINI HISTORIAN (3.1 ELITE VERSION) ---
@st.cache_data(show_spinner=False)
def generate_ai_summary(issue_data, series_name, issue_num, alt_name=""):
    import random 
    
    # 1. Prepare Data
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    
    needs_search = len(plot.strip()) < 50
    base_title = series_name.split(' (')[0]
    search_target = f"{base_title} {alt_name} issue {issue_num}" if alt_name else f"{series_name} issue {issue_num}"
    
    # 2. Advanced Reasoning Prompt
    prompt = f"""
    You are an elite comic book historian using advanced reasoning. 
    Write a 500-800 word deep-dive into {series_name} #{issue_num}.
    
    CONTEXTUAL DATA:
    - Target: {series_name} Issue #{issue_num}
    - Creators: {creators}
    - Characters: {chars}
    """
    
    if needs_search:
        prompt += f"""
        CRITICAL: The local database is empty. USE YOUR GOOGLE SEARCH TOOL to find the exact plot for: "{search_target}".
        SNIPER FILTERING RULE: Wiki results often contain summaries for entire arcs. You MUST verify that the events you summarize occur specifically in issue #{issue_num}. 
        If the search results are for the wrong issue, do not summarize them; state that the specific issue data is missing.
        """
    else:
        prompt += f"\nSOURCE PLOT: {plot}"
        
    prompt += "\nFormat with these Markdown headings: Context, Detailed Plot, Key Moments, Legacy."
    
    # 3. Model Hierarchy (Optimized for Speed)
    # 2.5 Flash is the "Goldilocks" model: Faster than Pro, smarter than 2.0.
    models_to_try = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-pro-preview"]
    
    for model_name in models_to_try:
        # Reduced initial wait time for a snappier feel
        wait_time = 5 
        for attempt in range(2): # Reduced from 3 to 2 attempts per model to fail-over faster
            try:
                from google.genai import types
                config = types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())] if needs_search else None,
                    temperature=0.7 # Lowered slightly for faster, more focused output
                )
                
                resp = ai_client.models.generate_content(model=model_name, contents=prompt, config=config)
                return resp.text
                
            except Exception as e:
                err = str(e).upper()
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    sleep_gap = wait_time + random.uniform(0.5, 2.0)
                    st.toast(f"⚡ {model_name} rate limited. Trying next model...")
                    time.sleep(sleep_gap)
                    break # Immediately jump to the next model in the list instead of retrying the same one
                else:
                    break
                    
    # 4. Final Failover
    if nvidia_client:
        st.caption("ℹ️ *Gemini models exhausted. Using NVIDIA Backup...*")
        try:
            comp = nvidia_client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct", 
                messages=[{"role": "user", "content": prompt}]
            )
            return comp.choices[0].message.content
        except Exception: pass
             
    return "AI Error: The frontier models are currently over capacity. Please wait 60 seconds."
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



