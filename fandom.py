import streamlit as st
import requests
import re
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

# --- SCRAPER LOGIC ---
def get_raw_lore(wiki_slug, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # We try every naming pattern Fandom uses
    patterns = [
        ep_title.replace(" ", "_"),                             # "Here_Goes_Nothing"
        ep_title.replace(" ", "_") + "_(episode)",               # "Here_Goes_Nothing_(episode)"
        ep_title.title().replace(" ", "_"),                      # "Here_Goes_Nothing" (Title Case)
        ep_title.title().replace(" ", "_") + "_(episode)"        # "Here_Goes_Nothing_(episode)" (Title Case)
    ]
    
    for p in patterns:
        url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{p}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                # Hunt for the Plot start
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    # Greedy loop: Capture every paragraph/list until a non-story section
                    for sibling in start.find_parent().find_next_siblings():
                        if sibling.name in ['h2', 'h3']:
                            h_text = sibling.get_text().lower()
                            if any(stop in h_text for stop in ['cast', 'trivia', 'gallery', 'references', 'production', 'credits']):
                                break
                        if sibling.name in ['p', 'ul', 'ol']:
                            txt = sibling.get_text().strip()
                            if txt: content.append(txt)
                    
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

            if st.button("🔓 Extract Raw Lore"):
                ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                api_res = requests.get(ep_url)
                
                if api_res.status_code == 200:
                    api_data = api_res.json()
                    raw_text, found_url = get_raw_lore(wiki_slug, api_data['name'])
                    
                    if raw_text:
                        st.subheader(api_data['name'])
                        if api_data.get('image'): st.image(api_data['image']['medium'])
                        
                        # TTS Section
                        if st.button("🔊 Narrate Raw Text"):
                            tts = gTTS(text=raw_text, lang='en')
                            tts.save("lore.mp3")
                            with open("lore.mp3", "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                        # Display Section
                        st.markdown(f'<div class="lore-box">{raw_text}</div>', unsafe_allow_html=True)
                        st.caption(f"Full text pulled from: {found_url}")
                    else:
                        st.error(f"Lore not found at {wiki_slug}.fandom.com. The page might use a different name.")
                else:
                    st.error("Could not find this episode in the TVmaze database.")
    except Exception as e:
        st.error(f"System Error: {e}")
