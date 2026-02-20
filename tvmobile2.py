import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq

# --- CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_KEY") or os.environ.get("GEMINI_KEY")
GROQ_KEY = st.secrets.get("GROQ_KEY") or os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault", page_icon="📺")

# --- MOBILE STYLING ---
st.markdown("""
    <style>
    div.stButton > button:first-child {
        width: 100%;
        background-color: #007BFF;
        color: white;
        border-radius: 10px;
        height: 3.5em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📺 TV Vault Pro")
st.write("Search any show for an AI-generated recap.")

# --- APP LOGIC ---
query = st.text_input("Search for a TV Show", placeholder="e.g. Friends")

if query:
    try:
        # 1. Search for Show
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        
        if resp:
            # Safely handle missing years to avoid 'NoneType' errors
            show_options = {}
            for i in resp:
                show_data = i['show']
                name = show_data['name']
                premiered = show_data.get('premiered')
                year = premiered.split('-')[0] if premiered else "????"
                label = f"{name} ({year})"
                show_options[label] = show_data['id']
                
            selected_label = st.selectbox("Select Show", options=list(show_options.keys()))
            show_id = show_options[selected_label]
            
            # 2. Season/Episode Input (These create s_val and ep_val)
            col1, col2 = st.columns(2)
            with col1:
                s_val = st.number_input("Season", min_value=1, value=1)
            with col2:
                ep_val = st.number_input("Episode", min_value=1, value=1)

            if st.button("Generate Recap"):
                with st.spinner("AI is analyzing the episode..."):
                    
                    # 3. Fetch Episode Data (Using s_val and ep_val)
                    ep_url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                    ep_resp = requests.get(ep_url)
                    
                    if ep_resp.status_code == 200:
                        data = ep_resp.json()
                        
                        # Display Image
                        if data.get('image'):
                            st.image(data['image']['medium'], use_container_width=True)
                        
                        # Clean Summary & Guests
                        clean_summary = re.sub('<[^<]+>', '', data.get('summary', ''))
                        guest_list = data.get('_embedded', {}).get('guestcast', [])
                        # This ensures the AI knows about guest characters like Paolo
                        guest_str = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "No major guests."

                        # --- THE PROMPT (Using s_val and ep_val) ---
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

                        # --- AI EXECUTION ---
                        try:
                            # Gemini Attempt
                            client = genai.Client(api_key=GEMINI_KEY)
                            ai_result = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                            st.write(ai_result.text)
                            st.caption("Generated by Gemini 2.0")
                        except Exception:
                            # Groq Fallback
                            groq_client = Groq(api_key=GROQ_KEY)
                            chat = groq_client.chat.completions.create(
                                messages=[{"role": "user", "content": prompt}],
                                model="llama-3.3-70b-versatile",
                            )
                            st.write(chat.choices[0].message.content)
                            st.caption("Generated by Groq Fallback")
                    else:
                        st.error(f"Could not find S{s_val} E{ep_val} for this show.")
        else:
            st.warning("No shows found.")
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Search a show to begin!")