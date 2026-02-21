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

# --- TIER 1: ADVANCED FANDOM SCRAPER (BUFFY-PROOF) ---
def get_raw_lore(wiki_slug, ep_title):
    base_url = f"https://{wiki_slug.lower()}.fandom.com"
    api_url = f"{base_url}/api.php"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # STEP 1: Direct Hit Strategy 
        parse_params = {"action": "parse", "page": ep_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, headers=headers, timeout=10).json()
        
        # Fallback to search if direct hit fails
        if "error" in parse_res:
            search_params = {"action": "query", "list": "search", "srsearch": f"{ep_title} -transcript", "format": "json"}
            search_res = requests.get(api_url, params=search_params, headers=headers).json()
            results = search_res.get("query", {}).get("search", [])
            if not results: return None, None
            parse_params["page"] = results[0]["title"]
            parse_res = requests.get(api_url, params=parse_params, headers=headers).json()

        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        if not html_text: return None, None
            
        soup = BeautifulSoup(html_text, 'html.parser')
        for junk in soup.find_all(['table', 'aside', 'div', 'span', 'sup'], class_=['portable-infobox', 'navbox', 'mw-editsection', 'reference']):
            junk.decompose()
        
        content, in_story = [], False
        story_keys = ['plot', 'synopsis', 'summary']
        stop_sections = ['trivia', 'gallery', 'references', 'credits', 'music', 'videos', 'cast', 'appearances', 'production']
        
        for tag in soup.find_all(['h2', 'h3', 'p']):
            text = tag.get_text().lower().strip()
            if any(key in text for key in story_keys):
                in_story = True
                continue
            if in_story and tag.name == 'h2' and any(s in text for s in stop_sections):
                break
            if in_story and tag.name == 'p' and len(tag.get_text().strip()) > 20:
                content.append(str(tag))
        
        final_html = "".join(content)
        page_url = f"{base_url}/wiki/{urllib.parse.quote(ep_title.replace(' ', '_'))}"
        return (final_html, page_url) if len(final_html) > 100 else (None, None)
    except: return None, None

def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary, tvmaze_url):
    text, url = get_raw_lore(wiki_slug, ep_title)
    if text: return text, url, "Fandom Lore"
    return tvmaze_summary, tvmaze_url, "TVMaze Summary"

# --- EPUB COMPILER ---
def build_season_epub(show_id, show_name, season_num, wiki_slug):
    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodes").json()
    season_episodes = [ep for ep in ep_data if ep.get('season') == season_num]
    if not season_episodes: return None
    book = epub.EpubBook()
    book.set_title(f"{show_name} - S{season_num} Compendium")
    book.set_language('en')
    chapters = []
    for i, ep in enumerate(season_episodes):
        final_text, _, _ = fetch_best_lore(show_name, season_num, ep.get('name', ''), wiki_slug, ep.get('summary', ''), ep.get('url'))
        c = epub.EpubHtml(title=ep.get('name', 'Episode'), file_name=f"ep_{i}.xhtml")
        c.content = f"<h2>{ep.get('name', 'Episode')}</h2>{final_text if final_text else 'Lore not found.'}"
        book.add_item(c); chapters.append(c)
    book.toc = tuple(chapters); book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    mem_file = io.BytesIO()
    epub.write_epub(mem_file, book)
    return mem_file.getvalue()

# --- STATE MANAGEMENT ---
for key in ['s_val', 'ep_val', 'lore_text', 'b64_audio', 'epub_ready', 'auto_fetch', 'source', 'wiki_url', 'ep_name', 'image_url']:
    if key not in st.session_state: st.session_state[key] = 1 if 'val' in key else (False if key == 'auto_fetch' else None)

