import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺", layout="centered")

# --- MOBILE CSS OPTIMIZATION ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #007BFF;
        color: white;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
        border: none;
    }
    .stSelectbox, .stNumberInput {
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📺 TV Vault Pro")

# --- MODE SELECTION ---
app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)

# --- SEARCH LOGIC ---
query = st.text_input("Search for a show", placeholder="e.g. Friends")

if query:
    try:
        # 1. Show Search
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        
        if resp:
            show_options = {}
            for i in resp:
                s_data = i['show']
                year = s_data.get('premiered', '????').split('-')[0] if s_data.get('premiered') else "????"
                show_options[f"{s_data['name']} ({year})"] = s_data['id']
                
            selected_show = st.selectbox("Select Show", options=list(show_options.keys()))
            show_id = show_options[selected_show]
            
            # 2. Input Layout
            if app_mode == "Single Episode":
                col1, col2 = st.columns(2)
                with col1: s_val = st.number_input("Season", min_value=1, value=1)
                with col2: ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Summarize Season", min_value=1, value=1)

            # 3. Execution
            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("AI is analyzing the vault..."):
                    
                    if app_mode == "Single Episode":
                        # --- EPISODE PROMPT LOGIC ---
                        url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        
                        if "name" in data:
                            if data.get('image'): st.image(data['image']['medium'], use_container_width=True)
                            
                            # Prepare Context
                            clean_summary = re.sub('<[^<]+>', '', data.get('summary', ''))
                            guest_data = data.get('_embedded', {}).get('guestcast', [])
                            guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_data]) or "No major guests listed."

                            # THE PROMPT
                            prompt = f"""
                            Act exactly like a helpful, conversational AI tv specialist answering a user who just asked: "What is Season {season_num}, Episode {episode_num} of {show_name} about?"
        
        Using the raw data provided and your own extensive knowledge of television, give a natural, engaging, and easy-to-read recap. 
        
        CRITICAL RULES:
        1. NO SPOILERS for future episodes, but can spoil current episode.
        2. Write in a conversational, informative tone.
        3. Break the text into short, digestible paragraphs. 
        4. Use standard dashes (-) for bullet points. 
        5. Do NOT use Markdown formatting (like ** or #) since this will be displayed in a plain text window. 
        
        RAW DATA:
        Show: {show_name}
        Season: {season_num}
        Episode: {episode_num}
        Episode Title: {ep_title}
        Guest Stars: {guest_stars}  <-- NEW: The AI now knows exactly who is in the episode!
        Plot Snippet: {safe_desc}
        
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
                        # --- SEASON PROMPT LOGIC ---
                        # Step A: Get the specific Season ID
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_id}/seasons").json()
                        target_season = next((s for s in seasons if s['number'] == s_val), None)
                        
                        if target_season:
                            # Step B: Get all episodes for that season
                            ep_list = requests.get(f"https://api.tvmaze.com/seasons/{target_season['id']}/episodes").json()
                            full_context = " ".join([re.sub('<[^<]+>', '', e.get('summary', '')) for e in ep_list])
                            
                            if target_season.get('image'): st.image(target_season['image']['medium'], use_container_width=True)

                            # THE PROMPT
                            prompt = f"""
                            Write a comprehensive season recap for {selected_show} Season {s_val} based on these summaries:
                            {full_context[:4000]}

                            CRITICAL RULES:
                            1. Identify the major story arcs and how the main characters evolved over the year.
                            2. Focus on narrative flow rather than a list of episodes.
                            3. Use a friendly, conversational tone.
                            4. NO MARKDOWN (no bolding or hashtags). Use dashes (-) for bullets.
                            5. Do not spoil the cliffhanger for the next season.
                            6. End with one interesting "behind-the-scenes" fact about this season.
                            """
                        else:
                            st.error(f"Season {s_val} not found.")
                            st.stop()

                    # --- AI CALL (With Fallback) ---
                    try:
                        # Try Gemini First
                        client = genai.Client(api_key=GEMINI_KEY)
                        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(response.text)
                        st.caption("Recap by Gemini 2.0")
                    except Exception:
                        # Fallback to Groq
                        groq_client = Groq(api_key=GROQ_KEY)
                        chat = groq_client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.write(chat.choices[0].message.content)
                        st.caption("Recap by Groq (Llama 3.3)")
                        
        else:
            st.warning("No shows found.")
    except Exception as e:
        st.error(f"App Error: {e}")
else:
    st.info("Enter a show title to begin.")