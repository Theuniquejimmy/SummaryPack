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

# Initialize Session States
if "history" not in st.session_state: st.session_state.history = []
if "debug_url" not in st.session_state: st.session_state.debug_url = ""

# --- SLUG & EPISODE OVERRIDES ---
SLUG_OVERRIDES = {
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot"
}

# --- STYLING ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #f63366;
        color: white;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
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

        st.session_state.debug_url = url
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot'])
            if synopsis:
                paras = [p.text.strip() for p in synopsis.find_parent().find_next_siblings('p')[:3]]
                return " ".join(paras)
    except: return None
    return None

# --- SIDEBAR ---
with st.sidebar:
    st.title("🕒 History")
    for h in reversed(st.session_state.history[-5:]): st.info(h)
    if st.button("Clear History"):
        st.session_state.history = []
        st.rerun()

st.title("📺 TV Vault Pro")
mode = st.radio("Mode:", ["Single Episode", "Full Season"], horizontal=True)
query = st.text_input("Search Show:", placeholder="e.g. Gilmore Girls")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_map = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Show:", options=list(show_map.keys()))
            show = show_map[label]
            
            if label not in st.session_state.history: st.session_state.history.append(label)

            if mode == "Single Episode":
                c1, c2 = st.columns(2)
                with c1: s_val = st.number_input("Season", min_value=1, value=1)
                with c2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)
                ep_val = 1

            if st.button(f"Generate {mode} Recap"):
                with st.spinner("⚡ Groq is processing..."):
                    if mode == "Single Episode":
                        ep_data = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast").json()
                        if "name" in ep_data:
                            lore = get_fandom_data(show['name'], ep_data['name'])
                            if ep_data.get('image'): st.image(ep_data['image']['medium'], use_container_width=True)
                            prompt = f"Recap S{s_val}E{ep_val} of {show['name']}. Title: {ep_data['name']}. Fandom Lore: {lore}. Summary: {re.sub('<[^<]+>', '', ep_data.get('summary', ''))}. RULES: Detailed, natural tone, no bolding. End with trivia."
                        else: st.error("Not found."); st.stop()
                    else:
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/seasons").json()
                        target = next((s for s in seasons if s['number'] == s_val), None)
                        if target:
                            eps = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in eps])
                            prompt = f"Summarize {show['name']} Season {s_val}. Context: {context[:3000]}. RULES: Focus on arcs, friendly tone, no bolding."
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
                        st.caption("🚀 Powered by Groq (Llama 3.3)")
                    except Exception as e:
                        st.warning("Groq busy, falling back to Gemini...")
                        try:
                            m_client = genai.Client(api_key=GEMINI_KEY)
                            res = m_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                            st.write(res.text)
                            st.caption("✨ Fallback Recap by Gemini 2.0")
                        except: st.error("Both AI services are down!")

                    with st.expander("🛠️ Debugger"):
                        st.write(f"**URL:** {st.session_state.debug_url}")
    except Exception as e: st.error(f"Error: {e}")
