import streamlit as st
import streamlit.components.v1 as components  # NEW IMPORT REQUIRED
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
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def create_audio(text, voice_choice):
    voice_map = {
        "Christopher (Deep, Cinematic)": "en-US-ChristopherNeural",
        "Aria (Clear, Professional)": "en-US-AriaNeural",
        "Guy (Casual, Conversational)": "en-US-GuyNeural",
        "Jenny (Friendly, Upbeat)": "en-US-JennyNeural",
        "Steffan (Authoritative, Clear)": "en-US-SteffanNeural",
        "Ryan (British, Sophisticated)": "en-GB-RyanNeural",
        "Natasha (Australian, Smooth)": "en-AU-NatashaNeural"
    }
    selected_voice = voice_map.get(voice_choice, "en-US-ChristopherNeural")
    
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
if 's_val' not in st.session_state: st.session_state.s_val = 1
if 'ep_val' not in st.session_state: st.session_state.ep_val = 1
if 'auto_fetch' not in st.session_state: st.session_state.auto_fetch = False

if 'lore_text' not in st.session_state:
    st.session_state.lore_text = None
    st.session_state.ep_name = None
    st.session_state.image_url = None
    st.session_state.wiki_url = None
    st.session_state.b64_audio = None

# --- NEXT EPISODE CALLBACK ---
def load_next_episode():
    st.session_state.ep_val += 1
    st.session_state.auto_fetch = True
    st.session_state.lore_text = None
    st.session_state.b64_audio = None

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
            with c1: st.number_input("Season", min_value=1, key="s_val")
            with c2: st.number_input("Episode", min_value=1, key="ep_val")

            if st.button("🔓 Extract Full Lore", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}"
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
                            st.session_state.b64_audio = None 
                        else:
                            st.error(f"Text not found. Ensure the episode exists on {wiki_slug}.fandom.com.")
                            st.session_state.lore_text = None
                    else: st.error("Episode name not found.")
                else: 
                    st.warning("You may have reached the end of the season! Adjust the Season tracker above.")

            # --- THE PRO READER UI ---
            if st.session_state.lore_text:
                st.divider()
                
                with st.expander("⚙️ Reader Settings", expanded=False):
                    rc1, rc2 = st.columns([1, 2])
                    theme = rc1.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    voice_setting = rc2.selectbox("Narrator Voice", [
                        "Christopher (Deep, Cinematic)", 
                        "Aria (Clear, Professional)", 
                        "Guy (Casual, Conversational)",
                        "Jenny (Friendly, Upbeat)",
                        "Steffan (Authoritative, Clear)",
                        "Ryan (British, Sophisticated)",
                        "Natasha (Australian, Smooth)"
                    ])
                
                theme_styles = {
                    "Dark": {"bg": "#121212", "text": "#e0e0e0", "accent": "#3b82f6", "player": "#1e1e1e"},
                    "Sepia": {"bg": "#f4ecd8", "text": "#433422", "accent": "#8b5a2b", "player": "#e8dfc8"},
                    "Light": {"bg": "#ffffff", "text": "#333333", "accent": "#2563eb", "player": "#f3f4f6"}
                }
                current_theme = theme_styles[theme]

                st.markdown(f"""
                    <style>
                    .pro-reader {{
                        background-color: {current_theme['bg']};
                        color: {current_theme['text']};
                        font-family: sans-serif;
                        font-size: 1.15rem;
                        line-height: 1.8;
                        padding: 30px 25px;
                        border-radius: 12px;
                        margin-top: 15px;
                    }}
                    .pro-reader h3 {{ color: {current_theme['accent']}; margin-top: 1.5em; }}
                    </style>
                """, unsafe_allow_html=True)

                st.subheader(f"S{st.session_state.s_val}E{st.session_state.ep_val}: {st.session_state.ep_name}")
                
                if st.session_state.image_url:
                    st.image(st.session_state.image_url, use_container_width=True)
                
                if st.button("🔊 Generate Audio Narration", use_container_width=True):
                    with st.spinner(f"Synthesizing {voice_setting.split(' ')[0]}'s voice..."):
                        clean_tts_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                        create_audio(clean_tts_text, voice_setting)
                        with open("lore.mp3", "rb") as f:
                            st.session_state.b64_audio = base64.b64encode(f.read()).decode()

                # --- THE FIX: ISOLATED IFRAME COMPONENT ---
                if st.session_state.b64_audio:
                    realtime_player_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                    <style>
                        body {{
                            margin: 0;
                            padding: 0;
                            background-color: transparent;
                        }}
                        .player-box {{
                            background-color: {current_theme['player']}; 
                            padding: 15px; 
                            border-radius: 10px; 
                            border-left: 4px solid {current_theme['accent']};
                            font-family: sans-serif;
                            color: {current_theme['text']};
                        }}
                    </style>
                    </head>
                    <body>
                        <div class="player-box">
                            <audio id="narrator-audio" controls autoplay style="width: 100%;">
                                <source src="data:audio/mp3;base64,{st.session_state.b64_audio}" type="audio/mp3">
                            </audio>
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 12px;">
                                <label for="speed-slider" style="font-size: 0.95rem; font-weight: 500;">
                                    🏃 Playback Speed: <span id="speed-display">1.0x</span>
                                </label>
                                <input type="range" id="speed-slider" min="0.5" max="2.0" step="0.1" value="1.0" style="width: 50%; cursor: pointer;">
                            </div>
                        </div>
                        
                        <script>
                            const audio = document.getElementById("narrator-audio");
                            const slider = document.getElementById("speed-slider");
                            const display = document.getElementById("speed-display");
                            
                            slider.addEventListener("input", function() {{
                                audio.playbackRate = this.value;
                                display.textContent = parseFloat(this.value).toFixed(1) + "x";
                            }});
                        </script>
                    </body>
                    </html>
                    """
                    # Render as an iframe so the JS executes perfectly
                    components.html(realtime_player_html, height=120)

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: [Fandom Wiki]({st.session_state.wiki_url})")
                
                st.divider()
                st.button(f"⏭️ Load Season {st.session_state.s_val}, Episode {st.session_state.ep_val + 1}", on_click=load_next_episode, use_container_width=True)

    except Exception as e:
        st.error(f"System Error: {e}")
