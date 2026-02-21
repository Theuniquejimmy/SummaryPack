# --- AGENT 2: THE HISTORIAN ---
@st.cache_data(show_spinner=False)  # <--- NEW: This line gives your app a permanent memory!
def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    
    if len(plot.strip()) < 50:
        plot = get_plot_from_search(series_name, issue_num, creators)
    
    prompt = f"""
    You are an expert comic book historian. Write a highly detailed, 500+ word deep-dive summary into {series_name} #{issue_num} by {creators}.
    
    Use the "Plot Snippet" below as your absolute source of truth for what happens in this issue. Do not guess the plot if data is provided.
    
    Structure your response using Markdown headings for these exact sections:
    ### 🌍 Context & Background
    ### 📖 Detailed Plot Summary
    ### 💥 Key Moments
    ### 🏛️ Legacy & Significance
    
    RAW DATA:
    Series: {series_name}
    Issue: {issue_num}
    Creators: {creators}
    Characters: {chars}
    Plot Snippet: {plot}
    """
    
    # NEW: Exponential Backoff (10s, then 20s, then 40s)
    wait_time = 10 
    for attempt in range(3):
        try:
            resp = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return resp.text
        except Exception as e:
            if "429" in str(e):
                st.toast(f"⏳ API cooling down. Waiting {wait_time} seconds... (Attempt {attempt+1}/3)")
                time.sleep(wait_time)
                wait_time *= 2  # Doubles the wait time for the next attempt
            else:
                break 
                
    if nvidia_client:
        st.caption("ℹ️ *Gemini unavailable. Using NVIDIA Backup...*")
        try:
            comp = nvidia_client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct", 
                messages=[{"role": "user", "content": prompt}]
            )
            return comp.choices[0].message.content
        except Exception as nvidia_err:
             return f"NVIDIA Error: {nvidia_err}"
             
    return "AI Error: Both primary and backup APIs failed."
