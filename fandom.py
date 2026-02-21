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
    "Gilmore Girls": "gilmoregirls"
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
        best_content = [] # Store the longest section here
        
        for header in soup.find_all(['h2', 'h3']):
            h_text, h_id = header.get_text().lower(), header.get('id', '').lower()
            inner_span = header.find('span')
            span_id = inner_span.get('id', '').lower() if inner_span else ""
            
            if any(key in h_text or key in h_id or key in span_id for key in story_keywords):
                content = []
                for sibling in header.find_next_siblings():
                    # Stop if we hit a completely new major section on the page
                    if sibling.name == 'h2': 
                        break
                        
                    if sibling.name in ['h3', 'h4']:
                        h_text_sib = sibling.get_text().strip()
                        stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos']
                        if any(stop in h_text_sib.lower() for stop in stop_words): break 
                        if h_text_sib: content.append(f"<br><h3>{h_text_sib}</h3>")
                        
                    elif sibling.name in ['p', 'ul', 'ol']:
                        txt = sibling.get_text().strip()
                        if txt: content.append(f"<p>{txt}</p>")
                
                # Compare section lengths: If "Plot" is longer than "Synopsis", overwrite it
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
        
        # 1. Gather Both Sources
        raw_text, _ = get_raw_lore(wiki_slug, ep['name'])
        tvmaze_summary = ep.get('summary', '')
        
        # 2. Get Clean Character Counts for accurate weighing
        fandom_len = len(BeautifulSoup(raw_text, "html.parser").get_text()) if raw_text else 0
        tvmaze_len = len(BeautifulSoup(tvmaze_summary, "html.parser").get_text()) if tvmaze_summary else 0
        
        # 3. Quality Control Weigh-In
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

            # --- EPUB EXPORT ---
            if st.button(f"📚 Export Season {st.session_state.s_val} as EPUB", use_container_width=True):
                compiled_file = build_season_epub(show_data['id'], show_data['name'], st.session_state.s_val, wiki_slug)
                if compiled_file:
                    st.session_state.epub_ready = compiled_file
                    st.success("Season Compiled Successfully!")
