import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

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
        border: 1px solid #3b82f6;
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

# --- THE PURE FANDOM SCRAPER ---
def get_fandom_lore(wiki_name, ep_title):
    headers = {'User-Agent': 'Mozilla/5.0'}
    # Clean the slugs for URL formatting
    wiki_slug = wiki_name.strip().replace(" ", "").lower()
    
    # Try the most common Fandom URL variations
    variations = [
        ep_title.strip().replace(" ", "_"),
        ep_title.strip().replace(" ", "_") + "_(episode)",
        ep_title.strip().title().replace(" ", "_"),
        ep_title.strip().title().replace(" ", "_") + "_(episode)"
    ]
    
    for v in variations:
        url = f"https://{wiki_slug}.fandom.com/wiki/{v}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                # Hunt for the plot starting point
                start = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
                
                if start:
                    content = []
                    # Greedy loop: Grab every paragraph/list until non-story sections
                    for sibling in start.find_parent().find_next_siblings():
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

# --- UI ---
st.title("📖 TV Vault Reader")
st.subheader("Manual Lore Extraction")

# Manual Inputs (Replacing TVmaze Search)
col1, col2 = st.columns(2)
with col1:
    wiki_input = st.text_input("Wiki Name:", placeholder="e.g. invincible")
with col2:
    ep_input = st.text_input("Episode Title:", placeholder="e.g. It's About Time")

st.caption(f"Will target: **{wiki_input if wiki_input else '...'}.fandom.com/wiki/{ep_input.replace(' ', '_') if ep_input else '...'}**")

if st.button("🔓 Extract Full Lore"):
    if wiki_input and ep_input:
        with st.spinner("Searching Fandom archives..."):
            lore_text, found_url = get_fandom_lore(wiki_input, ep_input)
            
            if lore_text:
                st.write("---")
                
                # --- TTS SECTION ---
                if st.button("🔊 Play Full Narration"):
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
                st.error("Lore not found. Check the Wiki name and Episode title spelling.")
    else:
        st.warning("Please enter both a Wiki name and an Episode title.")
