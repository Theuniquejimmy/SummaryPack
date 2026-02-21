import streamlit as st
import streamlit.components.v1 as components
import requests
import urllib.parse
from bs4 import BeautifulSoup
import base64
import edge_tts
import asyncio
from ebooklib import epub
import os

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot",
    "Gilmore Girls": "gilmoregirls",
    "ER": "er"
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

# --- THE SMART SECTION SCRAPER ---
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
        
        story_keywords = ['plot', 'synopsis', 'summary', 'episode_summary']
        best_content = []
        
        for header in soup.find_all(['h2', 'h3']):
            h_text, h_id = header.get_text().lower(), header.get('id', '').lower()
            inner_span = header.find('span')
            span_id = inner_span.get('id', '').lower() if inner_span else ""
            
            if any(key in h_text or key in h_id or key in span_id for key in story_keywords):
                content = []
                for sibling in header.find_next_siblings():
                    if sibling.name in ['h2', 'h3', 'h4']:
                        h_text_sib = sibling.get_text().strip()
                        stop_words = [
                            'cast', 'trivia', 'gallery', 'references', 'production', 
                            'credits', 'quotes', 'videos', 'music', 'notes', 
                            'continuity', 'external links', 'see also', 'reception', 'external'
                        ]
                        if any(stop in h_text_sib.lower() for stop in stop_words): 
                            break 
                        if h_text_sib: 
                            content.append(f"<br><h3>{h_text_sib}</h3>")
                        
                    elif sibling.name in ['p', 'ul', 'ol']:
                        txt = sibling.get_text().strip()
                        if txt: content.append(f"<p>{txt}</p>")
                
                if len("".join(content)) > len("".join(best_content)):
                    best_content = content
        
        if best_content: return "".join(best_content), page_url
    except Exception: pass
    return None, None

# --- EPUB COMPILER WITH TVMAZE BACKUP ---
def build_season_epub(show_id, show_name, season_num, wiki_slug):
    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodes").json()
    season_episodes = [ep for ep in ep_data if ep['season'] == season_num]
    
    if not season_episodes: return None
        
    book = epub.EpubBook()
    book.set_identifier(f"{show_name.replace(' ', '')}_S{season_num}")
    book.set_title(f"{show_name} - Season {season_num} Lore")
    book.set_language('en')
    book.add_author('TV Vault App')
    
    chapters = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, ep in enumerate(season_episodes):
        status_text.text(f"Scraping Episode {ep['number']}: {ep['name']}...")
        
        raw_text, _ = get_raw_lore(wiki_slug, ep['name'])
        tvmaze_summary = ep.get('summary', '')
        
        fandom_len = len(BeautifulSoup(raw_text, "html.parser").get_text()) if raw_text else 0
        tvmaze_len = len(BeautifulSoup(tvmaze_summary, "html.parser").get_text()) if tvmaze_summary else 0
        
        final_text = ""
        if raw_text and fandom_len >= tvmaze_len:
            final_text = raw_text
        elif tvmaze_summary:
            final_text = tvmaze_summary
            
        if final_text:
            c = epub.EpubHtml(title=f"Episode {ep['number']}: {ep['name']}", file_name=f"chap_{ep['number']}.xhtml", lang='en')
            c.content = f"<h2>Episode {ep['number']}: {ep['name']}</h2>\n" + final_text
            book.add_item(c)
            chapters.append(c)
            
        progress_bar.progress((i + 1) / len(season_episodes))
        
    if not chapters:
        status_text.text("Failed to find lore for any episodes in this season.")
        return None
        
    status_text.text("Binding EPUB file...")
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    style = 'h2 { text-align: center; margin-bottom: 2em; } h3 { margin-top: 1.5em; } p { line-height: 1.6; text-align: justify; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)
    book.spine = ['nav'] + chapters
    
    filename = f"{show_name.replace(' ', '_')}_Season_{season_num}.epub"
    epub.write_epub(filename, book)
    
    status_text.empty()
    progress_bar.empty()
    return filename

# --- STATE INITIALIZATION ---
if 's_val' not in st.session_state: st.session_state.s_val = 1
if 'ep_val' not in st.session_state: st.session_state.ep_val = 1
if 'auto_fetch' not in st.session_state: st.session_state.auto_fetch = False
if 'epub_ready' not in st.session_state: st.session_state.epub_ready = None

if 'lore_text' not in st.session_state:
    st.session_state.lore_text = None
    st.session_state.ep_name = None
    st.session_state.image_url = None
    st.session_state.wiki_url = None
    st.session_state.b64_audio = None

def load_next_episode():
    st.session_state.ep_val += 1
    st.session_state.auto_fetch = True
    st.session_state.lore_text = None
    st.session_state.b64_audio = None

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

