import streamlit as st
import requests
import re
import os
from groq import Groq
from google import genai
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺", layout="centered")

# --- GREEDY SCRAPER: CAPTURES EVERY SECTION UNTIL CAST ---
def get_fandom_data(show_name, ep_title):
    try:
        wiki_slug = show_name.replace(" ", "").lower()
        # Clean episode title for Fandom URL standards
        ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code != 200:
            res = requests.get(f"{url}_(episode)", headers=headers, timeout=5)

        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # Find the very first plot-related header
            start_node = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
            
            if start_node:
                content = []
                current = start_node.find_parent()
                
                # LOOP: Capture EVERYTHING until we hit a "Stop" section
                for sibling in current.find_next_siblings():
                    if sibling.name in ['h2', 'h3']:
                        header_text = sibling.get_text().lower()
                        # Only stop if we hit non-story sections
                        if any(stop in header_text for stop in ['cast', 'trivia', 'gallery', 'references', 'videos', 'production']):
                            break
                    
                    # Add paragraph text and list items (often used for action sequences)
                    if sibling.name in ['p', 'ul', 'ol']:
                        text = sibling.get_text().strip()
                        if text:
                            content.append(text)
                
                return "\n\n".join(content)
    except:
        return None
    return None

st.title("📺 TV Vault Pro")
st.caption("Now capturing full post-credits and ending lore.")

# --- UI LOGIC ---
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_map = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Show:", options=list(show_map.keys()))
            show = show_map[label]
            
            if mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate Exhaustive Recap"):
                with st.spinner("Analyzing full wiki lore, including post-credits..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}").json()
                        if "name" in ep_data:
                            # This now grabs the WHOLE plot, including the massacre section
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            
                            # THE "NO-MERCY" PROMPT
                            prompt = f"""
                            Act as a TV Historian. Write an exhaustive, beat-by-beat narrative of S{s_val}E{ep_val} of {show['name']}.
                            Episode Title: {ep_data['name']}
                            FULL WIKI CONTENT: {lore}

                            STRICT REQUIREMENTS:
                            1. DO NOT summarize. You must describe the entire episode from start to finish.
                            2. You MUST include the climax and the absolute final scene of the episode in gruesome detail if necessary.
                            3. Pay special attention to any "Ending" or "Post-credits" events (specifically the Omni-Man vs Guardians of the Globe massacre). 
                            4. If it is in the WIKI CONTENT provided, it MUST be in your recap.
                            5. Use a dark, serious, and detailed narrative tone. NO BOLDING.
                            6. End with 3 trivia facts.
                            """
                        else: st.error("Not found."); st.stop()
                    else:
                        # Season mode
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Recap {show['name']} Season {s_val}. Context: {context[:8000]}. Focus on major character shifts."
                            if target.get('image'): st.image(target['image']['medium'])

                    # --- AI EXECUTION ---
                    try:
                        g_client = Groq(api_key=GROQ_KEY)
                        chat = g_client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.write(chat.choices[0].message.content)
                    except:
                        m_client = genai.Client(api_key=GEMINI_KEY)
                        res = m_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(res.text)

    except Exception as e: st.error(f"Error: {e}")