def load_next_ep():
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
                p_date = s.get('premiered')
                year = str(p_date)[:4] if p_date else "????"
                show_options[f"{s.get('name', 'Unknown')} ({year})"] = s
            
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            base_name = re.sub(r'\s*\(\d{4}\)', '', show_data['name'])
            wiki_slug = WIKI_ALIASES.get(base_name, base_name.replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: st.number_input("Season", min_value=1, key="s_val")
            with c2: st.number_input("Episode", min_value=1, key="ep_val")

            if st.button("📚 Compile Season EPUB", use_container_width=True):
                data = build_season_epub(show_data['id'], show_data['name'], st.session_state.s_val, wiki_slug)
                if data: st.session_state.epub_ready = data

            if st.session_state.epub_ready:
                st.download_button("⬇️ Download EPUB", data=st.session_state.epub_ready, file_name=f"{base_name}_Lore.epub", mime="application/epub+zip", use_container_width=True)

            st.divider()

            if st.button("🔓 Extract Episode Lore", use_container_width=True) or st.session_state.auto_fetch:
                st.session_state.auto_fetch = False
                api_res = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={st.session_state.s_val}&number={st.session_state.ep_val}").json()
                if "name" in api_res:
                    final_text, final_url, source = fetch_best_lore(show_data['name'], st.session_state.s_val, api_res['name'], wiki_slug, api_res.get('summary', ''), api_res.get('url'))
                    st.session_state.lore_text, st.session_state.wiki_url, st.session_state.source = final_text, final_url, source
                    st.session_state.ep_name, st.session_state.image_url, st.session_state.b64_audio = api_res['name'], api_res.get('image', {}).get('original'), None

            if st.session_state.lore_text:
                with st.expander("⚙️ Reader Settings"):
                    theme = st.selectbox("Theme", ["Dark", "Sepia", "Light"])
                    voice = st.selectbox("Narrator", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
                
                t = {"Dark": {"bg": "#121212", "text": "#e0e0e0", "acc": "#3b82f6", "pl": "#1e1e1e"}, "Sepia": {"bg": "#f4ecd8", "text": "#433422", "acc": "#8b5a2b", "pl": "#e8dfc8"}, "Light": {"bg": "#ffffff", "text": "#333333", "acc": "#2563eb", "pl": "#f3f4f6"}}[theme]
                st.markdown(f"""<style>.pro-reader {{ background-color: {t['bg']}; color: {t['text']}; padding: 35px; border-radius: 12px; font-family: 'Georgia', serif; line-height: 1.8; }} .pro-reader h2 {{ color: {t['acc']}; }}</style>""", unsafe_allow_html=True)
                st.subheader(f"S{st.session_state.s_val}E{st.session_state.ep_val}: {st.session_state.ep_name}")
                if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
                
                if st.button("🔊 Narrate Lore"):
                    txt = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                    create_audio(txt, voice)
                    with open("lore.mp3", "rb") as f: st.session_state.b64_audio = base64.b64encode(f.read()).decode()

                if st.session_state.b64_audio:
                    # THE SPEED SLIDER PLAYER
                    player_html = f"""
                    <div style="background:{t['pl']};padding:15px;border-radius:10px;border-left:4px solid {t['acc']};color:{t['text']};">
                        <audio id="v-audio" controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{st.session_state.b64_audio}"></audio>
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:12px;font-family:sans-serif;">
                            <label>🏃 Speed: <span id="s-val">1.0x</span></label>
                            <input type="range" id="s-slider" min="0.5" max="2.0" step="0.1" value="1.0" style="width:50%;">
                        </div>
                    </div>
                    <script>
                        const a=document.getElementById("v-audio"), s=document.getElementById("s-slider"), v=document.getElementById("s-val");
                        s.oninput=function() {{ a.playbackRate=this.value; v.textContent=this.value+"x"; }};
                    </script>
                    """
                    components.html(player_html, height=120)

                st.markdown(f'<div class="pro-reader">{st.session_state.lore_text}</div>', unsafe_allow_html=True)
                st.caption(f"Source: {st.session_state.source} | [View Original]({st.session_state.wiki_url})")
                st.button(f"⏭️ Next Episode", on_click=load_next_ep, use_container_width=True)
    except Exception as e: st.error(f"Vault Error: {e}")
else: st.info("Search for a show to begin.")
