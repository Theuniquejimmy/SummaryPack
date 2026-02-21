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

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

WIKI_ALIASES = {
    "Buffy the Vampire Slayer": "buffy",
    "The Incredible Hulk": "hulk",
    "The Wheel of Time": "wot",
    "The Bear": "the-bear"
}

st.set_page_config(page_title="TV Vault Pro", page_icon="📺")

# --- MOBILE STYLING ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #007BFF;
        color: white;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

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

# --- WATERFALL LORE ENGINE ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    search_params = {"action": "query", "list": "search", "srsearch": ep_title, "format": "json"}
    headers = {'User-Agent': 'TVVaultPro/1.0'}
    try:
        search_res = requests.get(api_url, params=search_params, headers=headers).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results: return None, None
        exact_title = search_results[0]["title"]
        for res in search_results:
            if "(tv episode)" in res["title"].lower():
                exact_title = res["title"]
                break
        parse_params = {"action": "parse", "page": exact_title, "prop": "text", "format": "json", "redirects": "1"}
        parse_res = requests.get(api_url, params=parse_params, headers=headers).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        if not html_text: return None, None
        soup = BeautifulSoup(html_text, 'html.parser')
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
        return "".join(content), f"https://{wiki_slug}.fandom.com/wiki/{exact_title.replace(' ', '_')}"
    except: return None, None

def fetch_best_lore(show_name, season_num, ep_title, wiki_slug, tvmaze_summary):
    f_text, f_url = get_raw_lore(wiki_slug, ep_title)
    if f_text and len(f_text) > 400: return f_text, f_url, "Fandom"
    return tvmaze_summary, "https://www.tvmaze.com", "TVMaze"

# --- EPUB COMPILER ---
def create_epub_in_memory(show_title, recap_text, is_season, s_val, ep_val, ep_list=None, wiki_slug=None):
    book = epub.EpubBook()
    title_str = f"{show_title} - Season {s_val}" if is_season else f"{show_title} - S{s_val}E{ep_val}"
    book.set_identifier("tvvaultpro_recap")
    book.set_title(title_str)
    book.set_language('en')
    
    chapters = []
    # Intro Chapter
    html_content = markdown.markdown(recap_text)
    intro = epub.EpubHtml(title="Recap Overview", file_name='intro.xhtml', lang='en')
    intro.content = f"<h1>{title_str}</h1>{html_content}"
    book.add_item(intro); chapters.append(intro)
    
    # Episode Chapters (Scraping Lore)
    if is_season and ep_list:
        for ep in ep_list:
            ep_n, ep_t = ep.get('number', 0), ep.get('name', 'Unknown')
            lore, _, _ = fetch_best_lore(show_title, s_val, ep_t, wiki_slug, ep.get('summary', ''))
            c = epub.EpubHtml(title=f"Ep {ep_n}", file_name=f'ep_{ep_n}.xhtml', lang='en')
            c.content = f"<h2>Episode {ep_n}: {ep_t}</h2>{lore}"
            book.add_item(c); chapters.append(c)
            
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    mem = io.BytesIO()
    epub.write_epub(mem, book)
    return mem.getvalue()

# --- MAIN APP ---
st.title("📺 TV Vault Pro")
app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search for a show", placeholder="e.g. Buffy the Vampire Slayer")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {}
            for i in resp:
                s_data = i.get('show', {})
                if not s_data: continue
                p_date = s_data.get('premiered')
                year = p_date[:4] if p_date else "????"
                show_options[f"{s_data.get('name', 'Unknown')} ({year})"] = s_data.get('id')
            
            selected_show = st.selectbox("Select Show", options=list(show_options.keys()))
            show_id = show_options[selected_show]
            clean_name = selected_show.split(" (")[0]
            wiki_slug = WIKI_ALIASES.get(clean_name, clean_name.replace(" ", "").lower())

            if app_mode == "Single Episode":
                c1, c2 = st.columns(2)
                s_val = c1.number_input("Season", min_value=1, value=1, key="s_input")
                ep_val = c2.number_input("Episode", min_value=1, value=1, key="e_input")
            else:
                s_val = st.number_input("Summarize Season", min_value=1, value=1, key="s_season_input")
                ep_val = 1

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("Analyzing the Vault..."):
                    ep_list_data = []
                    if app_mode == "Single Episode":
                        url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        if "name" in data:
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            raw_summary = data.get('summary') or "No summary available."
                            clean_summary = re.sub('<[^<]+>', '', raw_summary)
                            guest_list = data.get('_embedded', {}).get('guestcast', [])
                            guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "No major guests."
                            prompt = f"Recap Season {s_val}, Episode {ep_val} of {selected_show}. Title: {data['name']}. Guests: {guests}. Summary: {clean_summary}. (NO MARKDOWN)"
                        else:
                            st.error("Episode not found."); st.stop()
                    else:
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_id}/seasons").json()
                        target = next((s for s in seasons if s.get('number') == s_val), None)
                        if target:
                            if target.get('image'): st.image(target['image']['medium'], use_container_width=True)
                            ep_list_data = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            full_text = " ".join([re.sub('<[^<]+>', '', e.get('summary') or "") for e in ep_list_data])
                            prompt = f"Detailed season recap for {selected_show} Season {s_val}. Context: {full_text[:3500]}. (NO MARKDOWN)"
                        else:
                            st.error("Season not found."); st.stop()

                    # AI Call
                    try:
                        client = genai.Client(api_key=GEMINI_KEY)
                        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        final_text = res.text
                    except:
                        chat = Groq(api_key=GROQ_KEY).chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile")
                        final_text = chat.choices[0].message.content

                    # --- PRO READER UI ---
                    st.session_state.lore_text = final_text
                    st.write(final_text)
                    
                    st.divider()
                    col_audio, col_epub = st.columns(2)
                    
                    with col_audio:
                        voice = st.selectbox("Narrator:", ["Christopher (Deep, Cinematic)", "Aria (Clear, Professional)", "Guy (Casual, Conversational)"])
                        if st.button("🔊 Play Audio"):
                            clean_tts = BeautifulSoup(final_text, "html.parser").get_text()
                            create_audio(clean_tts, voice)
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                components.html(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}"></audio>', height=100)
                    
                    with col_epub:
                        epub_data = create_epub_in_memory(clean_name, final_text, (app_mode=="Full Season"), s_val, ep_val, ep_list_data, wiki_slug)
                        st.download_button("📥 Download EPUB", data=epub_data, file_name=f"{clean_name}_S{s_val}.epub", mime="application/epub+zip")

        else: st.warning("No shows found.")
    except Exception as e: st.error(f"App Error: {e}")
else: st.info("Enter a show title to begin.")
