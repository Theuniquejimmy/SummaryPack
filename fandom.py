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

# --- SCRAPER: FULL SECTION FETCH ---
def get_fandom_data(show_name, ep_title):
    try:
        wiki_slug = show_name.replace(" ", "").lower()
        ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        
        # Fuzzy check if the primary URL fails
        if res.status_code != 200:
            res = requests.get(f"{url}_(episode)", headers=headers, timeout=5)

        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # Identify the start of the plot/synopsis section
            synopsis_span = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
            
            if synopsis_span:
                content = []
                # Start at the parent header (usually <h2> or <h3>)
                current_element = synopsis_span.find_parent()
                
                # Iterate through siblings until the next header is reached
                for sibling in current_element.find_next_siblings():
                    if sibling.name in ['h2', 'h3']:
                        break
                    if sibling.name == 'p':
                        text = sibling.get_text(strip=True)
                        if text:
                            content.append(text)
                
                return "\n\n".join(content)
    except:
        return None
    return None

st.title("📺 TV Vault Pro")
st.subheader("Deep-Dive AI Recaps")

# --- UI ---
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Gilmore Girls")

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
                with st.spinner("Processing full lore and analyzing climax..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}").json()
                        if "name" in ep_data:
                            # Fetch the entire plot section from Fandom
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            
                            # PROMPT: Focus on narrative depth and word count
                            prompt = f"""
                            Act as a TV Historian. Provide a high-word-count, exhaustive recap of S{s_val}E{ep_val} of {show['name']}.
                            Episode Title: {ep_data['name']}
                            Fandom Deep-Lore (Full Plot Section): {lore}
                            Database Snippet: {re.sub('<[^<]+>', '', ep_data.get('summary', ''))}

                            INSTRUCTIONS:
                            1. Use the Fandom Deep-Lore to provide a beat-by-beat narrative of the entire episode.
                            2. You MUST include the climax, the final fight/confrontation, and the resolution. Do not stop early.
                            3. Analyze character motivations and subplots in depth.
                            4. Use a friendly, conversational, but expert tone.
                            5. NO BOLDING. No hashtags.
                            6. End with three specific, high-detail trivia facts.
                            """
                        else:
                            st.error("Episode not found.")
                            st.stop()
                    else:
                        # Full Season Recap
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"""
                            Write an exhaustive narrative recap for {show['name']} Season {s_val}. 
                            Context: {context[:8000]}
                            
                            INSTRUCTIONS:
                            1. Describe the overarching story arcs and character evolution in massive detail.
                            2. Focus heavily on the season finale and how it resolves the season's tension.
                            3. Friendly tone, no bolding, be expansive and narrative-driven.
                            """
                            if target.get('image'): st.image(target['image']['medium'])
                        else:
                            st.error("Season not found.")
                            st.stop()

                    # --- EXECUTION: GROQ PRIMARY ---
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

    except Exception as e:
        st.error(f"App Error: {e}")
else:
    st.info("Search a show to begin your deep-dive.")
