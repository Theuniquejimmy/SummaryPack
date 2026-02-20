import streamlit as st
import requests
import re
import os
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

# --- MOBILE STYLING ---
st.markdown("""
    <style>
    .plot-text {
        font-size: 1.15em;
        line-height: 1.7;
        background-color: #1a1a1a;
        padding: 25px;
        border-radius: 15px;
        color: #f0f0f0;
        border: 1px solid #333;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 10px;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- SCRAPER ---
def get_full_fandom_plot(show_name, ep_title):
    try:
        wiki_slug = show_name.replace(" ", "").lower()
        ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            res = requests.get(f"{url}_(episode)", headers=headers, timeout=5)

        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            start_node = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
            
            if start_node:
                content = []
                current = start_node.find_parent()
                for sibling in current.find_next_siblings():
                    if sibling.name in ['h2', 'h3']:
                        header_text = sibling.get_text().lower()
                        if any(stop in header_text for stop in ['cast', 'trivia', 'gallery', 'references']):
                            break
                    if sibling.name in ['p', 'ul', 'ol']:
                        text = sibling.get_text().strip()
                        if text: content.append(text)
                return "\n\n".join(content)
    except: return None
    return "Lore not found. Try checking the search spelling."

# --- TTS HELPER ---
def play_audio(text):
    tts = gTTS(text=text, lang='en')
    tts.save("temp_audio.mp3")
    with open("temp_audio.mp3", "rb") as f:
        data = f.read()
        b64 = base64.b64encode(data).decode()
        # Custom HTML to allow for playback speed controls in some browsers
        audio_html = f"""
            <audio controls style="width: 100%;">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            """
        st.markdown(audio_html, unsafe_allow_html=True)

# --- UI ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search Show:", placeholder="e.g. Invincible")

if query:
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    if resp:
        show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Confirm Show", options=list(show_options.keys()))
        show = show_options[label]
        
        c1, c2 = st.columns(2)
        with c1: s_val = st.number_input("Season", min_value=1, value=1)
        with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("🔓 Open the Vault"):
            ep_url = f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}"
            data = requests.get(ep_url).json()
            
            if "name" in data:
                plot = get_full_fandom_plot(show['name'], data['name'])
                
                st.subheader(f"{data['name']}")
                if data.get('image'): 
                    st.image(data['image']['medium'], use_container_width=True)
                
                # TTS Section
                st.write("---")
                if st.button("🔊 Narrate This Plot"):
                    play_audio(plot)
                st.caption("Tip: Use the three dots on the player to change playback speed.")
                
                # Text Section
                st.markdown(f'<div class="plot-text">{plot}</div>', unsafe_allow_html=True)
            else:
                st.error("Episode not found.")
