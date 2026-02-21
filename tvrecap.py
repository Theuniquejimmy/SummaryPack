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
from bs4 import BeautifulSoup
from ebooklib import epub
from google import genai
from groq import Groq

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺", layout="wide")

# Initialize Session States
if 'lore_text' not in st.session_state: st.session_state.lore_text = None
if 'b64_audio' not in st.session_state: st.session_state.b64_audio = None
if 'ep_list' not in st.session_state: st.session_state.ep_list = []
if 'image_url' not in st.session_state: st.session_state.image_url = None
if 'ep_name' not in st.session_state: st.session_state.ep_name = ""
if 's_val' not in st.session_state: st.session_state.s_val = 1
if 'ep_val' not in st.session_state: st.session_state.ep_val = 1

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

# --- EPUB HELPER ---
def create_epub_in_memory(show_title, recap_text, is_season, s_val, ep_val, ep_list=None):
    book = epub.EpubBook()
    title_str = f"{show_title} - Season {s_val}" if is_season else f"{show_title} - S{s_val}E{ep_val}"
    book.set_identifier("tvvaultpro_recap")
    book.set_title(title_str)
    book.set_language('en')
    
    chapters = []
    html_content = markdown.markdown(recap_text)
    intro_chapter = epub.EpubHtml(title="Recap Overview", file_name='intro.xhtml', lang='en')
    intro_chapter.content = f"<h1>{title_str}</h1>{html_content}"
    book.add_item(intro_chapter)
    chapters.append(intro_chapter)
    
    if is_season and ep_list:
        for ep in ep_list:
            ep_num = ep.get('number', 0)
            ep_name = ep.get('name', 'Unknown')
            raw_summary = ep.get('summary') or "<p>No summary available.</p>"
            chapter = epub.EpubHtml(title=f"Ep {ep_num}", file_name=f'ep_{ep_num}.xhtml', lang='en')
            chapter.content = f"<h2>Episode {ep_num}: {ep_name}</h2>{raw_summary}"
            book.add_item(chapter)
            chapters.append(chapter)
            
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    mem_file = io.BytesIO()
    epub.write_epub(mem_file, book)
    return mem_file.getvalue()

# --- APP UI ---
st.title("📺 TV Vault Pro")

with st.sidebar:
    st.header("Search & Settings")
    app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"])
    query = st.text_input("Search Show", placeholder="e.g. Buffy the Vampire Slayer")

