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

# --- SLUG CORRECTION TABLE ---
# Add any shows here that don't follow the standard "showname.fandom" rule
SLUG_OVERRIDES = {
    "The Incredible Hulk": "marvelcinematicuniverse",
    "DC's Legends of Tomorrow": "legendsoftomorrow",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot",
    "Star Wars: The Clone Wars": "starwars"
}

# Initialize History & Debug Logs
if "history" not in st.session_state: st.session_state.history = []
if "debug_url" not in st.session_state: st.session_state.debug_url = ""

# --- SCRAPER WITH SLUG LOGIC ---
def get_fandom_data(show_name, ep_title):
    try:
        # 1. Determine the Wiki Slug (Check override first, then default)
        wiki_slug = SLUG_OVERRIDES.get(show_name)
        if not wiki_slug:
            wiki_slug = show_name.replace(" ", "").lower()
            
        # 2. Clean Episode Title for URL
        # Fandom removes most punctuation and replaces spaces with underscores
        ep_slug = re.sub(r'[^\w\s-]', '', ep_title).replace(" ", "_")
        
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        st.session_state.debug_url = url
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # Fandom often hides the summary under these specific IDs
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot', 'Episode_Summary'])
            if synopsis:
                paras = []
                # Look for the actual text content following the header
                curr = synopsis.find_parent().find_next_sibling()
                while curr and curr.name == 'p' and len(paras) < 3:
                    if curr.text.strip():
                        paras.append(curr.text.strip())
                    curr = curr.find_next_sibling()
                return " ".join(paras)
    except:
        return None
    return None

# --- SIDEBAR & UI ---
with st.sidebar:
    st.title("🕒 Recent Searches")
    for item in reversed(st.session_state.history[-5:]):
        st.info(item)
    if st.button("Clear History"):
        st.session_state.history = []
        st.rerun()

st.title("📺 TV Vault Pro")

# --- APP LOGIC ---
app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search for a show", placeholder="e.g. The Incredible Hulk")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            # Map labels to show data
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            selected_label = st.selectbox("Select Show", options=list(show_options.keys()))
            show_data = show_options[selected_label]
            
            if selected_label not in st.session_state.history:
                st.session_state.history.append(selected_label)

            # Input fields
            if app_mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("Hunting for deep lore..."):
                    if app_mode == "Single Episode":
                        # TVmaze Core Data
                        url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        
                        if "name" in data:
                            # Fandom Deep Search
                            fandom_lore = get_fandom_data(show_data['name'], data['name'])
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            clean_summary = re.sub('<[^<]+>', '', data.get('summary', ''))
                            guest_list = data.get('_embedded', {}).get('guestcast', [])
                            guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "None"

                            prompt = f"""
                            Recap S{s_val}E{ep_val} of {show_data['name']}.
                            Title: {data['name']}
                            Guests: {guests}
                            TVmaze Snippet: {clean_summary}
                            Fandom Deep Lore: {fandom_lore if fandom_lore else "Use internal knowledge."}

                            RULES:
                            1. Write a high-detail, conversational recap.
                            2. Use the lore notes to mention subplots or specific character beats.
                            3. NO bolding. NO spoilers for the end.
                            4. End with a unique trivia fact.
                            """
                        else:
                            st.error("Episode not found.")
                            st.stop()
                    else:
                        # Full Season Recap
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_data['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            full_text = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Summarize story arcs for {show_data['name']} Season {s_val}. Context: {full_text[:3500]}."
                            if target.get('image'): st.image(target['image']['medium'])
                        else:
                            st.error("Season not found.")
                            st.stop()

                    # AI Call
                    try:
                        client = genai.Client(api_key=GEMINI_KEY)
                        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(res.text)
                    except:
                        groq_client = Groq(api_key=GROQ_KEY)
                        chat = groq_client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.write(chat.choices[0].message.content)

                    # Debugger
                    with st.expander("🛠️ Slug & URL Debugger"):
                        st.code(f"Show Name: {show_data['name']}\nTarget URL: {st.session_state.debug_url}")
                        if fandom_lore: st.success("Fandom Data Successfully Scraped!")
                        else: st.warning("Fandom Data Not Found - Defaulting to AI Knowledge.")

    except Exception as e:
        st.error(f"App Error: {e}")
else:
    st.info("Search a show to begin!")
