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

# --- SESSION STATE FOR HISTORY ---
if "history" not in st.session_state:
    st.session_state.history = []

# --- MOBILE UI STYLING ---
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
    </style>
    """, unsafe_allow_html=True)

# --- WEB SCRAPING FUNCTION ---
def get_fandom_data(show_name, ep_title):
    try:
        wiki_slug = show_name.replace(" ", "").lower()
        ep_slug = ep_title.replace(" ", "_")
        url = f"https://{wiki_slug}.fandom.com/wiki/{ep_slug}"
        
        # Save to debug state
        st.session_state.debug_url = url
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            synopsis = soup.find('span', id=lambda x: x and x in ['Synopsis', 'Summary', 'Plot'])
            if synopsis:
                paras = []
                curr = synopsis.find_parent().find_next_sibling()
                while curr and curr.name == 'p' and len(paras) < 3:
                    paras.append(curr.text)
                    curr = curr.find_next_sibling()
                return " ".join(paras)
    except:
        return None
    return None

# --- SIDEBAR ---
with st.sidebar:
    st.title("🕒 Recent Searches")
    for item in reversed(st.session_state.history[-5:]):
        st.info(item)
    if st.button("Clear History"):
        st.session_state.history = []
        st.rerun()

st.title("📺 TV Vault Pro")
st.caption("Now with Fandom Wiki Deep-Lore Integration")

# --- APP LOGIC ---
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
                col1, col2 = st.columns(2)
                with col1: s_val = st.number_input("Season", min_value=1, value=1)
                with col2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Season", min_value=1, value=1)

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("Searching TVmaze & Fandom Wikis..."):
                    
                    if app_mode == "Single Episode":
                        # 1. Get TVmaze Data
                        url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        
                        if "name" in data:
                            # 2. Try to "Boost" with Fandom Wiki
                            fandom_lore = get_fandom_data(show_data['name'], data['name'])
                            
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            clean_summary = re.sub('<[^<]+>', '', data.get('summary', ''))
                            guest_list = data.get('_embedded', {}).get('guestcast', [])
                            guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "None"

                            # THE ENHANCED PROMPT
                            prompt = f"""
                            Act as a TV expert and super-fan. Recap S{s_val}E{ep_val} of {selected_label}.
                            Title: {data['name']}
                            Guests: {guests}
                            Basic Plot: {clean_summary}
                            Deep Lore Notes (from Fandom): {fandom_lore if fandom_lore else "None found."}

                            RULES:
                            1. Combine the basic plot with the Deep Lore notes for a high-detail recap.
                            2. Mention subplots, character drama, and iconic quotes if available.
                            3. Use a friendly, conversational tone. No bolding.
                            4. End with one interesting trivia facts.
                            5. No spoilers for future episodes.
                            
                            Structure your response naturally, with this flow:
                            - A informative opening acknowledging the episode title and where we are in the season.
                            - A setup of where the main characters are at the start of the episode.
                            - The main plot points or conflict (use a detailed bulleted list with dashes). CRITICAL: Use your own internal knowledge to fill in any major subplots, romantic developments, or notable guest characters that are missing from the raw data.        - How the episode ends. where do the characters end up?
                            - A quick piece of trivia about the episode, guest stars, or how it ties into the larger season arc.
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
                            prompt = f"Summarize story arcs for {selected_label} Season {s_val}. Context: {full_text[:3500]}. RULES: Friendly tone, no bolding, focus on growth. End with a BTS fact."
                            if target.get('image'): st.image(target['image']['medium'])
                        else:
                            st.error("Season not found.")
                            st.stop()

                    # --- AI CALL ---
                    try:
                        client = genai.Client(api_key=GEMINI_KEY)
                        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(res.text)
                    except Exception:
                        groq_client = Groq(api_key=GROQ_KEY)
                        chat = groq_client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.write(chat.choices[0].message.content)
                       
                    # --- DEBUG SECTION ---
                    with st.expander("🛠️ System Debug Log"):
                        st.write(f"**Target Fandom URL:** {st.session_state.debug_url}")
                        st.write("**Data Found:**" if fandom_lore else "**Fandom Data:** Not Found (Using AI internal knowledge only)")
                        
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Search a show to begin!")


