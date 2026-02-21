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
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Buffy the Vampire Slayer": "buffy",
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

# --- SCRAPER ENGINE ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json"}
    headers = {'User-Agent': 'TVVaultPro/1.0'}
    try:
        search_res = requests.get(api_url, params=search_params, headers=headers, timeout=10).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results: return None, None
        
        exact_title = search_results[0]["title"]
        for res in search_results:
            if "(tv episode)" in res["title"].lower():
                exact_title = res["title"]
                break

        page_url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{urllib.parse.quote(exact_title.replace(' ', '_'))}"
        parse_params = {"action": "parse", "page": exact_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, headers=headers, timeout=10).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        
        if not html_text: return None, None
        soup = BeautifulSoup(html_text, 'html.parser')
        
        content = []
        in_story = False
        # Improved Extraction Logic
        for tag in soup.find_all(['h2', 'h3', 'p']):
            t_text = tag.get_text().lower()
            if any(k in t_text for k in ['plot', 'synopsis', 'summary']):
                in_story = True
                continue
            if in_story and tag.name == 'h2': break
            if in_story and tag.get_text().strip():
                content.append(str(tag))
        
        return "".join(content), page_url
    except: return None, None

def get_wikipedia_lore(show_name, season_num, ep_title):
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {"action": "parse", "page": f"List of {show_name} episodes", "prop": "text", "format": "json", "redirects": "1"}
    try:
        res = requests.get(api_url, params=params, timeout=10).json()
        soup = BeautifulSoup(res["parse"]["text"]["*"], 'html.parser')
        for cell in soup.find_all(['td', 'th']):
            if ep_title.lower() in cell.get_text().lower():
                parent_tr = cell.find_parent('tr')
                next_tr = parent_tr.find_next_sibling('tr') if parent_tr else None
                if next_tr:
                    desc = next_tr.find('td', class_='description')
                    if desc: return str(desc), f"https://en.wikipedia.org/wiki/{show_name.replace(' ', '_')}"
    except: pass
    return None, None

def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary, tvmaze_url):
    # 1. Try Fandom
    text, url = get_raw_lore(wiki_slug, ep_title)
    if text and len(text) > 400: return text, url, "Fandom"
    
    # 2. Try Wikipedia
    text, url = get_wikipedia_lore(show_name, season_num, ep_title)
    if text and len(text) > 200: return text, url, "Wikipedia"
    
    # 3. TVMaze Fallback
    return tvmaze_summary, tvmaze_url, "TVMaze"

# --- EPUB COMPILER ---
def build_season_epub(show_id, show_name, season_num, wiki_slug):
    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodes").json()
    season_episodes = [ep for ep in ep_data if ep.get('season') == season_num]
    if not season_episodes: return None
        
    book = epub.EpubBook()
    book.set_title(f"{show_name} - S{season_num} Compendium")
    book.set_language('en')
    
    chapters = []
    progress_bar = st.progress(0)
    
    for i, ep in enumerate(season_episodes):
        final_text, _, _ = fetch_best_lore(show_name, season_num, ep.get('name', ''), wiki_slug, ep.get('summary', ''), ep.get('url'))
        c = epub.EpubHtml(title=ep.get('name', 'Episode'), file_name=f"ep_{i}.xhtml")
        c.content = f"<h2>{ep.get('name', 'Episode')}</h2>{final_text}"
        book.add_item(c)
        chapters.append(c)
        progress_bar.progress((i + 1) / len(season_episodes))
        
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    
    import io
    mem_file = io.BytesIO()
    epub.write_epub(mem_file, book)
    progress_bar.empty()
    return mem_file.getvalue()

# --- STATE INITIALIZATION ---
if 's_val' not in st.session_state: st.session_state.s_val = 1
if 'ep_val' not in st.session_state: st.session_state.ep_val = 1
if 'auto_fetch' not in st.session_state: st.session_state.auto_fetch = False
if 'epub_ready' not in st.session_state: st.session_state.epub_ready = None
if 'lore_text' not in st.session_state: st.session_state.lore_text = None
if 'b64_audio' not in st.session_state: st.session_state.b64_audio = None

