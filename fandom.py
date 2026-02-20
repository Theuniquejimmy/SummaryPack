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

# --- SLUG OVERRIDES ---
SLUG_OVERRIDES = {
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot",
    "Star Wars: The Clone Wars": "starwars"
}

# --- STYLING ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #3b82f6;
        color: white;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
        border: none;
    }
    /* Increase font size for readability on longer answers */
    .stMarkdown p {
        font-size: 1.1em;
        line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)

# --- SCRAPER ---
def get_fandom_data(show_name, ep_title):
    try:
        wiki_slug = SLUG_OVERRIDES.get(show_name, show_name.replace(" ", "").lower())
        ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            url = f"{url}_(episode)"
            res = requests.get(url, headers=headers, timeout=5)

        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot'])
            if synopsis:
                # Pull more paragraphs for a deeper word count
                paras = [p.text.strip() for p in synopsis.find_parent().find_next_siblings('p')[:5]]
                return " ".join(paras)
    except: return None
    return None

st.title("📺 TV Vault Pro")
st.caption("Deep-Dive AI Recaps & Lore")

# --- APP MODES ---
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

            if st.button(f"Generate Deep {mode} Recap"):
                with st.spinner("Analyzing deep lore and writing..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast").json()
                        if "name" in ep_data:
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            
                            # PROMPT: Increased word limit/detail instructions
                            prompt = f"""
                            Act as a TV historian. Write a comprehensive recap of S{s_val}E{ep_val} of {show['name']}.
                            Title: {ep_data['name']}
                            Fandom Lore: {lore}
                            Summary: {re.sub('<[^<]+>', '', ep_data.get('summary', ''))}

                            INSTRUCTIONS:
                            1. Go into great detail about character motivations, specific subplots (like Ross/Rachel or Paolo drama).
                            2. Do not hold back on word count—be thorough and expansive.
                            3. Use a friendly, expert tone. No bolding. Use bullet points for easier reading.
                            4. Be sure to cover how the epoisode ends and where we'll need to be for the next one.
                            """
                        else: st.error("Not found."); st.stop()
                    else:
                        # Full Season Recap
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            # Increased character limit for season context to allow more detail
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"""
                            Write an exhaustive, high-word-count season recap for {show['name']} Season {s_val}.
                            Context: {context[:5000]}
                            
                            INSTRUCTIONS:
                            1. Analyze the entire season's arc. Discuss how the status quo changed from the first to the last episode.
                            2. Provide in-depth analysis of character development for all lead roles.
                            3. Be expansive and detailed.
                            4. No bolding.
                            5. Identify at least TWO important plot point for every episode of the season so, if season has 25 epsiodes 50 plot points at least and write them with great detail that if you havn't seen the episode you'd know the main plot. Cite each with episode tag its from "S*E*" and list them in order of episode.
                            6. do not skip episodes, every episode should include a plot point. make a bullet point list.
                            7. What I need to know for next season.

                            """
                            if target.get('image'): st.image(target['image']['medium'])
                        else: st.error("Not found."); st.stop()

                    # --- AI EXECUTION: GROQ PRIMARY ---
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
else:
    st.info("Search a show to begin your deep-dive.")





