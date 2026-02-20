import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

# --- CUSTOM CSS ---
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

# --- THE SCRAPER (V3) ---
def get_fandom_lore(wiki_slug, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Variations to hunt for the right URL
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
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    # Greedy loop: Capture everything until Cast or Trivia
                    for sibling in start.find_parent().find_next_siblings():
                        if sibling.name in ['h2', 'h3']:
                            h_text = sibling.get_text().lower()
                            if any(stop in h_text for stop in ['cast', 'trivia', 'gallery', 'references']):
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

# 1. Search with Typo Tolerance
query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

if query:
    resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
    
    if resp:
        show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
        label = st.selectbox("Select Show:", options=list(show_options.keys()))
        show_data = show_options[label]
        
        # 2. Manual Override (The 'Invincible' Fix)
        # Defaults to the TVmaze name, but you can change it if it fails
        wiki_name = st.text_input("Fandom Wiki Name:", value=show_data['name'].replace(" ", "").lower())
        st.caption(f"Currently targeting: **{wiki_name}.fandom.com**")

        c1, c2 = st.columns(2)
        with c1: s_val = st.number_input("Season", min_value=1, value=1)
        with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

        if st.button("🔓 Open the Vault"):
            ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
            api_data = requests.get(ep_url).json()
            
            if "name" in api_data:
                lore_text, found_url = get_fandom_lore(wiki_name, api_data['name'])
                
                if lore_text:
                    st.header(f"{api_data['name']}")
                    if api_data.get('image'): st.image(api_data['image']['medium'], use_container_width=True)
                    
                    if st.button("🔊 Read Out Loud"):
                        tts = gTTS(text=lore_text, lang='en')
                        tts.save("lore.mp3")
                        with open("lore.mp3", "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                            st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                    st.markdown(f'<div class="lore-box">{lore_text}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Lore not found at {wiki_name}.fandom.com. Check if the Wiki name is correct!")
