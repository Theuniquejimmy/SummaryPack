import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault Pro", page_icon="📺")

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

app_mode = st.radio("Recap Mode:", ["Single Episode", "Full Season"], horizontal=True)

query = st.text_input("Search for a show", placeholder="e.g. Buffy the Vampire Slayer")

if query:
    try:
        # 1. Show Search
        url = f"https://api.tvmaze.com/search/shows?q={query}"
        resp = requests.get(url).json()
        
        if resp:
            show_options = {}
            for item in resp:
                s_data = item.get('show', {})
                if not s_data:
                    continue
                
                # NO SPLIT COMMAND USED HERE
                p_date = s_data.get('premiered', '')
                # If p_date is valid and has at least 4 characters, take the first 4 (the year)
                year = p_date[:4] if (p_date and len(p_date) >= 4) else "????"
                
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
                    s_val = st.number_input("Season", min_value=1, value=1)
                with col2:
                    ep_val = st.number_input("Episode", min_value=1, value=1)
            else:
                s_val = st.number_input("Summarize Season", min_value=1, value=1)
                ep_val = 1 

            if st.button(f"Generate {app_mode} Recap"):
                with st.spinner("AI is analyzing the vault..."):
                    
                    if app_mode == "Single Episode":
                        ep_url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                        data = requests.get(ep_url).json()
                        
                        # Fix for TVMaze returning a 404 Not Found JSON object
                        if data.get("status") == 404 or "id" not in data:
                            st.error(f"Episode S{s_val}E{ep_val} not found in the TVMaze database.")
                            st.stop()
                            
                        if data.get('image') and data['image'].get('medium'): 
                            st.image(data['image']['medium'], use_container_width=True)
                        
                        raw_summary = data.get('summary') or "No summary available."
                        clean_summary = re.sub('<[^<]+>', '', raw_summary)
                        
                        guest_list = data.get('_embedded', {}).get('guestcast', [])
                        guests = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "No major guests."

                        prompt = f"""
                        Recap Season {s_val}, Episode {ep_val} of {selected_show} as if you are a tv specialist.
                        Title: {data.get('name', 'Unknown')}
                        Guests: {guests}
                        Summary: {clean_summary}

                        CRITICAL RULES:
                        1. NO SPOILERS for future episodes, but can spoil current episode.
                        2. Write in a conversational, informative tone.
                        3. Break the text into short, digestible paragraphs. 
                        4. Use standard dashes (-) for bullet points. 
                        5. Do NOT use Markdown formatting (like ** or #).
                        6. Write a high-detail, conversational recap.
                        7. Use the lore notes to mention subplots or specific character beats.
                        
                        Structure your response naturally, with this flow:
                        - A informative opening acknowledging the episode title and where we are in the season.
                        - A setup of where the main characters are at the start of the episode.
                        - The main plot points or conflict. Fill in any major subplots.
                        - How the episode ends.
                        - List all main plot points of episode so if I havent seen it it'll fill me in.
                        - A quick piece of trivia about the episode, guest stars
                        - How it ties into the larger season arc.
                        """
                    
                    else:
                        seasons_url = f"https://api.tvmaze.com/shows/{show_id}/seasons"
                        seasons = requests.get(seasons_url).json()
                        target = next((s for s in seasons if s.get('number') == s_val), None)
                        
                        if not target:
                            st.error(f"Season {s_val} not found.")
                            st.stop()
                            
                        if target.get('image') and target['image'].get('medium'): 
                            st.image(target['image']['medium'], use_container_width=True)
                        
                        ep_list_url = f"https://api.tvmaze.com/seasons/{target['id']}/episodes"
                        ep_list = requests.get(ep_list_url).json()
                        
                        full_text = " ".join([re.sub('<[^<]+>', '', e.get('summary') or "") for e in ep_list])
                        
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
                        5. Identify at least TWO important plot point for every episode of the season. Cite each with episode tag its from "S*E*" and list them in order of episode.
                        6. End with a thourough summary of the season hitting the most important plot points. 
                        7. What I need to know for next season.
                        8. Don't skip episodes when giving summaries.
                        """

                    # --- AI CALL (Gemini with Groq Fallback) ---
                    try:
                        client = genai.Client(api_key=GEMINI_KEY)
                        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                        st.write(res.text)
                    except Exception as ai_err:
                        st.warning(f"Gemini failed ({ai_err}), falling back to Groq...")
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
        st.info("If you see an error here, the API data might be formatted unexpectedly.")
else:
    st.info("Enter a show title to begin.")