try:
    if query:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: st.number_input("Season", min_value=1, key="s_val")
            with c2: st.number_input("Episode", min_value=1, key="ep_val")

            # --- EPUB EXPORT ---
            if st.button(f"📚 Export Season {st.session_state.s_val} as EPUB", use_container_width=True):
                compiled_file = build_season_epub(show_data['id'], show_data['name'], st.session_state.s_val, wiki_slug)
                if compiled_file:
                    st.session_state.epub_ready = compiled_file
                    st.success("Season Compiled Successfully!")
                else:
                    st.error("Could not compile season. No lore found.")
            
            if st.session_state.epub_ready and os.path.exists(st.session_state.epub_ready):
                with open(st.session_state.epub_ready, "rb") as file:
                    st.download_button(label="⬇️ Download Your EPUB Book", data=file, file_name=st.session_state.epub_ready, mime="application/epub+zip", use_container_width=True)

            st.divider()

            # --- READER EXTRACTION WITH BACKUP ---
            if st.button("🔓 Read Single Episode", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}"
                api_res = requests.get(api_url)
                
                if api_res.status_code == 200:
                    api_data = api_res.json()
                    if "name" in api_data:
                        raw_text, found_url = get_raw_lore(wiki_slug, api_data['name'])
                        tvmaze_summary = api_data.get('summary', '')
                        
                        fandom_len = len(BeautifulSoup(raw_text, "html.parser").get_text()) if raw_text else 0
                        tvmaze_len = len(BeautifulSoup(tvmaze_summary, "html.parser").get_text()) if tvmaze_summary else 0
                        
                        if raw_text and fandom_len >= tvmaze_len:
                            st.session_state.lore_text = raw_text
                            st.session_state.wiki_url = found_url
                        elif tvmaze_summary:
                            st.session_state.lore_text = tvmaze_summary
                            st.session_state.wiki_url = api_data.get('url', 'https://www.tvmaze.com')
                            st.toast("Fandom stub detected. Loaded higher-quality TVMaze summary!", icon="⚖️")
                        else:
                            st.session_state.lore_text = None
                            st.error(f"No plot summary found on Fandom or TVMaze.")
                            
                        if st.session_state.lore_text:
                            st.session_state.ep_name = api_data['name']
                            st.session_state.image_url = api_data.get('image', {}).get('original')
                            st.session_state.b64_audio = None 

                    else: st.error("Episode name not found.")
                else: 
                    st.warning("You may have reached the end of the season! Adjust the Season tracker above.")

            # --- THE PRO READER UI ---
            if st.session_state.lore_text:
                
                with st.expander("⚙️ Reader Settings", expanded=False):
                    rc1, rc2 = st.columns([1, 2])
                    theme = rc1.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    voice_setting = rc2.selectbox("Narrator Voice", [
                        "Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)",
                        "Jenny (Friendly, Upbeat)", "Steffan (Authoritative, Clear)", "Ryan (British, Sophisticated)", "Natasha (Australian, Smooth)"
                    ])
                
                theme_styles = {
                    "Dark": {"bg": "#121212", "text": "#e0e0e0", "accent": "#3b82f6", "player": "#1e1e1e"},
                    "Sepia": {"bg": "#f4ecd8", "text": "#433422", "accent": "#8b5a2b", "player": "#e8dfc8"},
                    "Light": {"bg": "#ffffff", "text": "#333333", "accent": "#2563eb", "player": "#f3f4f6"}
                }
                current_theme = theme_styles[theme]

                st.markdown(f"""
                    <style>
                    .pro-reader {{ background-color: {current_theme['bg']}; color: {current_theme['text']}; font-family: sans-serif; font-size: 1.15rem; line-height: 1.8; padding: 30px 25px; border-radius: 12px; margin-top: 15px; }}
                    .pro-reader h3 {{ color: {current_theme['accent']}; margin-top: 1.5em; }}
                    </style>
                """, unsafe_allow_html=True)

                st.subheader(f"S{st.session_state.s_val}E{st.session_state.ep_val}: {st.session_state.ep_name}")
                if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
                
                if st.button("🔊 Generate Audio Narration", use_container_width=True):
                    with st.spinner(f"Synthesizing {voice_setting.split(' ')[0]}'s voice..."):
                        clean_tts_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                        create_audio(clean_tts_text, voice_setting)
                        with open("lore.mp3", "rb") as f:
                            st.session_state.b64_audio = base64.b64encode(f.read()).decode()

                if st.session_state.b64_audio:
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

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: [Link]({st.session_state.wiki_url})")
                
                st.divider()
                st.button(f"⏭️ Load Season {st.session_state.s_val}, Episode {st.session_state.ep_val + 1}", on_click=load_next_episode, use_container_width=True)

except Exception as e:
    st.error(f"System Error: {e}")
