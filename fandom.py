import streamlit as st
import requests
import urllib.parse
from gtts import gTTS
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="TV Vault Reader", page_icon="📖", layout="centered")

WIKI_ALIASES = {
    "Invincible": "amazon-invincible",
    "The Incredible Hulk": "marvelcinematicuniverse",
    "X-Men '97": "xmen97",
    "The Wheel of Time": "wot"
}

st.markdown("""
    <style>
    .lore-box {
        font-size: 1.15rem;
        line-height: 1.8;
        background-color: #1a1a1a;
        padding: 25px;
        border-radius: 15px;
        color: #f1f1f1;
        border-left: 5px solid #3b82f6;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 12px;
        height: 3.5em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- THE MEDIAWIKI API EXTRACTOR ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    
    # We don't need underscores for the API; natural spaces work perfectly!
    variations = [
        ep_title,
        f"{ep_title} (episode)",
        f"{ep_title} (TV episode)"
    ]
    
    for v in variations:
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1", # This tells the server to strip all HTML automatically
            "titles": v,
            "format": "json",
            "redirects": "1"    # Automatically follow Fandom redirects
        }
        
        try:
            res = requests.get(api_url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                pages = data.get("query", {}).get("pages", {})
                
                for page_id, page_data in pages.items():
                    # If page_id is "-1", the page doesn't exist
                    if page_id != "-1" and "extract" in page_data:
                        raw_text = page_data["extract"]
                        
                        # Process the raw text document
                        lines = raw_text.split('\n')
                        story_content = []
                        
                        for line in lines:
                            # The API formats headers as "== Header Name =="
                            if line.startswith("== ") and line.endswith(" =="):
                                header_name = line.lower()
                                stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos', 'notes']
                                if any(stop in header_name for stop in stop_words):
                                    break # We hit the end of the story
                                
                                # Format subheaders nicely for our display
                                clean_header = line.replace("=", "").strip()
                                story_content.append(f"### {clean_header}")
                            elif line.strip():
                                story_content.append(line.strip())
                        
                        if story_content:
                            # Rebuild the final display URL
                            final_title = page_data["title"].replace(" ", "_")
                            page_url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{urllib.parse.quote(final_title)}"
                            return "\n\n".join(story_content), page_url
        except Exception:
            continue
            
    return None, None

# --- UI ---
st.title("📖 TV Vault Reader")
st.caption("Powered by MediaWiki API")

query = st.text_input("Search for a show:", placeholder="e.g. Invincible")

if query:
    try:
        resp = requests.get(f"https://api.tvmaze.com/search/shows?q={query}").json()
        if resp:
            show_options = {f"{i['show']['name']} ({i['show'].get('premiered','?').split('-')[0]})": i['show'] for i in resp}
            label = st.selectbox("Select Result:", options=list(show_options.keys()))
            show_data = show_options[label]
            
            wiki_slug = WIKI_ALIASES.get(show_data['name'], show_data['name'].replace(" ", "").lower())
            
            c1, c2 = st.columns(2)
            with c1: s_val = st.number_input("Season", min_value=1, value=1)
            with c2: ep_val = st.number_input("Episode", min_value=1, value=1)

            if st.button("🔓 Extract Full Lore"):
                api_url = f"https://api.tvmaze.com/shows/{show_data['id']}/episodebynumber?season={s_val}&number={ep_val}"
                api_res = requests.get(api_url)
                
                if api_res.status_code == 200:
                    api_data = api_res.json()
                    
                    if "name" in api_data:
                        raw_text, found_url = get_raw_lore(wiki_slug, api_data['name'])
                        
                        if raw_text:
                            st.subheader(api_data['name'])
                            if api_data.get('image'): st.image(api_data['image']['medium'])
                            
                            if st.button("🔊 Play Audio"):
                                with st.spinner("Synthesizing audio..."):
                                    tts = gTTS(text=raw_text, lang='en')
                                    tts.save("lore.mp3")
                                    with open("lore.mp3", "rb") as f:
                                        b64 = base64.b64encode(f.read()).decode()
                                        st.markdown(f'<audio controls autoplay style="width:100%"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

                            st.markdown(f'<div class="lore-box">{raw_text}</div>', unsafe_allow_html=True)
                            st.caption(f"Source: [Direct API Link]({found_url})")
                        else:
                            st.error(f"Text not found. Fandom's database returned empty for {wiki_slug}.")
                    else:
                        st.error("Episode name not found in the database.")
                else:
                    st.error("Could not locate this specific episode number.")
    except Exception as e:
        st.error(f"Error: {e}")
