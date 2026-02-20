import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

# --- SMART WIKI RESOLVER ---
# This ensures that when you pick a show, it hits the correct Fandom domain
WIKI_ALIASES = {
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot",
    "Star Wars: The Clone Wars": "starwars"
}

# --- MOBILE CSS ---
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

# --- THE RAW SCRAPER ---
def get_raw_fandom_text(wiki_slug, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # URL Variations to ensure we find the right page
    variations = [
        ep_title.replace(" ", "_"),
        ep_title.replace(" ", "_") + "_(episode)",
        ep_title.title().replace(" ", "_"),
        ep_title.title().replace(" ", "_") + "_(episode)"
    ]
    
    for v in variations:
        url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{v}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                # Find the Plot section start
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    # GRAB EVERYTHING: Loop until we hit non-story sections
                    for sibling in start.find_parent().find_next_siblings():
                        if sibling.name in ['h2', 'h3']:
                            h_text = sibling.get_text().lower()
                            if any(stop in h_text for stop in ['cast', 'trivia', 'gallery', 'references', 'production']):
                                break
                        # Keep original paragraph and list structure
                        if sibling.name in ['p', 'ul', 'ol']:
                            txt = sibling.get_text().strip()
                            if txt: content.append(txt)
                    
                    if content:
                        return "\n\n".join(content), url
        except: continue
    return None, None

# --- UI LOGIC ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

if query:
    # 1. TVmaze for show data
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    
    if resp:
        show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Select Result:", options=list(show_options.keys()))
        show_data = show_options[label]
        
        # 2. Automated Slug Mapping
        wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
        st.info(f"Targeting Wiki: {wiki_slug}.fandom.com")

        c1, c2 = st.columns(2)
        with c1: s_val = st.number_input("Season", min_value=1, value=1)
        with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("🔓 Extract Raw Lore"):
            # 3. Get Episode Name
            ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
            api_data = requests.get(ep_url).json()
            
            if "name" in api_data:
                # 4. Fetch the raw text from Fandom
                raw_text, found_url = get_raw_fandom_text(wiki_slug, api_data['name'])
                
                if raw_text:
                    st.header(api_data['name'])
                    if api_data.get('image'): 
                        st.image(api_data['image']['medium'], use_container_width=True)
                    
                    # --- RAW TTS ---
                    if st.button("🔊 Narrate Raw Text"):
                        with st.spinner("Preparing audio..."):
                            tts = gTTS(text=raw_text, lang='en')
                            tts.save("lore.mp3")
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                    # --- RAW DISPLAY ---
                    st.markdown(f'<div class="lore-box">{raw_text}</div>', unsafe_allow_html=True)
                    st.caption(f"Full page text extracted from: [Fandom Wiki]({found_url})")
                else:
                    st.error(f"Could not find the lore at {wiki_slug}.fandom.com. The page structure might be unique.")
