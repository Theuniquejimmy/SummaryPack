import streamlit as st
import requests
import re
import os
from google import genai
from groq import Groq

# --- CONFIGURATION ---
# These pull from your computer's environment variables
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GROQ_KEY = os.environ.get("GROQ_KEY")

st.set_page_config(page_title="TV Vault", page_icon="📺", layout="centered")

# --- MOBILE OPTIMIZATION (CSS) ---
st.markdown("""
    <style>
    /* Makes the button big and thumb-friendly on mobile */
    div.stButton > button:first-child {
        width: 100%;
        background-color: #007BFF;
        color: white;
        font-size: 18px;
        font-weight: bold;
        border-radius: 12px;
        height: 3.5em;
        border: none;
    }
    /* Centers the images */
    .stImage > img {
        border-radius: 15px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📺 TV Vault Pro")
st.write("Find any episode recap with AI-powered trivia.")

# --- THE APP LOGIC ---
query = st.text_input("Search for a TV Show", placeholder="e.g. Friends or The Bear")

if query:
    try:
        # Search TVmaze for the show
        search_url = f"https://api.tvmaze.com/search/shows?q={query}"
        resp = requests.get(search_url).json()
        
        if resp:
            # Build a dictionary of { "Show Name (Year)": ID }
            show_options = {}
            for item in resp:
                name = item['show']['name']
                year = item['show'].get('premiered', '????').split('-')[0]
                label = f"{name} ({year})"
                show_options[label] = item['show']['id']
            
            selected_label = st.selectbox("Which show did you mean?", options=list(show_options.keys()))
            show_id = show_options[selected_label]
            
            # Side-by-side inputs for Season and Episode
            col1, col2 = st.columns(2)
            with col1:
                s_val = st.number_input("Season", min_value=1, step=1, value=1)
            with col2:
                ep_val = st.number_input("Episode", min_value=1, step=1, value=1)

            if st.button("Get Episode Recap"):
                with st.spinner("Talking to the AI..."):
                    
                    # Fetch episode data + guest cast (for Paolo and others!)
                    ep_url = f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s_val}&number={ep_val}&embed=guestcast"
                    ep_resp = requests.get(ep_url)
                    
                    if ep_resp.status_code == 200:
                        data = ep_resp.json()
                        
                        # Show episode title and image
                        st.divider()
                        st.header(f"\"{data.get('name', 'Untitled')}\"")
                        
                        if data.get('image'):
                            st.image(data['image']['medium'], use_container_width=True)
                        
                        # Clean up the summary and guests
                        raw_summary = data.get('summary', 'No summary available.')
                        clean_summary = re.sub('<[^<]+>', '', raw_summary)
                        
                        guest_list = data.get('_embedded', {}).get('guestcast', [])
                        guest_str = ", ".join([f"{g['character']['name']} ({g['person']['name']})" for g in guest_list]) or "No major guests listed."

                        # --- THE PROMPT (Using s_val and ep_val) ---
                        prompt = f"""
                        Act as a TV historian. Give me a detailed recap of Season {s_val}, Episode {ep_val} of {selected_label}.
                        
                        EPISODE DATA:
                        - Title: {data.get('name')}
                        - Notable Guests: {guest_str}
                        - Basic Plot: {clean_summary}

                        INSTRUCTIONS:
                        1. Use your internal knowledge to flesh out the subplots, romantic arcs, and character drama.
                        2. Write in a friendly, conversational tone.
                        3. Use short paragraphs and simple dashes (-) for lists.
                        4. DO NOT use markdown bolding or hashtags.
                        5. DO NOT spoil the final scene or major twists.
                        6. End with one interesting "Did you know?" trivia fact about this episode.
                        """

                        # --- AI EXECUTION ---
                        try:
                            # Try Gemini 2.0 first
                            client = genai.Client(api_key=GEMINI_KEY)
                            ai_result = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                            st.write(ai_result.text)
                            st.caption("Recap provided by Gemini 2.0 Flash")
                        except Exception:
                            # Fallback to Groq Llama 3
                            groq_client = Groq(api_key=GROQ_KEY)
                            chat = groq_client.chat.completions.create(
                                messages=[{"role": "user", "content": prompt}],
                                model="llama-3.3-70b-versatile",
                            )
                            st.write(chat.choices[0].message.content)
                            st.caption("Gemini busy; fallback recap provided by Llama 3.3 (Groq)")
                    else:
                        st.error(f"Sorry! I couldn't find Season {s_val}, Episode {ep_val} for this show.")
        else:
            st.warning("No shows found. Try a different title!")
    except Exception as e:
        st.error(f"App Error: {e}")

else:
    st.info("Search for a show above to begin.")