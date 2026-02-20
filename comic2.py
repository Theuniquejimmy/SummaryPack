import streamlit as st
import requests
import os
import io
import re
from PIL import Image
from google import genai
from groq import Groq  # New Import

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Comic Vault Analyzer", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stTextInput > div > div > input { color: #00d4ff; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    </style>
    """, unsafe_allow_html=True)

# --- API KEYS ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GROQ_KEY = os.environ.get("GROQ_KEY") # Ensure this is in your env variables

if not COMIC_VINE_KEY or not GEMINI_KEY:
    st.error("Missing core API keys! Please check your environment variables.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_KEY)
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

# --- HELPER FUNCTIONS ---
@st.cache_data
def fetch_volumes(query):
    search_url = "https://comicvine.gamespot.com/api/search/"
    params = {
        "api_key": COMIC_VINE_KEY,
        "format": "json",
        "query": query,
        "resources": "volume",
        "limit": 20
    }
    headers = {"User-Agent": "ComicVaultStreamlit/1.0"}
    try:
        response = requests.get(search_url, params=params, headers=headers).json()
        results = response.get('results', [])
        
        def extract_year(res):
            year_str = str(res.get('start_year', '9999'))
            match = re.search(r'(\d{4})', year_str)
            return int(match.group(1)) if match else 9999

        results.sort(key=extract_year)
        return results
    except Exception as e:
        st.error(f"Search error: {e}")
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
    except Exception:
        return None

def generate_ai_summary(issue_data, series_name, issue_num):
    char_list = issue_data.get('character_credits') or []
    character_names = ", ".join([char['name'] for char in char_list])
    raw_desc = issue_data.get('deck') or issue_data.get('description') or "No description provided."
    
    prompt = f"""
    Act as a helpful, conversational comic book expert. 
    What is {series_name} #{issue_num} about? Please give me as much detail as possible.
    
    RULES: No spoilers for future issues. Use thourought thought out paragraphs. Use bullet points (-).
    DATA:
    Series: {series_name}
    Issue: {issue_num}
    Title: {issue_data.get('name', 'Unknown')}
    Plot: {str(raw_desc)[:2000]}
    Characters: {character_names}
    """
    
    # --- TRY GEMINI FIRST ---
    try:
        response = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return f"**[Gemini AI]**\n\n{response.text}"
    
    except Exception as gemini_err:
        # --- FALLBACK TO GROQ ---
        if groq_client:
            try:
                # Use st.caption for a much smaller, subtle notification
                st.caption("ℹ️ *Gemini busy; using Groq backup*") 
                
                completion = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                )
                return f"**[Groq Backup AI]**\n\n{completion.choices[0].message.content}"
            except Exception as groq_err:
                return f"Both AI services failed. Gemini Error: {gemini_err} | Groq Error: {groq_err}"
        else:
            return f"Gemini failed and no Groq key was found. Error: {gemini_err}"

# --- MAIN UI ---
st.title("📚 Comic Vault Analyzer")

with st.sidebar:
    st.header("1. Search Series")
    series_query = st.text_input("Enter Series Name", placeholder="e.g. Daredevil")
    
    if series_query:
        volumes = fetch_volumes(series_query)
        if volumes:
            st.caption(f"Found {len(volumes)} volumes")
            vol_options = {f"{v['name']} ({v['start_year']})": v['id'] for v in volumes}
            selected_vol_name = st.selectbox("2. Select Volume", options=list(vol_options.keys()))
            volume_id = vol_options[selected_vol_name]
            
            st.header("3. Issue Details")
            issue_num = st.text_input("Issue Number", value="1")
            analyze_clicked = st.button("Analyze Issue", use_container_width=True)
        else:
            st.warning("No volumes found.")

if series_query and 'volume_id' in locals():
    if analyze_clicked:
        with st.spinner("Fetching data and consulting the archives..."):
            issue_data = get_issue_data(volume_id, issue_num)
            
            if issue_data:
                col1, col2 = st.columns([1, 2])
                with col1:
                    img_url = issue_data.get('image', {}).get('medium_url')
                    if img_url:
                        st.image(img_url, use_container_width=True)
                with col2:
                    st.subheader(f"{selected_vol_name} #{issue_num}")
                    summary = generate_ai_summary(issue_data, selected_vol_name, issue_num)
                    st.markdown(summary)
            else:
                st.error(f"Issue #{issue_num} not found.")