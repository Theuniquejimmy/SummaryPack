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
    "The Wheel of Time": "wheeloftime",
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

# --- TIER 1: FANDOM SCRAPER ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json"}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        search_res = requests.get(api_url, params=search_params, headers=headers, timeout=10).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results: return None, None
            
        exact_title = search_results[0]["title"]
        e_lower = ep_title.lower()
        
        found_tv = False
        for res in search_results:
            t_lower = res["title"].lower()
            if t_lower in [f"{e_lower} (tv episode)", f"{e_lower} (episode)", f"{e_lower} (tv series)", f"{e_lower} (tv)"]:
                exact_title = res["title"]
                found_tv = True
                break
                
        if not found_tv:
            for res in search_results:
                t_lower = res["title"].lower()
                if t_lower == e_lower:
                    if "transcript" not in t_lower:
                        exact_title = res["title"]
                        break

        page_url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{urllib.parse.quote(exact_title.replace(' ', '_'))}"
        
        parse_params = {"action": "parse", "page": exact_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, headers=headers, timeout=10).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        
        if not html_text: return None, None
            
        soup = BeautifulSoup(html_text, 'html.parser')
        for edit_btn in soup.find_all('span', class_='mw-editsection'): edit_btn.decompose()
        
        story_keywords = ['plot', 'synopsis', 'summary', 'episode_summary']
        stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos', 'music', 'notes', 'continuity', 'external links', 'see also', 'reception', 'external', 'locations', 'appearances']
        
        best_content = []
        current_content = []
        in_story = False
        
        for tag in soup.find_all(['h2', 'h3', 'h4', 'p', 'ul', 'ol']):
            if tag.find_parent('table') or tag.find_parent('aside') or tag.get('id') == 'toc': continue
                
            if tag.name in ['h2', 'h3']:
                h_text, h_id = tag.get_text().lower(), tag.get('id', '').lower()
                if any(stop in h_text for stop in stop_words):
                    if in_story:
                        if len("".join(current_content)) > len("".join(best_content)): best_content = current_content
                        in_story = False
                        current_content = []
                    continue
                
                if any(key in h_text or key in h_id for key in story_keywords):
                    if in_story: current_content.append(f"<br><h3>{tag.get_text().strip()}</h3>")
                    else:
                        in_story = True
                        current_content = []
                    continue
                
                if in_story and tag.name == 'h2':
                    if len("".join(current_content)) > len("".join(best_content)): best_content = current_content
                    in_story = False
                    current_content = []
                    continue
                    
                if in_story and tag.name in ['h3', 'h4']:
                    txt = tag.get_text().strip()
                    if txt: current_content.append(f"<br><h3>{txt}</h3>")
                    continue
                    
            elif tag.name in ['p', 'ul', 'ol'] and in_story:
                txt = tag.get_text().strip()
                if txt: current_content.append(f"<p>{txt}</p>")
                    
        if in_story and len("".join(current_content)) > len("".join(best_content)):
            best_content = current_content
            
        if best_content: return "".join(best_content), page_url
    except Exception: pass
    return None, None

# --- TIER 2: WIKIPEDIA SCRAPER (NEW) ---
def get_wikipedia_lore(show_name, season_num, ep_title):
    """Scrapes the strictly formatted Wikipedia episode tables."""
    api_url = "https://en.wikipedia.org/w/api.php"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TVVaultReader/1.0'}
    
    # Wikipedia typically stores episodes on season pages or main show pages
    queries = [
        f"{show_name} (season {season_num})",
        f"List of {show_name} episodes",
        f"{show_name} (TV series)",
        show_name
    ]
    
    for q in queries:
        params = {"action": "parse", "page": q, "prop": "text", "format": "json", "redirects": "1"}
        try:
            res = requests.get(api_url, params=params, headers=headers, timeout=10).json()
            if "parse" in res and "text" in res["parse"]:
                html = res["parse"]["text"]["*"]
                soup = BeautifulSoup(html, 'html.parser')
                
                # Wikipedia tables use <td class="summary"> or just quotes for episode titles
                for cell in soup.find_all(['td', 'th']):
                    cell_text = cell.get_text().replace('"', '').replace('”', '').replace('“', '').strip().lower()
                    
                    if ep_title.lower() == cell_text or ep_title.lower() in cell_text:
                        # Found the title cell! The plot is always in the NEXT table row.
                        parent_tr = cell.find_parent('tr')
                        if parent_tr:
                            next_tr = parent_tr.find_next_sibling('tr')
                            if next_tr:
                                desc_td = next_tr.find('td', class_='description')
                                if desc_td:
                                    content = []
                                    for p in desc_td.find_all('p'):
                                        txt = p.get_text().strip()
                                        if txt: content.append(f"<p>{txt}</p>")
                                    
                                    # Sometimes Wikipedia doesn't use <p> tags inside the cell
                                    if not content:
                                        txt = desc_td.get_text().strip()
                                        if txt: content.append(f"<p>{txt}</p>")
                                            
                                    if content:
                                        page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(res['parse']['title'].replace(' ', '_'))}"
                                        return "".join(content), page_url
        except Exception:
            continue
            
    return None, None

