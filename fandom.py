import streamlit as st
import requests
import re
import urllib.parse
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot"
}

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
    }
    div.stButton > button {
        width: 100%;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- THE DOCUMENT ORDER SCANNER ---
def get_raw_lore(wiki_slug, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # FIX 1: Safely encode apostrophes and special characters for Fandom URLs
    base_title = ep_title.replace(" ", "_")
    patterns = [
        urllib.parse.quote(base_title),
        urllib.parse.quote(base_title + "_(episode)"),
        urllib.parse.quote(ep_title.title().replace(" ", "_"))
    ]
    
    for p in patterns:
        url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{p}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                content_div = soup.find('div', class_='mw-parser-output')
                
                if not content_div: 
                    continue
                
                content = []
                # FIX 2: Scan the entire document sequentially
                for tag in content_div.find_all(['h2', 'h3', 'p', 'ul', 'ol']):
                    
                    # IGNORE the right-hand sidebar/infobox and table of contents
                    if tag.find_parent('aside') or tag.find_parent('table') or tag.find_parent('nav') or tag.get('id') == 'toc':
                        continue
                    
                    # Check for STOP headers
                    if tag.name in ['h2', 'h3']:
                        h_text = tag.get_text().lower()
                        stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos', 'notes']
                        if any(stop in h_text for stop in stop_words):
                            break # We hit the end of the story, stop entirely
                    
                    # Collect the actual text
                    elif tag.name in ['p', 'ul', 'ol']:
                        txt = tag.get_text().strip()
                        # Filter out tiny blank artifacts or spacing issues
                        if len(txt) > 25:
                            content.append(txt)
                
                if content:
                    return "\n\n".join(content), url
        except Exception:
            continue
            
    return None, None

# --- UI ---
st.title("📖 TV Vault Reader")

query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            
            wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: s_val = st.number_input("Season", min_value=1, value=1)
            with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

            if st.button("🔓 Extract Full Lore"):
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                api_res = requests.get(api_url).json()
                
                if "name" in api_res:
                    raw_text, found_url = get_raw_lore(wiki_slug, api_res['name'])
                    
                    if raw_text:
                        st.subheader(api_res['name'])
                        if api_res.get('image'): st.image(api_res['image']['medium'])
                        
                        if st.button("🔊 Play Audio"):
                            tts = gTTS(text=raw_text, lang='en')
                            tts.save("lore.mp3")
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                        st.markdown(f'<div class="lore-box">{raw_text}</div>', unsafe_allow_html=True)
                        st.caption(f"Source: {found_url}")
                    else:
                        st.error("Story section not found. The page layout might be entirely blank or blocked.")
                else:
                    st.error("Episode not found in database.")
    except Exception as e:
        st.error(f"Error: {e}")
