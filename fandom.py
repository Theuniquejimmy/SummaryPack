import streamlit as st
import requests
import urllib.parse
from bs4 import BeautifulSoup
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

# --- THE 2-STEP API CRAWLER ---
def get_raw_lore(wiki_slug, ep_title):
    api_url = f"https://{wiki_slug.lower()}.fandom.com/api.php"
    
    # STEP 1: Search the wiki database to find the exact, case-sensitive page title
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": ep_title,
        "format": "json"
    }
    
    try:
        search_res = requests.get(api_url, params=search_params, timeout=10).json()
        search_results = search_res.get("query", {}).get("search", [])
        
        if not search_results:
            return None, None
            
        # Get the exact title from the best match
        exact_title = search_results[0]["title"]
        page_url = f"https://{wiki_slug.lower()}.fandom.com/wiki/{urllib.parse.quote(exact_title.replace(' ', '_'))}"
        
        # STEP 2: Ask the API for the pure HTML text of that specific page
        parse_params = {
            "action": "parse",
            "page": exact_title,
            "prop": "text",
            "format": "json",
            "redirects": "1"
        }
        
        parse_res = requests.get(api_url, params=parse_params, timeout=10).json()
        html_text = parse_res.get("parse", {}).get("text", {}).get("*", "")
        
        if not html_text:
            return None, None
            
        # STEP 3: Parse the clean HTML (This preserves lists, but ignores sidebars!)
        soup = BeautifulSoup(html_text, 'html.parser')
        
        start_node = None
        story_keywords = ['plot', 'synopsis', 'summary', 'episode_summary']
        
        # Find the starting header
        for header in soup.find_all(['h2', 'h3']):
            h_text = header.get_text().lower()
            h_id = header.get('id', '').lower()
            inner_span = header.find('span')
            span_id = inner_span.get('id', '').lower() if inner_span else ""
            
            if any(key in h_text or key in h_id or key in span_id for key in story_keywords):
                start_node = header
                break
                
        if start_node:
            content = []
            # Grab everything until the cast list
            for sibling in start_node.find_next_siblings():
                if sibling.name in ['h2', 'h3']:
                    stop_words = ['cast', 'trivia', 'gallery', 'references', 'production', 'credits', 'quotes', 'videos']
                    if any(stop in sibling.get_text().lower() for stop in stop_words):
                        break
                
                # Crucial: We grab <p> AND <ul>/<ol> so the bullet points aren't lost
                if sibling.name in ['p', 'ul', 'ol']:
                    txt = sibling.get_text().strip()
                    if txt:
                        content.append(txt)
            
            if content:
                return "\n\n".join(content), page_url
                
    except Exception as e:
        pass
        
    return None, None

# --- UI ---
st.title("📖 TV Vault Reader")
st.caption("Powered by 2-Step MediaWiki API")

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
                            st.caption(f"Source: [Fandom Wiki]({found_url})")
                        else:
                            st.error(f"Text not found. Ensure the episode exists on {wiki_slug}.fandom.com.")
                    else:
                        st.error("Episode name not found in the database.")
                else:
                    st.error("Could not locate this specific episode number.")
    except Exception as e:
        st.error(f"Error: {e}")
