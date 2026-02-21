import streamlit as st
import requests
import os
import io
import re
from PIL import Image
from google import genai
from groq import Groq

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; text-align: center; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    /* Small tweak to make the arrow buttons look seamless */
    div[data-testid="column"] button { padding-left: 0; padding-right: 0; }
    </style>
    """, unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "history" not in st.session_state:
    st.session_state.history = []
if "issue_num" not in st.session_state:
    st.session_state.issue_num = "1"
if "auto_analyze" not in st.session_state:
    st.session_state.auto_analyze = False

# --- CALLBACKS FOR ARROW BUTTONS ---
def prev_issue():
    try:
        current = int(st.session_state.issue_num)
        if current > 1:
            st.session_state.issue_num = str(current - 1)
            st.session_state.auto_analyze = True
    except ValueError:
        pass # Ignore if the user typed something weird like "1-A"

def next_issue():
    try:
        current = int(st.session_state.issue_num)
        st.session_state.issue_num = str(current + 1)
        st.session_state.auto_analyze = True
    except ValueError:
        pass

# --- API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GROQ_KEY = os.environ.get("GROQ_KEY")

if not COMIC_VINE_KEY or not GEMINI_KEY:
    st.error("Missing core API keys! Please check your environment variables.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_KEY)
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

# --- HELPER FUNCTIONS ---
@st.cache_data
def fetch_volumes(query):
    search_url = "https://comicvine.gamespot.com/api/search/"
    params = {"api_key": COMIC_VINE_KEY, "format": "json", "query": query, "resources": "volume", "limit": 50}
    headers = {"User-Agent": "ComicVaultStreamlit/1.0"}
    try:
        response = requests.get(search_url, params=params, headers=headers).json()
        results = response.get('results', [])
        
        def extract_year(res):
            match = re.search(r'(\d{4})', str(res.get('start_year', '9999')))
            return int(match.group(1)) if match else 9999

        results.sort(key=extract_year)
        return results
    except:
        return []

@st.cache_data
def get_issue_data(volume_id, issue_num):
    issue_url = "https://comicvine.gamespot.com/api/issues/"
    params = {
        "api_key": COMIC_VINE_KEY,
        "format": "json",
        "filter": f"volume:{volume_id},issue_number:{issue_num}",
        "field_list": "name,deck,description,character_credits,image"
    }
    headers = {"User-Agent": "ComicVaultStreamlit/1.0"}
    try:
        resp = requests.get(issue_url, params=params, headers=headers).json()
        results = resp.get('results', [])
        return results[0] if results else None
    except:
        return None

def generate_ai_summary(issue_data, series_name, issue_num):
    char_list = issue_data.get('character_credits') or []
    character_names = ", ".join([char['name'] for char in char_list])
    raw_desc = issue_data.get('deck') or issue_data.get('description') or "No description provided."
    safe_desc = str(raw_desc)[:5000] 
    
    prompt = f"""
    Act as an expert comic book historian giving a deep-dive, comprehensive summary of {series_name} #{issue_num}. 
    
    Structure your response with these specific sections:
    - CONTEXT: Where does this fit in the character's history?
    - DETAILED PLOT: A thorough breakdown of the events.
    - KEY MOMENTS: Important reveals or beats.
    - SIGNIFICANCE: Why this issue matters.
    
    RULES: Write at least 4-5 substantial paragraphs. No spoilers for future issues. No Markdown.
    DATA: {series_name} #{issue_num}. Plot: {safe_desc}. Characters: {character_names}
    """
    
    try:
        response = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return f"**[Gemini Deep Dive]**\n\n{response.text}"
    except:
        if groq_client:
            st.caption("ℹ️ *Gemini busy; using Groq for Deep Dive*")
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
            )
            return f"**[Groq Deep Dive]**\n\n{completion.choices[0].message.content}"
        return "AI failed."

# --- MAIN UI ---
st.title("📚 Comic Vault Analyzer")

with st.sidebar:
    st.header("🕰️ Recent Searches")
    h_series = ""
    if st.session_state.history:
        history_options = ["Select from history..."] + list(reversed(st.session_state.history))
        selected_history = st.selectbox("Jump back to:", options=history_options)
        if selected_history != "Select from history...":
            h_series = selected_history.split(" #")[0]
            # Update session state with the selected history issue
            st.session_state.issue_num = selected_history.split(" #")[1]

    st.divider()
    st.header("1. Search Series")
    series_query = st.text_input("Series Name", value=h_series if h_series else "")
    
    if series_query:
        volumes = fetch_volumes(series_query)
        if volumes:
            vol_options = {f"{v['name']} ({v['start_year']})": v['id'] for v in volumes}
            selected_vol_name = st.selectbox("2. Select Volume", options=list(vol_options.keys()))
            volume_id = vol_options[selected_vol_name]
            
            st.header("3. Issue Details")
            
            # --- NEW: Arrow Button Navigation UI ---
            col_prev, col_input, col_next = st.columns([1, 2, 1])
            with col_prev:
                # Use a markdown spacing trick to align buttons with the text input
                st.markdown("<br>", unsafe_allow_html=True)
                st.button("◄", on_click=prev_issue, use_container_width=True)
                
            with col_input:
                st.text_input("Issue", key="issue_num") # Bound to st.session_state.issue_num
                
            with col_next:
                st.markdown("<br>", unsafe_allow_html=True)
                st.button("►", on_click=next_issue, use_container_width=True)

            analyze_btn_clicked = st.button("Analyze Issue", use_container_width=True)
            
            # Combine manual click and automatic arrow trigger
            analyze_triggered = analyze_btn_clicked or st.session_state.auto_analyze
            
        else:
            st.warning("No volumes found.")

# --- DISPLAY AREA ---
if series_query and 'volume_id' in locals():
    if analyze_triggered:
        # Reset the auto-trigger so it doesn't loop
        st.session_state.auto_analyze = False 
        
        with st.spinner(f"Consulting the archives for Issue #{st.session_state.issue_num}..."):
            issue_data = get_issue_data(volume_id, st.session_state.issue_num)
            
            if issue_data:
                # Add to history
                history_item = f"{selected_vol_name} #{st.session_state.issue_num}"
                if history_item not in st.session_state.history:
                    st.session_state.history.append(history_item)
                
                col1, col2 = st.columns([1, 2])
                with col1:
                    img_url = issue_data.get('image', {}).get('medium_url')
                    if img_url: st.image(img_url, use_container_width=True)
                with col2:
                    st.subheader(history_item)
                    with st.container(border=True):
                        summary = generate_ai_summary(issue_data, selected_vol_name, st.session_state.issue_num)
                        st.markdown(summary)
            else:
                st.error(f"Issue #{st.session_state.issue_num} not found in this volume.")
