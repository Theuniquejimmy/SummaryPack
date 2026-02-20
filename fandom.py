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

# --- GREEDY SCRAPER ---
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
                current = start_node.find_parent()
                for sibling in current.find_next_siblings():
                    if sibling.name in ['h2', 'h3']:
                        header_text = sibling.get_text().lower()
                        if any(stop in header_text for stop in ['cast', 'trivia', 'gallery', 'references', 'videos', 'production']):
                            break
                    if sibling.name in ['p', 'ul', 'ol']:
                        text = sibling.get_text().strip()
                        if text: content.append(text)
                return "\n\n".join(content)
    except: return None
    return None

st.title("📺 TV Vault Pro")

# --- UI LOGIC ---
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Show:", options=list(show_options.keys()))
            show_data = show_options[label]
            
            if mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate Accurate Recap"):
                with st.spinner("Locking temporal coordinates..."):
                    if mode == "Single Episode":
                        ep_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                        data = requests.get(ep_url).json()
                        
                        if "name" in data:
                            lore = get_fandom_data(show_data['name'], data['name'])
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            # THE TEMPORAL-LOCK PROMPT
                            prompt = f"""
                            Act as a TV Chronologist. Recap ONLY Season {s_val}, Episode {ep_val} of {show_data['name']}.
                            Title: {data['name']}
                            WIKI DATA: {lore}

                            STRICT TEMPORAL RULES:
                            1. You are strictly forbidden from including events that occurred in previous episodes (like the massacre at the end of Episode 1) unless they are being actively discussed or investigated in THIS episode.
                            2. Do not "hallucinate" the big twist from a previous episode into this recap. Focus on the plot progression of THIS specific hour.
                            3. Use the WIKI DATA as your primary source of truth for where this episode begins and ends.
                            4. If this is Episode 2, focus on the AFTERMATH and investigation, not the fight itself.
                            5. No bolding. Natural, detailed tone.
                            """
                        else: st.error("Episode not found."); st.stop()
                    
                    else:
                        # Season mode
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Recap {show_data['name']} Season {s_val}. Context: {context[:8000]}."
                        else: st.error("Season not found."); st.stop()

                    # --- EXECUTION ---
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
