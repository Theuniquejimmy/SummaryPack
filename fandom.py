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

# --- MASTER SCRAPER: READS THE ENTIRE PAGE ---
def get_fandom_data(show_name, ep_title):
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
                # Greedy search: Grab everything until the very end of the article
                for sibling in start_node.find_parent().find_next_siblings():
                    # Stop ONLY at references or footer sections
                    if sibling.name in ['h2', 'h3']:
                        header_text = sibling.get_text().lower()
                        if any(stop in header_text for stop in ['references', 'gallery', 'videos', 'external', 'navigation']):
                            break
                    if sibling.name in ['p', 'ul', 'ol']:
                        content.append(sibling.get_text().strip())
                return "\n\n".join(content)
    except: return None
    return None

st.title("📺 TV Vault Pro")
st.caption("Deep-Dive mode enabled: Maximum detail, zero bleeding.")

# --- UI LOGIC ---
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Show:", options=list(show_map.keys())) if 'show_map' in locals() else st.selectbox("Select Show:", options=list(show_options.keys()))
            show_data = show_options[label]
            
            if mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate Epic {mode} Recap"):
                with st.spinner("Writing a high-detail narrative..."):
                    if mode == "Single Episode":
                        ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                        data = requests.get(ep_url).json()
                        
                        if "name" in data:
                            lore = get_fandom_data(show_data['name'], data['name'])
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            # THE "EPIC SCALE" PROMPT
                            prompt = f"""
                            Act as a Professional TV Critic. Write an EXHAUSTIVE, 1000+ word narrative recap of ONLY Season {s_val}, Episode {ep_val} of {show_data['name']}.
                            Episode Title: {data['name']}
                            FULL WIKI TEXT: {lore}

                            STRUCTURE:
                            1. PREVIOUSLY ON: A 2-sentence summary of the major cliffhanger from the previous episode to set the stage.
                            2. THE SETUP: Detailed breakdown of the episode's opening and character motivations.
                            3. THE ESCALATION: Beat-by-beat narrative of the middle-act action and dialogue.
                            4. THE CLIMAX & ENDING: A massive, vivid description of the final confrontation, including any post-credits scenes.
                            
                            STRICT RULES:
                            - Use the FULL WIKI TEXT provided. Do not skip any paragraphs.
                            - Stay strictly within the timeline of THIS episode for the main body.
                            - Be descriptive, atmospheric, and conversational.
                            - NO BOLDING.
                            """
                        else: st.error("Episode not found."); st.stop()
                    else:
                        # Full Season mode
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Write a massive 2000-word narrative recap for {show_data['name']} Season {s_val}. Context: {context[:8000]}."
                        else: st.error("Season not found."); st.stop()

                    # --- AI EXECUTION ---
                    client = Groq(api_key=GROQ_KEY)
                    chat = client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                    )
                    st.write(chat.choices[0].message.content)

    except Exception as e: st.error(f"Error: {e}")