# --- WATERFALL ENGINE ROUTER ---
def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary, tvmaze_url):
    """Executes the 3-Tier Waterfall"""
    
    # 1. Try Fandom
    raw_text, url = get_raw_lore(wiki_slug, ep_title)
    text_len = len(BeautifulSoup(raw_text, "html.parser").get_text()) if raw_text else 0
    
    # If Fandom works and is larger than a tiny stub (300 chars), use it.
    if raw_text and text_len > 300:
        return raw_text, url, "Fandom"
        
    # 2. Try Wikipedia
    wiki_text, wiki_url = get_wikipedia_lore(show_name, season_num, ep_title)
    wiki_len = len(BeautifulSoup(wiki_text, "html.parser").get_text()) if wiki_text else 0
    
    # If Wikipedia has a decent plot, use it.
    if wiki_text and wiki_len > 150:
        return wiki_text, wiki_url, "Wikipedia"
        
    # 3. TVMaze Fallback
    if tvmaze_summary:
        return tvmaze_summary, tvmaze_url, "TVMaze"
        
    return None, None, None

# --- EPUB COMPILER WITH WATERFALL ---
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
        
        final_text, _, _ = fetch_best_lore(
            show_name, season_num, ep['name'], wiki_slug, 
            ep.get('summary', ''), ep.get('url', '')
        )
            
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
    st.session_state.source = None
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

            # --- READER EXTRACTION WITH WATERFALL ---
            if st.button("🔓 Read Single Episode", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}"
                api_res = requests.get(api_url)
                
                if api_res.status_code == 200:
                    api_data = api_res.json()
                    if "name" in api_data:
                        
                        # Trigger the Triple-Tier Engine
                        final_text, final_url, source_used = fetch_best_lore(
                            show_data['name'], st.session_state.s_val, api_data['name'], 
                            wiki_slug, api_data.get('summary', ''), api_data.get('url', 'https://www.tvmaze.com')
                        )
                        
                        if final_text:
                            st.session_state.lore_text = final_text
                            st.session_state.wiki_url = final_url
                            st.session_state.source = source_used
                            st.session_state.ep_name = api_data['name']
                            st.session_state.image_url = api_data.get('image', {}).get('original')
                            st.session_state.b64_audio = None
                            
                            # Give the user a heads up if we fell back from Fandom
                            if source_used == "Wikipedia":
                                st.toast("Fandom was empty. Successfully loaded Wikipedia Plot!", icon="🏛️")
                            elif source_used == "TVMaze":
                                st.toast("Both Fandom and Wikipedia failed. Loaded TVMaze backup.", icon="⚠️")
                        else:
                            st.session_state.lore_text = None
                            st.error(f"No plot summary found on Fandom, Wikipedia, or TVMaze.")

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
                
                # Visual indicator of which data source won the waterfall
                st.caption(f"Source: **{st.session_state.source}** | [Original Link]({st.session_state.wiki_url})")
                
                st.divider()
                st.button(f"⏭️ Load Season {st.session_state.s_val}, Episode {st.session_state.ep_val + 1}", on_click=load_next_episode, use_container_width=True)

except Exception as e:
    st.error(f"System Error: {e}")
