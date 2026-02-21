import streamlit as st
import streamlit.components.v1 as components
import requests
import re
import os
import io
import markdown
import asyncio
import edge_tts
import base64
import urllib.parse
from bs4 import BeautifulSoup
from ebooklib import epub
from google import genai
from groq import Groq

# --- CONFIGURATION & ALIASES ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

# Helps the scraper find the right wikis for shows with weird names
WIKI_ALIASES = {
    "Buffy the Vampire Slayer": "buffy",
    "The Incredible Hulk": "hulk",
    "Horizon Zero Dawn": "horizon",
    "The Wheel of Time": "wot",
    "The Bear": "the-bear"
}

st.set_page_config(page_title="TV Vault Pro", page_icon="📖", layout="wide")

# Initialize Session States
state_keys = [
    'lore_text', 'b64_audio', 'ep_list', 'image_url', 
    'ep_name', 's_val', 'ep_val', 'wiki_url', 'source', 'epub_ready'
]
for key in state_keys:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'ep_list' else []

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

# --- TIER 1 & 2: SCRAPER ENGINE ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json"}
    headers = {'User-Agent': 'TVVaultPro/1.0'}
    try:
        search_res = requests.get(api_url, params=search_params, headers=headers, timeout=10).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results: return None, None
        
        exact_title = search_results[0]["title"]
        # Prioritize (TV Episode) tags to avoid comic/book confusion
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
        
        # Extract story content (Plot/Synopsis)
        content = []
        in_story = False
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

def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary):
    # 1. Try Fandom
    text, url = get_raw_lore(wiki_slug, ep_title)
    if text and len(text) > 400: return text, url, "Fandom"
    
    # 2. Try Wikipedia
    text, url = get_wikipedia_lore(show_name, season_num, ep_title)
    if text and len(text) > 200: return text, url, "Wikipedia"
    
    # 3. TVMaze Fallback
    return tvmaze_summary, "https://www.tvmaze.com", "TVMaze (AI Enhanced)"

# --- TIER 3: EPUB COMPILER ---
def build_season_epub(show_id, show_name, season_num, wiki_slug):
    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodes").json()
    season_episodes = [ep for ep in ep_data if ep['season'] == season_num]
    if not season_episodes: return None
        
    book = epub.EpubBook()
    book.set_title(f"{show_name} - S{season_num} Compendium")
    book.set_language('en')
    
    chapters = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, ep in enumerate(season_episodes):
        status_text.text(f"Scraping E{ep['number']}: {ep['name']}...")
        final_text, _, _ = fetch_best_lore(show_name, season_num, ep['name'], wiki_slug, ep.get('summary', ''))
        
        c = epub.EpubHtml(title=ep['name'], file_name=f"ep_{i}.xhtml")
        c.content = f"<h2>{ep['name']}</h2>{final_text}"
        book.add_item(c)
        chapters.append(c)
        progress_bar.progress((i + 1) / len(season_episodes))
        
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    
    mem_file = io.BytesIO()
    epub.write_epub(mem_file, book)
    status_text.empty(); progress_bar.empty()
    return mem_file.getvalue()

# --- APP UI ---
st.title("📺 TV Vault Pro")

with st.sidebar:
    st.header("Search & Settings")
    app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season Compendium"])
    query = st.text_input("Search Show", placeholder="e.g. Buffy")

if query:
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    if resp:
        show_options = {f"{s['show']['name']} ({s['show'].get('premiered','?')[:4]})": s['show'] for s in resp if 'show' in s}
        label = st.selectbox("Select Result", options=list(show_options.keys()))
        show_data = show_options[label]
        wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
        
        c1, c2 = st.columns(2)
        s_val = c1.number_input("Season", min_value=1, value=1)
        ep_val = c2.number_input("Episode", min_value=1, value=1) if "Single" in app_mode else 1

        if st.button(f"🚀 Launch Vault Extraction", use_container_width=True):
            if "Compendium" in app_mode:
                epub_data = build_season_epub(show_data['id'], show_data['name'], s_val, wiki_slug)
                st.session_state.epub_ready = epub_data
            else:
                with st.spinner("Executing Waterfall Scrape..."):
                    api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                    ep_json = requests.get(api_url).json()
                    
                    if "name" in ep_json:
                        final_text, final_url, source = fetch_best_lore(show_data['name'], s_val, ep_json['name'], wiki_slug, ep_json.get('summary', ''))
                        
                        # Use AI to polish the raw lore
                        client = genai.Client(api_key=GEMINI_KEY)
                        polish_prompt = f"Format this raw TV lore into a beautiful, witty recap. Source data: {final_text[:4000]}"
                        res = client.models.generate_content(model="gemini-2.0-flash", contents=polish_prompt)
                        
                        st.session_state.lore_text = res.text
                        st.session_state.ep_name = ep_json['name']
                        st.session_state.image_url = ep_json.get('image', {}).get('original')
                        st.session_state.wiki_url = final_url
                        st.session_state.source = source
                        st.session_state.b64_audio = None

        if st.session_state.epub_ready:
            st.download_button("⬇️ Download Full Season Compendium", data=st.session_state.epub_ready, file_name=f"{show_data['name']}_S{s_val}.epub", mime="application/epub+zip", use_container_width=True)

        # --- THE PRO READER UI ---
        if st.session_state.lore_text:
            st.divider()
            with st.expander("⚙️ Reader Settings"):
                rc1, rc2 = st.columns([1, 2])
                theme = rc1.selectbox("Theme", ["Dark", "Sepia", "Light"])
                voice = rc2.selectbox("Narrator", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
            
            themes = {"Dark": {"bg": "#121212", "text": "#e0e0e0", "acc": "#3b82f6"}, "Sepia": {"bg": "#f4ecd8", "text": "#433422", "acc": "#8b5a2b"}, "Light": {"bg": "#ffffff", "text": "#333333", "acc": "#2563eb"}}
            t = themes[theme]

            st.markdown(f"""<style>.pro-reader {{ background-color: {t['bg']}; color: {t['text']}; padding: 30px; border-radius: 12px; border: 1px solid {t['acc']}44; font-family: 'Georgia', serif; line-height: 1.8; }} .pro-reader h2 {{ color: {t['acc']}; }}</style>""", unsafe_allow_html=True)
            
            st.subheader(st.session_state.ep_name)
            if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
            
            st.markdown(f'<div class="pro-reader">{markdown.markdown(st.session_state.lore_text)}</div>', unsafe_allow_html=True)
            st.caption(f"Source: {st.session_state.source} | [View Original]({st.session_state.wiki_url})")

            if st.button("🔊 Play Audio Narration", use_container_width=True):
                clean_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text()
                create_audio(clean_text, voice)
                with open("lore.mp3", "rb") as f:
                    st.session_state.b64_audio = base64.b64encode(f.read()).decode()

            if st.session_state.b64_audio:
                player = f"""<div style="background:#222;padding:10px;border-radius:10px;"><audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{st.session_state.b64_audio}"></audio></div>"""
                components.html(player, height=80)
