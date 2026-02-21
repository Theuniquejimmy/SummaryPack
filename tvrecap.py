import streamlit as st
import streamlit.components.v1 as components
import requests
import urllib.parse
from bs4 import BeautifulSoup
import base64
import edge_tts
import asyncio
from ebooklib import epub
import io
import os
import re
import markdown

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Buffy the Vampire Slayer": "buffy",
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wheeloftime",
    "Gilmore Girls": "gilmoregirls",
    "ER": "er",
    "The Bear": "the-bear"
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

# --- TIER 1: ADVANCED FANDOM SCRAPER ---
def get_raw_lore(wiki_slug, ep_title):
    base_url = f"https://{wiki_slug.lower()}.fandom.com"
    api_url = f"{base_url}/api.php"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # 1. SEARCH STRATEGY
        search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json", "srlimit": 10}
        search_res = requests.get(api_url, params=search_params, headers=headers, timeout=10).json()
        results = search_res.get("query", {}).get("search", [])
        
        exact_title = None
        e_lower = ep_title.lower()
        
        # Priority list for matching titles
        for res in results:
            t_lower = res["title"].lower()
            if "transcript" in t_lower: continue # Skip transcripts
            
            # Check for exact match or standard tags
            if t_lower == e_lower:
                exact_title = res["title"]
                break
            if any(tag in t_lower for tag in ["(episode)", "(tv episode)"]) and e_lower in t_lower:
                exact_title = res["title"]
                break
        
        # 2. FALLBACK: Direct URL Guess (Crucial for Buffy)
        if not exact_title:
            guess_title = ep_title.replace(" ", "_")
            check_url = f"{base_url}/wiki/{urllib.parse.quote(guess_title)}"
            if requests.head(check_url, headers=headers).status_code == 200:
                exact_title = ep_title
            else:
                if results: exact_title = results[0]["title"] # Last resort: first result
                else: return None, None

        page_url = f"{base_url}/wiki/{urllib.parse.quote(exact_title.replace(' ', '_'))}"
        
        # 3. PARSE CONTENT
        parse_params = {"action": "parse", "page": exact_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, headers=headers, timeout=10).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        
        if not html_text: return None, None
            
        soup = BeautifulSoup(html_text, 'html.parser')
        
        # Remove spoilers for other episodes/junk
        for junk in soup.find_all(['table', 'aside', 'div', 'span'], class_=['portable-infobox', 'navbox', 'mw-editsection']):
            junk.decompose()
        
        content = []
        in_story = False
        story_keys = ['plot', 'synopsis', 'summary']
        stop_sections = ['trivia', 'gallery', 'references', 'credits', 'music', 'videos', 'cast', 'appearances', 'production']
        
        for tag in soup.find_all(['h2', 'h3', 'p']):
            text = tag.get_text().lower()
            if any(key in text for key in story_keys):
                in_story = True
                continue
            if in_story and tag.name == 'h2' and any(s in text for s in stop_sections):
                break
            if in_story and tag.name == 'p' and len(tag.get_text().strip()) > 20:
                content.append(str(tag))
        
        return "".join(content), page_url
    except: return None, None

# --- WATERFALL ROUTER ---
def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary, tvmaze_url):
    text, url = get_raw_lore(wiki_slug, ep_title)
    if text and len(BeautifulSoup(text, "html.parser").get_text()) > 300:
        return text, url, "Fandom"
    
    # Simple TVMaze backup if Fandom fails
    return tvmaze_summary, tvmaze_url, "TVMaze"

# --- EPUB COMPILER ---
def build_season_epub(show_id, show_name, season_num, wiki_slug):
    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodes").json()
    season_episodes = [ep for ep in ep_data if ep.get('season') == season_num]
    if not season_episodes: return None
        
    book = epub.EpubBook()
    book.set_title(f"{show_name} - S{season_num} Lore")
    book.set_language('en')
    
    chapters = []
    progress_bar = st.progress(0)
    
    for i, ep in enumerate(season_episodes):
        final_text, _, _ = fetch_best_lore(show_name, season_num, ep.get('name', ''), wiki_slug, ep.get('summary', ''), ep.get('url'))
        c = epub.EpubHtml(title=ep.get('name', 'Episode'), file_name=f"ep_{i}.xhtml")
        c.content = f"<h2>{ep.get('name', 'Episode')}</h2>{final_text}"
        book.add_item(c); chapters.append(c)
        progress_bar.progress((i + 1) / len(season_episodes))
        
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    
    mem_file = io.BytesIO()
    epub.write_epub(mem_file, book)
    progress_bar.empty()
    return mem_file.getvalue()

