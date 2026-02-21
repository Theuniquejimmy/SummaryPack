import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq

# --- CONFIGURATION ---
# Pulls keys from Streamlit Secrets (Cloud) or Environment Variables (Local)
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺")

# --- MOBILE STYLING ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #007BFF;
        color: white;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📺 TV Vault Pro")

# --- MODE SELECTION ---
app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)

# --- SEARCH ---
query = st.text_input("Search for a show", placeholder="e.g. Buffy the Vampire Slayer")

if query:
    try:
        # 1. Show Search
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        
        if resp:
            show_options = {}
            for i in resp:
                s_data = i.get('show', {})
                if not s_data:
                    continue
                
                # --- THE FIX: Bulletproof date handling ---
                p_date = s_data.get('premiered')
                # Explicitly check if it's a string before splitting
                if isinstance(p_date, str) and '-' in p_date:
                    year = p_date.split('-')[0]
                else:
                    year = "????"
                
                name = s_data.get('name', 'Unknown Title')
                show_options[f"{name} ({year})"] = s_data.get('id')
            
            if not show_options:
                st.warning("Found data, but no valid show titles. Try tweaking your search.")
                st.stop()
                
            selected_show = st.selectbox("Select Show", options=list(show_options.keys()))
            show_id = show_options[selected_show]
            
            # --- INPUTS ---
            if app_mode == "Single Episode":
                col1, col2 = st.columns(2)
                with col1:
                    s_val = st.number_input("Season", min_value=1, value=1, key="s_input")
                with col2:
                    ep_val = st.number_input("Episode", min_value=1, value=1, key="e_input")
            else:
                # Season mode only needs the season number
                s_val = st.number_input("Summarize Season", min_value=1, value=1, key="s_season_input")
                ep_val = 1 # Safety placeholder

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("AI is analyzing the vault..."):
                    
                    if app_mode == "Single Episode":
                        # --- EPISODE LOGIC ---
                        url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(url).json()
                        
                        if "name" in data:
                            if data.get('image') and data['image'].get('medium'): 
                                st.image(data['image']['medium'], use_container_width=True)
                            
                            # --- SAFETY FIX: Handle 'None' summaries ---
                            raw_summary = data.get('summary') or "No summary available."
                            clean_summary = re.sub('<[^<]+>', '', raw_summary)
                            
                            guest_list = data.get('_embedded', {}).get('guestcast', [])
                            guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "No major guests."

                            # THE PROMPT 
                            prompt = f"""
                            Recap Season {s_val}, Episode {ep_val} of {selected_show} as if you are a tv specialist.
                            Title: {data['name']}
                            Guests: {guests}
                            Summary: {clean_summary}

                            CRITICAL RULES:
                            1. NO SPOILERS for future episodes, but can spoil current episode.
                            2. Write in a conversational, informative tone.
                            3. Break the text into short, digestible paragraphs. 
                            4. Use standard dashes (-) for bullet points. 
                            5. Do NOT use Markdown formatting (like ** or #) since this will be displayed in a plain text window.
                            6. Write a high-detail, conversational recap.
                            7. Use the lore notes to mention subplots or specific character beats.
                            
                            Structure your response naturally, with this flow:
                            - A informative opening acknowledging the episode title and where we are in the season.
                            - A setup of where the main characters are at the start of the episode.
                            - The main plot points or conflict (use a detailed bulleted list with dashes). CRITICAL: Use your own internal knowledge to fill in any major subplots, romantic developments, or notable guest characters that are missing from the raw data.
                            - How the episode ends. where do the characters end up?
                            - List all main plot points of episode so if I havent seen it it'll fill me in.
                            - A quick piece of trivia about the episode, guest stars
                            - How it ties into the larger season arc.
                            """
                        else:
                            st.error(f"Episode S{s_val}E{ep_val} not found.")
                            st.stop()
                    
                    else:
                        # --- SEASON LOGIC ---
                        seasons = requests.get(f"https://api.tvmaze.com/shows/{show_id}/seasons").json()
                        target = next((s for s in seasons if s.get('number') == s_val), None)
                        
                        if target:
                            if target.get('image') and target['image'].get('medium'): 
                                st.image(target['image']['medium'], use_container_width=True)
                            
                            ep_list = requests.get(f"https://api.tvmaze.com/seasons/{target['id']}/episodes").json()
                            
                            # --- SAFETY FIX: Handle 'None' summaries in the loop ---
                            full_text = " ".join([re.sub('<[^<]+>', '', e.get('summary') or "") for e in ep_list])
                            
                            # THE PROMPT
                            prompt = f"""
                            Act as an authentic, adaptive AI collaborator with a touch of wit. Provide a thorough, insightful recap of {selected_show} Season {s_val} as if i'v never seen it and need to prepare myself to watch the next season.
                            Episode Context: {full_text[:3500]}
                            
                            Your response must follow these structural guidelines:
                            Tone: Balance empathy with candor. Be a supportive, grounded guide who uses clear, concise prose with a hint of humor.

                            RULES:
                            1. Identify major story arcs and character growth over the year.
                            2. Friendly, conversational tone.
                            3. NO MARKDOWN (no bolding or hashtags). Use dashes (-) for bullets.
                            4. Do not spoil the next season's cliffhanger.
                            5. Identify at least TWO important plot point for every episode of the season so, if season has 25 epsiodes 50 plot points at least and write them with great detail that if you havn't seen the episode you'd know the main plot. Cite each with episode tag its from "S*E*" and list them in order of episode.
                            6. End with a thourough summary of the season hitting the most important plot points. 
                            7. What I need to know for next season.
                            8. Don't skip episodes when giving summaries.
                            """
                        else:
                            st.error(f"Season {s_val} not found.")
                            st.stop()

                    # --- AI CALL (Gemini with Groq Fallback) ---
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

        else:
            st.warning("No shows found.")
    except Exception as e:
        st.error(f"App Error: {e}")
else:
    st.info("Enter a show title to begin.")
