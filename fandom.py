import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺", layout="centered")

# --- MAPPING TABLES ---
# For when the Wiki domain doesn't match the show name
SLUG_OVERRIDES = {
    "The Incredible Hulk": "marvelcinematicuniverse",
    "DC's Legends of Tomorrow": "legendsoftomorrow",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot",
    "Star Wars: The Clone Wars": "starwars"
}

# For when the specific episode URL is weird or different on Fandom
EPISODE_OVERRIDES = {
    "Pilot": "Pilot_(Gilmore_Girls)", # Example for Gilmore Girls
    "33": "33_(Battlestar_Galactica)", # Example for numbers
}

# --- SCRAPER LOGIC ---
def get_fandom_data(show_name, ep_title):
    try:
        # 1. Wiki Slug
        wiki_slug = SLUG_OVERRIDES.get(show_name, show_name.replace(" ", "").lower())
            
        # 2. Episode Slug (Check overrides first)
        if ep_title in EPISODE_OVERRIDES:
            ep_slug = EPISODE_OVERRIDES[ep_title]
        else:
            ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        
        # 3. Fuzzy Check: If page doesn't exist, try adding "_(episode)"
        if res.status_code != 200:
            url = f"{url}_(episode)"
            res = requests.get(url, headers=headers, timeout=5)

        st.session_state.debug_url = url
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot'])
            if synopsis:
                paras = []
                curr = synopsis.find_parent().find_next_sibling()
                while curr and curr.name == 'p' and len(paras) < 3:
                    if curr.text.strip(): paras.append(curr.text.strip())
                    curr = curr.find_next_sibling()
                return " ".join(paras)
    except:
        return None
    return None

# --- UI & LOGIC ---
if "history" not in st.session_state: st.session_state.history = []

st.title("📺 TV Vault Pro")
app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search for a show", placeholder="e.g. Gilmore Girls")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            selected_label = st.selectbox("Select Show", options=list(show_options.keys()))
            show_data = show_options[selected_label]
            
            if selected_label not in st.session_state.history:
                st.session_state.history.append(selected_label)

            if app_mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("Syncing databases..."):
                    if app_mode == "Single Episode":
                        url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        
                        if "name" in data:
                            fandom_lore = get_fandom_data(show_data['name'], data['name'])
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            prompt = f"""
                            Recap S{s_val}E{ep_val} of {show_data['name']}.
                            Title: {data['name']}
                            Fandom Deep Lore: {fandom_lore if fandom_lore else "Use internal knowledge."}
                            Summary: {re.sub('<[^<]+>', '', data.get('summary', ''))}

                            RULES: Natural tone, no bolding, no spoilers. End with trivia.
                            """
                        else:
                            st.error("Episode not found.")
                            st.stop()
                    else:
                        # Full Season Logic
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            full_text = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Summarize {show_data['name']} Season {s_val}. Context: {full_text[:3500]}."
                            if target.get('image'): st.image(target['image']['medium'])

                    # AI EXECUTION
                    client = genai.Client(api_key=GEMINI_KEY)
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    st.write(res.text)

                    with st.expander("🛠️ Advanced URL Mapping"):
                        st.write(f"**Show:** {show_data['name']} | **Fandom Link:** {st.session_state.get('debug_url', 'N/A')}")
    except Exception as e:
        st.error(f"Error: {e}")