def load_next_episode():
    st.session_state.ep_val += 1
    st.session_state.auto_fetch = True
    st.session_state.lore_text = None
    st.session_state.b64_audio = None

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search for a show:", placeholder="e.g. Buffy")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            # THE BUFFY FIX: Bulletproof dictionary for show options
            show_options = {}
            for item in resp:
                s = item.get('show', {})
                if not s: continue
                p_date = s.get('premiered')
                # NUCLEAR FIX: Slice string directly if it exists, otherwise ????
                year = str(p_date)[:4] if p_date else "????"
                label = f"{s.get('name', 'Unknown')} ({year})"
                show_options[label] = s
            
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: st.number_input("Season", min_value=1, key="s_val")
            with c2: st.number_input("Episode", min_value=1, key="ep_val")

            # --- EPUB EXPORT ---
            if st.button(f"📚 Export Season {st.session_state.s_val} as EPUB", use_container_width=True):
                epub_data = build_season_epub(show_data['id'], show_data['name'], st.session_state.s_val, wiki_slug)
                if epub_data:
                    st.session_state.epub_ready = epub_data
                    st.success("Season Compiled!")
            
            if st.session_state.epub_ready:
                st.download_button(label="⬇️ Download Your EPUB", data=st.session_state.epub_ready, file_name=f"{show_data['name']}_Season{st.session_state.s_val}.epub", mime="application/epub+zip", use_container_width=True)

            st.divider()

            # --- READER EXTRACTION ---
            if st.button("🔓 Read Single Episode", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}"
                api_res = requests.get(api_url).json()
                
                if "name" in api_res:
                    final_text, final_url, source = fetch_best_lore(show_data['name'], st.session_state.s_val, api_res['name'], wiki_slug, api_res.get('summary', ''), api_res.get('url'))
                    st.session_state.lore_text = final_text
                    st.session_state.wiki_url = final_url
                    st.session_state.source = source
                    st.session_state.ep_name = api_res['name']
                    st.session_state.image_url = api_res.get('image', {}).get('original')
                    st.session_state.b64_audio = None

            # --- PRO READER UI ---
            if st.session_state.lore_text:
                with st.expander("⚙️ Reader Settings"):
                    rc1, rc2 = st.columns([1, 2])
                    theme = rc1.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    voice_setting = rc2.selectbox("Narrator Voice", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
                
                themes = {"Dark": {"bg": "#121212", "text": "#e0e0e0", "acc": "#3b82f6", "pl": "#1e1e1e"}, "Sepia": {"bg": "#f4ecd8", "text": "#433422", "acc": "#8b5a2b", "pl": "#e8dfc8"}, "Light": {"bg": "#ffffff", "text": "#333333", "acc": "#2563eb", "pl": "#f3f4f6"}}
                t = themes[theme]

                st.markdown(f"""<style>.pro-reader {{ background-color: {t['bg']}; color: {t['text']}; padding: 30px; border-radius: 12px; margin-top: 15px; border: 1px solid {t['acc']}44; font-family: 'Georgia', serif; line-height: 1.8; }} .pro-reader h3 {{ color: {t['acc']}; }}</style>""", unsafe_allow_html=True)

                st.subheader(f"S{st.session_state.s_val}E{st.session_state.ep_val}: {st.session_state.ep_name}")
                if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
                
                if st.button("🔊 Generate Audio Narration", use_container_width=True):
                    with st.spinner("Synthesizing..."):
                        clean_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                        create_audio(clean_text, voice_setting)
                        with open("lore.mp3", "rb") as f:
                            st.session_state.b64_audio = base64.b64encode(f.read()).decode()

                if st.session_state.b64_audio:
                    player_html = f"""<div style="background:{t['pl']};padding:15px;border-radius:10px;border-left:4px solid {t['acc']};"><audio id="aud" controls autoplay style="width:100%;"><source src="data:audio/mp3;base64,{st.session_state.b64_audio}"></audio><script>const a=document.getElementById("aud");</script></div>"""
                    components.html(player_html, height=100)

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: {st.session_state.source} | [View Original]({st.session_state.wiki_url})")
                st.divider()
                st.button(f"⏭️ Next: S{st.session_state.s_val}E{st.session_state.ep_val+1}", on_click=load_next_episode, use_container_width=True)

    except Exception as e:
        st.error(f"Vault Error: {e}")
