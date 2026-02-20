import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

# --- MANUAL WIKI OVERRIDES ---
# If a show has a weird wiki name, add it here: "TVmaze Name": "fandom_slug"
WIKI_MAPPING = {
    "The Incredible Hulk": "marvelcinematicuniverse",
    "Invincible": "invincible",
    "The Wheel of Time": "wot",
    "X-Men '97": "xmen97",
    "Star Wars: The Clone Wars": "starwars"
}

# --- STYLING ---
st.markdown("""
    <style>
    .lore-box {
        font-size: 1.1rem;
        line-height: 1.8;
        background-color: #1a1a1a;
        padding: 25px;
        border-radius: 15px;
        color: #f1f1f1;
        border-left: 5px solid #3b82f6;
    }
    .stButton > button {
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
    
    # 1. Determine the correct Wiki Slug
    wiki_slug = WIKI_MAPPING.get(show_name)
    if not wiki_slug:
        wiki_slug = show_name.replace(" ", "").lower()
    
    # 2. Try URL variations for the episode
    # Fandom is case-sensitive and loves "_(episode)" suffixes
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
                # Find the plot section
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    # Greedy loop: Capture EVERYTHING until non-story sections
                    for sibling in start.find_parent().find_next_siblings():
                        if sibling.name in ['h2', 'h3']:
                            h_text = sibling.get_text().lower()
                            if any(stop in h_text for stop in ['cast', 'trivia', 'gallery', 'references', 'videos', 'production']):
                                break
                        if sibling.name in ['p', 'ul', 'ol']:
                            txt = sibling.get_text().strip()
                            if txt: content.append(txt)
                    
                    if content:
                        return "\n\n".join(content), url
        except: continue
    return None, None

# --- UI ---
st.title("📖 TV Vault Reader")
query = st.text_input("Search Show:", placeholder="e.g. Invincible")

if query:
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    if resp:
        show_map = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Select Show:", options=list(show_map.keys()))
        show = show_map[label]
        
        c1, c2 = st.columns(2)
        with c1: s_val = st.number_input("Season", min_value=1, value=1)
        with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("🔓 Extract Full Lore"):
            ep_url = f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}"
            data = requests.get(ep_url).json()
            
            if "name" in data:
                # Use the clean show name from TVmaze
                lore_text, found_url = get_fandom_lore(show['name'], data['name'])
                
                if lore_text:
                    st.subheader(data['name'])
                    if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                    
                    # --- TTS ---
                    if st.button("🔊 Play Full Narration"):
                        with st.spinner("Preparing audio..."):
                            tts = gTTS(text=lore_text, lang='en')
                            tts.save("lore.mp3")
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                    st.markdown(f'<div class="lore-box">{lore_text}</div>', unsafe_allow_html=True)
                    st.caption(f"Source: [Fandom Wiki]({found_url})")
                else:
                    st.error("Lore still not found. The Wiki might use a different name.")
                    st.info(f"Targeting Wiki: {show['name'].replace(' ', '').lower()}.fandom.com")