if query:
    url = f"https://api.tvmaze.com/search/shows?q={query}"
    resp = requests.get(url).json()
    
    if resp:
        show_options = {}
        for item in resp:
            s = item.get('show', {})
            p_date = s.get('premiered')
            # Safety slice for year
            year = str(p_date)[:4] if p_date else "????"
            label = f"{s.get('name')} ({year})"
            show_options[label] = s.get('id')
            
        selected_show = st.selectbox("Select Show", options=list(show_options.keys()))
        show_id = show_options[selected_show]
        clean_title = selected_show.split(" (")[0]
        
        c1, c2 = st.columns(2)
        s_val_input = c1.number_input("Season", min_value=1, value=1)
        ep_val_input = c2.number_input("Episode", min_value=1, value=1) if app_mode == "Single Episode" else 1

        if st.button(f"🚀 Generate {app_mode} Recap", use_container_width=True):
            with st.spinner("Accessing the Vault..."):
                st.session_state.b64_audio = None
                
                if app_mode == "Single Episode":
                    ep_data = requests.get(f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val_input}&number={ep_val_input}").json()
                    if "id" not in ep_data: 
                        st.error("Episode not found.")
                        st.stop()
                    st.session_state.ep_name = ep_data.get('name')
                    st.session_state.image_url = ep_data.get('image', {}).get('medium')
                    st.session_state.ep_list = []
                    
                    # Safety check for Single Episode summary
                    raw_sum = ep_data.get('summary') if ep_data.get('summary') else ""
                    summary_context = re.sub('<[^<]+>', '', raw_sum)
                    prompt = f"Provide a detailed, witty recap of {clean_title} S{s_val_input}E{ep_val_input}. Context: {summary_context}"
                else:
                    seasons = requests.get(f"https://api.tvmaze.com/shows/{show_id}/seasons").json()
                    target_s = next((s for s in seasons if s.get('number') == s_val_input), seasons[0])
                    st.session_state.ep_list = requests.get(f"https://api.tvmaze.com/seasons/{target_s['id']}/episodes").json()
                    st.session_state.ep_name = f"Season {s_val_input} Complete"
                    st.session_state.image_url = target_s.get('image', {}).get('medium')
                    
                    # Safety check for Season List comprehension
                    summary_context = " ".join([re.sub('<[^<]+>', '', e.get('summary')) for e in st.session_state.ep_list if e.get('summary')])[:4000]
                    prompt = f"Provide a deep-dive season recap for {clean_title} Season {s_val_input}. Context: {summary_context}"

                try:
                    client = genai.Client(api_key=GEMINI_KEY)
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    st.session_state.lore_text = res.text
                except Exception:
                    groq_client = Groq(api_key=GROQ_KEY)
                    res = groq_client.chat.completions.create(messages=[{"role":"user","content":prompt}], model="llama-3.3-70b-versatile")
                    st.session_state.lore_text = res.choices[0].message.content
                
                st.session_state.s_val, st.session_state.ep_val = s_val_input, ep_val_input

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

            st.markdown(f"""<style>
                .pro-reader {{ background-color: {current_theme['bg']}; color: {current_theme['text']}; font-family: 'Georgia', serif; font-size: 1.15rem; line-height: 1.8; padding: 30px; border-radius: 12px; border: 1px solid {current_theme['accent']}22; }}
                .pro-reader h1, .pro-reader h2, .pro-reader h3 {{ color: {current_theme['accent']}; }}
                </style>""", unsafe_allow_html=True)

            st.subheader(f"{clean_title} - {st.session_state.ep_name}")
            if st.session_state.image_url: st.image(st.session_state.image_url, use_container_width=True)
            
            st.markdown(f'<div class="pro-reader">{markdown.markdown(st.session_state.lore_text)}</div>', unsafe_allow_html=True)
            st.write("---")
            
            col_down, col_audio = st.columns(2)
            
            with col_down:
                epub_bin = create_epub_in_memory(clean_title, st.session_state.lore_text, (app_mode=="Full Season"), st.session_state.s_val, st.session_state.ep_val, st.session_state.ep_list)
                st.download_button("📥 Download eBook (.epub)", data=epub_bin, file_name=f"{clean_title}_Recap.epub", mime="application/epub+zip", use_container_width=True)

            with col_audio:
                if st.button("🔊 Generate Audio Narration", use_container_width=True):
                    with st.spinner("Synthesizing..."):
                        clean_tts_text = BeautifulSoup(st.session_state.lore_text, "html.parser").get_text(separator=' ')
                        create_audio(clean_tts_text, voice_setting)
                        with open("lore.mp3", "rb") as f:
                            st.session_state.b64_audio = base64.b64encode(f.read()).decode()

            if st.session_state.b64_audio:
                player_html = """
                <div style="background-color: PLAYER_BG; padding: 15px; border-radius: 10px; border-left: 4px solid ACCENT_COLOR; color: TEXT_COLOR;">
                    <audio id="narrator-audio" controls autoplay style="width: 100%;"><source src="data:audio/mp3;base64,AUDIO_DATA" type="audio/mp3"></audio>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 12px; font-family: sans-serif;">
                        <label>🏃 Speed: <span id="speed-display">1.0x</span></label>
                        <input type="range" id="speed-slider" min="0.5" max="2.0" step="0.1" value="1.0" style="width: 50%;">
                    </div>
                </div>
                <script>
                    const audio = document.getElementById("narrator-audio");
                    const slider = document.getElementById("speed-slider");
                    const display = document.getElementById("speed-display");
                    slider.oninput = function() { 
                        audio.playbackRate = this.value; 
                        display.textContent = this.value + "x"; 
                    };
                </script>
                """
                player_html = player_html.replace("PLAYER_BG", current_theme['player']).replace("ACCENT_COLOR", current_theme['accent']).replace("TEXT_COLOR", current_theme['text']).replace("AUDIO_DATA", st.session_state.b64_audio)
                components.html(player_html, height=130)

    else:
        st.warning("No shows found.")
else:
    st.info("Search for a show to begin your journey.")
