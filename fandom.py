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

# --- SCRAPER ---
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
            # Look for the Plot or Synopsis headers
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot'])
            if synopsis:
                # Pull 6 paragraphs to ensure we hit the end of the episode
                paras = [p.text.strip() for p in synopsis.find_parent().find_next_siblings('p')[:6]]
                return " ".join(paras)
    except: return None
    return None

st.title("📺 TV Vault Pro")
st.subheader("Deep-Dive AI Recaps")

# --- UI LOGIC ---
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Friends")

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

            if st.button(f"Generate Exhaustive {mode} Recap"):
                with st.spinner("Accessing archives and training data..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}").json()
                        if "name" in ep_data:
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            
                            # UPDATED PROMPT: Focusing on the Climax
                            prompt = f"""
                            Act as a TV Expert. Provide an exhaustive, beat-by-beat recap of S{s_val}E{ep_val} of {show['name']}.
                            Episode Title: {ep_data['name']}
                            Fandom Lore: {lore}
                            Database Snippet: {re.sub('<[^<]+>', '', ep_data.get('summary', ''))}

                            CRITICAL INSTRUCTIONS:
                            1. The 'Database Snippet' is often incomplete. You MUST use your internal training data to include the entire episode, ESPECIALLY the climax, final scenes, and any major fights or cliffhangers.
                            2. Do not stop where the snippet stops. Describe the resolution of the episode in detail.
                            3. Use a natural, narrative tone. No bolding. 
                            4. End with a "Deep Lore" trivia fact.
                            """
                        else: st.error("Not found."); st.stop()
                    else:
                        # Season Logic
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Write a massive narrative recap for {show['name']} Season {s_val}. Context: {context[:5000]}. Focus on the season finale and big character shifts."
                            if target.get('image'): st.image(target['image']['medium'])
                        else: st.error("Not found."); st.stop()

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
