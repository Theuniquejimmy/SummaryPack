import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

# --- MOBILE STYLING ---
st.markdown("""
    <style>
    .lore-box {
        font-size: 1.15rem;
        line-height: 1.8;
        background-color: #1a1a1a;
        padding: 25px;
        border-radius: 15px;
        color: #f1f1f1;
        border-left: 5px solid #3b82f6;
        margin-top: 20px;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
        background-color: #3b82f6;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- THE DEEP HUNTER SCRAPER ---
def get_fandom_lore(show_name, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # We clean the show name for the URL slug
    wiki_slug = show_name.replace(" ", "").lower()
    
    # Variations of the episode title for the URL (Fandom is picky)
    variations = [
        ep_title.replace(" ", "_"),
        ep_title.replace(" ", "_") + "_(episode)",
        ep_title.title().replace(" ", "_"),
        ep_title.title().replace(" ", "_") + "_(episode)"
    ]
    
    for v in variations:
        url = f"https://{wiki_slug}.fandom.com/wiki/{v}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                # Find the plot starting point
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    current = start.find_parent()
                    # Greedy loop: Grab everything until "Cast" or "Trivia"
                    for sibling in current.find_next_siblings():
                        if sibling.name in ['h2', 'h3']:
                            h_text = sibling.get_text().lower()
                            if any(stop in h_text for stop in ['cast', 'trivia', 'gallery', 'references', 'production']):
                                break
                        if sibling.name in ['p', 'ul', 'ol']:
                            txt = sibling.get_text().strip()
                            if txt: content.append(txt)
                    
                    if content:
                        return "\n\n".join(content), url
        except: continue
        
    return None, None

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")
st.caption("Search via TVmaze | Read via Fandom | Narrate via gTTS")

query = st.text_input("Search for a show", placeholder="e.g. Invincible")

if query:
    # 1. TVmaze Search
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    
    if resp:
        show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Select Show", options=list(show_options.keys()))
        show_data = show_options[label]
        
        # 2. Season/Episode Selection
        col1, col2 = st.columns(2)
        with col1: s_val = st.number_input("Season", min_value=1, value=1)
        with col2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("🔓 Extract Full Lore"):
            # 3. Get Episode Info from TVmaze
            ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
            api_data = requests.get(ep_url).json()
            
            if "name" in api_data:
                # 4. Use the Episode Name to Hunt Fandom
                lore_text, found_url = get_fandom_lore(show_data['name'], api_data['name'])
                
                if lore_text:
                    st.header(f"{api_data['name']}")
                    if api_data.get('image'): 
                        st.image(api_data['image']['medium'], use_container_width=True)
                    
                    # --- TTS ---
                    if st.button("🔊 Narrate This Plot"):
                        with st.spinner("Preparing audio..."):
                            tts = gTTS(text=lore_text, lang='en')
                            tts.save("lore.mp3")
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                    # --- LORE DISPLAY ---
                    st.markdown(f'<div class="lore-box">{lore_text}</div>', unsafe_allow_html=True)
                    st.caption(f"Source: [Fandom Wiki]({found_url})")
                else:
                    st.error("Lore not found on Fandom. Try checking the search spelling or verify the wiki name.")
            else:
                st.error("Episode not found in the TVmaze database.")
