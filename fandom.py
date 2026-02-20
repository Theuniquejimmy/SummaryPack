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

# --- GREEDY SCRAPER: GETS EVERYTHING UNTIL TRIVIA/CAST ---
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
            # Look for the start of the plot
            start_node = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
            
            if start_node:
                content = []
                # Get the header containing the span (usually an h2)
                current = start_node.find_parent()
                
                # Loop through every sibling until we hit the "Cast" or "Trivia" section
                for sibling in current.find_next_siblings():
                    # Stop if we hit a section that isn't plot-related
                    if sibling.name in ['h2', 'h3']:
                        header_text = sibling.get_text().lower()
                        if any(stop_word in header_text for stop_word in ['cast', 'trivia', 'gallery', 'references', 'videos']):
                            break
                    
                    if sibling.name == 'p':
                        content.append(sibling.get_text().strip())
                    elif sibling.name in ['ul', 'ol']:
                        content.append(sibling.get_text().strip())
                
                return "\n\n".join(content)
    except:
        return None
    return None

st.title("📺 TV Vault Pro")
st.subheader("Exhaustive AI Deep-Dives")

# --- UI ---
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

            if st.button(f"Generate Total Recap"):
                with st.spinner("Scraping full wiki pages and analyzing the ending..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}").json()
                        if "name" in ep_data:
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            
                            # PROMPT: Explicit Climax Instructions
                            prompt = f"""
                            Act as a TV Expert. Write a massive, comprehensive recap of S{s_val}E{ep_val} of {show['name']}.
                            Title: {ep_data['name']}
                            FULL WIKI TEXT: {lore}

                            STRICT INSTRUCTIONS:
                            1. DO NOT summarize. Write a long, beat-by-beat narrative of the entire episode.
                            2. You MUST include the ending/climax in vivid detail. 
                            3. Specifically check for "post-credits" or "twist endings" (like the Omni-Man fight in Invincible) and describe them thoroughly.
                            4. If the Wiki text is long, use all of it to flesh out the action scenes.
                            5. NO BOLDING. Natural, expert tone.
                            6. End with 3 trivia facts.
                            """
                        else: st.error("Not found."); st.stop()
                    else:
                        # Full Season Recap
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Write a long narrative for {show['name']} Season {s_val}. Context: {context[:8000]}. Focus on major character deaths and season finales."
                            if target.get('image'): st.image(target['image']['medium'])
                        else: st.error("Not found."); st.stop()

                    # --- EXECUTION ---
                    try:
                        g_client = Groq(api_key=GROQ_KEY)
                        chat = g_client.chat.complet_req = g_client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.write(chat.choices[0].message.content)
                    except:
                        m_client = genai.Client(api_key=GEMINI_KEY)
                        res = m_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(res.text)

    except Exception as e: st.error(f"Error: {e}")
else:
    st.info("Search a show to begin the deep-dive.")
