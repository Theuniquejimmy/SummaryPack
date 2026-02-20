import streamlit as st
import requests
import urllib.parse
from bs4 import BeautifulSoup
import base64
import edge_tts
import asyncio

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot"
}

# --- NEURAL TTS HELPER ---
async def generate_neural_audio(text, voice, filename="lore.mp3"):
    """Generates high-quality audio using Microsoft's Neural voices."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def create_audio(text, voice_choice):
    # Mapping friendly names to the actual neural voice codes
    voice_map = {
        "Christopher (Deep, Cinematic)": "en-US-ChristopherNeural",
        "Aria (Clear, Professional)": "en-US-AriaNeural",
        "Guy (Casual, Conversational)": "en-US-GuyNeural"
    }
    selected_voice = voice_map.get(voice_choice, "en-US-ChristopherNeural")
    
    # Run the async TTS generation safely in Streamlit
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(generate_neural_audio(text, selected_voice))

# --- THE 2-STEP API CRAWLER ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json"}
    
    try:
        search_res = requests.get(api_url, params=search_params, timeout=10).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results: return None, None
            
        exact_title = search_results[0]["title"]
        page_url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{urllib.parse.quote(exact_title.replace(' ', '_'))}"
        
        parse_params = {"action": "parse", "page": exact_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, timeout=10).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        
        if not html_text: return None, None
            
        soup = BeautifulSoup(html_text, 'html.parser')
        for edit_btn in soup.find_all('span', class_='mw-editsection'): edit_btn.decompose()
        
        start_node = None
        story_keywords = ['plot', 'synopsis', 'summary', 'episode_summary']
        
        for header in soup.find_all(['h2', 'h3']):
            h_text, h_id = header.get_text().lower(), header.get('id', '').lower()
            inner_span = header.find('span')
            span_id = inner_span.get('id', '').lower() if inner_span else ""
            
            if any(key in h_text or key in h_id or key in span_id for key in story_keywords):
                start_node = header
                break
                
        if start_node:
            content = []
            for sibling in start_node.find_next_siblings():
                if sibling.name in ['h2', 'h3', 'h4']:
                    h_text = sibling.get_text().strip()
                    stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos']
                    if any(stop in h_text.lower() for stop in stop_words): break 
                    if h_text: content.append(f"<br><h3>{h_text}</h3>")
                elif sibling.name in ['p', 'ul', 'ol']:
                    txt = sibling.get_text().strip()
                    if txt: content.append(f"<p>{txt}</p>")
            
            if content: return "".join(content), page_url
    except Exception: pass
    return None, None

# --- STATE INITIALIZATION ---
if 'lore_text' not in st.session_state:
    st.session_state.lore_text = None
    st.session_state.ep_name = None
    st.session_state.image_url = None
    st.session_state.wiki_url = None

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: s_val = st.number_input("Season", min_value=1, value=1)
            with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

            if st.button("🔓 Extract Full Lore", use_container_width=True):
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                api_res = requests.get(api_url)
                
                if api_res.status_code == 200:
                    api_data = api_res.json()
                    if "name" in api_data:
                        raw_text, found_url = get_raw_lore(wiki_slug, api_data['name'])
                        if raw_text:
                            st.session_state.lore_text = raw_text
                            st.session_state.ep_name = api_data['name']
                            st.session_state.image_url = api_data.get('image', {}).get('original')
                            st.session_state.wiki_url = found_url
                        else:
                            st.error(f"Text not found. Ensure the episode exists on {wiki_slug}.fandom.com.")
                            st.session_state.lore_text = None
                    else: st.error("Episode name not found.")
                else: st.error("Could not locate this specific episode number.")

            # --- THE PRO READER UI ---
            if st.session_state.lore_text:
                st.divider()
                
                # Reader Settings Dashboard
                with st.expander("⚙️ Reader Settings", expanded=False):
                    rc1, rc2, rc3 = st.columns(3)
                    theme = rc1.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    font_size = rc2.slider("Text Size", min_value=1.0, max_value=2.5, value=1.2, step=0.1)
                    voice_setting = rc3.selectbox("Narrator Voice", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
                
                theme_styles = {
                    "Dark": {"bg": "#121212", "text": "#e0e0e0", "accent": "#3b82f6"},
                    "Sepia": {"bg": "#f4ecd8", "text": "#433422", "accent": "#8b5a2b"},
                    "Light": {"bg": "#ffffff", "text": "#333333", "accent": "#2563eb"}
                }
                current_theme = theme_styles[theme]

                st.markdown(f"""
                    <style>
                    .pro-reader {{
                        background-color: {current_theme['bg']};
                        color: {current_theme['text']};
                        font-family: sans-serif;
                        font-size: {font_size}rem;
                        line-height: 1.8;
                        padding: 40px 30px;
                        border-radius: 12px;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                        max-width: 800px;
                        margin: 0 auto;
                        transition: all 0.3s ease;
                    }}
                    .pro-reader h3 {{ color: {current_theme['accent']}; margin-top: 1.5em; }}
                    </style>
                """, unsafe_allow_html=True)

                st.subheader(st.session_state.ep_name)
                
                if st.session_state.image_url:
                    st.image(st.session_state.image_url, use_container_width=True)
                
                # Audio Player (Now using Neural TTS)
                if st.button("🔊 Play Cinematic Narration", use_container_width=True):
                    with st.spinner("Synthesizing neural audio... (this takes a few seconds for long plots)"):
                        clean_tts_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                        
                        # Generate the audio using our new Edge-TTS function
                        create_audio(clean_tts_text, voice_setting)
                        
                        with open("lore.mp3", "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                            st.markdown(f'<audio controls autoplay style="width:100%; margin-bottom: 20px;"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: [Fandom Wiki]({st.session_state.wiki_url})")

    except Exception as e:
        st.error(f"System Error: {e}")
