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
        font-size: 1.2em;
        line-height: 1.7;
        background-color: #1e1e1e;
        padding: 20px;
        border-radius: 10px;
        color: #e0e0e0;
    }
    div.stButton > button {
        width: 100%;
        height: 3em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- SCRAPER: THE FULL LORE COLLECTOR ---
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
                        # Stop ONLY at non-story sections
                        if any(stop in header_text for stop in ['cast', 'trivia', 'gallery', 'references', 'videos']):
                            break
                    if sibling.name in ['p', 'ul', 'ol']:
                        text = sibling.get_text().strip()
                        if text: content.append(text)
                return "\n\n".join(content)
    except: return None
    return "Lore not found for this specific episode URL."

# --- TTS HELPER ---
def text_to_speech(text):
    tts = gTTS(text=text, lang='en')
    tts.save("speech.mp3")
    with open("speech.mp3", "rb") as f:
        data = f.read()
        b64 = base64.b64encode(data).decode()
        md = f"""
            <audio controls autoplay="true">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            """
        st.markdown(md, unsafe_allow_html=True)

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")
query = st.text_input("Search for a show", placeholder="e.g. Invincible")

if query:
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    if resp:
        show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Select Show", options=list(show_options.keys()))
        show = show_options[label]
        
        c1, c2 = st.columns(2)
        with c1: s_val = st.number_input("Season", min_value=1, value=1)
        with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("Fetch Full Lore"):
            ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}").json()
            if "name" in ep_data:
                full_plot = get_full_fandom_plot(show['name'], ep_data['name'])
                
                st.header(f"S{s_val}E{ep_val}: {ep_data['name']}")
                if ep_data.get('image'): st.image(ep_data['image']['medium'])
                
                # --- TTS BUTTON ---
                if st.button("🔊 Read Lore Out Loud"):
                    text_to_speech(full_plot)
                
                # --- DISPLAY TEXT ---
                st.markdown(f'<div class="plot-text">{full_plot}</div>', unsafe_allow_html=True)
            else:
                st.error("Episode not found in TVmaze.")