# --- STATE ---
for key in ['s_val', 'ep_val', 'lore_text', 'b64_audio', 'epub_ready', 'auto_fetch', 'source', 'wiki_url', 'ep_name', 'image_url']:
    if key not in st.session_state:
        st.session_state[key] = 1 if 'val' in key else (False if key == 'auto_fetch' else None)

def load_next():
    st.session_state.ep_val += 1
    st.session_state.auto_fetch = True
    st.session_state.lore_text = None

# --- UI ---
st.title("📖 TV Vault Reader")
query = st.text_input("Search for a show:", placeholder="e.g. Buffy")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {}
            for item in resp:
                s = item.get('show', {})
                if not s: continue
                p_date = s.get('premiered')
                year = str(p_date)[:4] if p_date else "????"
                show_options[f"{s.get('name', 'Unknown')} ({year})"] = s
            
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            
            # Alias Lookup
            base_name = re.sub(r'\s*\(\d{4}\)', '', show_data['name'])
            wiki_slug = WIKI_ALIASES.get(base_name, base_name.replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: st.number_input("Season", min_value=1, key="s_val")
            with c2: st.number_input("Episode", min_value=1, key="ep_val")

            if st.button("📚 Compile Season EPUB", use_container_width=True):
                data = build_season_epub(show_data['id'], show_data['name'], st.session_state.s_val, wiki_slug)
                if data:
                    st.session_state.epub_ready = data
                    st.success("Season Compiled!")
            
            if st.session_state.epub_ready:
                st.download_button("⬇️ Download EPUB", data=st.session_state.epub_ready, file_name=f"{base_name}_Lore.epub", mime="application/epub+zip", use_container_width=True)

            st.divider()

            if st.button("🔓 Read Single Episode", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                api_res = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}").json()
                
                if "name" in api_res:
                    final_text, final_url, source = fetch_best_lore(show_data['name'], st.session_state.s_val, api_res['name'], wiki_slug, api_res.get('summary', ''), api_res.get('url'))
                    st.session_state.lore_text = final_text
                    st.session_state.wiki_url = final_url
                    st.session_state.source = source
                    st.session_state.ep_name = api_res['name']
                    st.session_state.image_url = api_res.get('image', {}).get('original')
                    st.session_state.b64_audio = None

            if st.session_state.lore_text:
                with st.expander("⚙️ Reader Settings"):
                    theme = st.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    voice = st.selectbox("Narrator", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
                
                t = {"Dark": {"bg": "#121212", "text": "#e0e0e0", "acc": "#3b82f6", "pl": "#1e1e1e"}, "Sepia": {"bg": "#f4ecd8", "text": "#433422", "acc": "#8b5a2b", "pl": "#e8dfc8"}, "Light": {"bg": "#ffffff", "text": "#333333", "acc": "#2563eb", "pl": "#f3f4f6"}}[theme]
                st.markdown(f"""<style>.pro-reader {{ background-color: {t['bg']}; color: {t['text']}; padding: 30px; border-radius: 12px; font-family: 'Georgia', serif; line-height: 1.8; }} .pro-reader h2 {{ color: {t['acc']}; }}</style>""", unsafe_allow_html=True)
                
                st.subheader(f"S{st.session_state.s_val}E{st.session_state.ep_val}: {st.session_state.ep_name}")
                if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
                
                if st.button("🔊 Narrate Lore"):
                    txt = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                    create_audio(txt, voice)
                    with open("lore.mp3", "rb") as f:
                        st.session_state.b64_audio = base64.b64encode(f.read()).decode()

                if st.session_state.b64_audio:
                    components.html(f"""<div style="background:{t['pl']};padding:10px;border-radius:10px;"><audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{st.session_state.b64_audio}"></audio></div>""", height=80)

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: {st.session_state.source} | [View Original]({st.session_state.wiki_url})")
                st.button(f"⏭️ Next Episode", on_click=load_next, use_container_width=True)
    except Exception as e: st.error(f"Error: {e}")
else: st.info("Search for a show to begin.")
