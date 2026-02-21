def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "No data")[:5000]
    
    prompt = f"""
    Act as a passionate, encyclopedic comic book historian. Your goal is to write a highly detailed, comprehensive deep-dive into {series_name} #{issue_num}. 
    
    The raw data below might be brief, but you MUST use your extensive internal knowledge of comic lore to expand on it. Structure your response using Markdown headings for these exact sections:
    
    ### 🌍 Context & Background
    Explain what was happening in the comic universe and the character's life leading up to this issue. Who is the creative team, and what era/run is this?
    
    ### 📖 Detailed Plot Summary
    Provide an exhaustive, multi-paragraph recounting of the issue's events. Do not just give a blurb; narrate the key actions, conflicts, and character dynamics.
    
    ### 💥 Key Moments
    Use bullet points to list the most iconic panels, character beats, or reveals in this specific issue.
    
    ### 🏛️ Legacy & Significance
    Why does this issue matter? Discuss its impact, first appearances, or how it sets up the future (without spoiling specific future plotlines).
    
    RULES:
    - Your output MUST be a substantial, long-form read (at least 500-800 words).
    - Be enthusiastic, professional, and authoritative.
    - Do NOT be constrained by the briefness of the "Plot Snippet".
    
    RAW DATA:
    Series: {series_name}
    Issue: {issue_num}
    Plot Snippet: {plot}
    Characters Involved: {chars}
    """
    
    try:
        resp = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return resp.text
    except Exception:
        if nvidia_client:
            st.caption("ℹ️ *Using NVIDIA Backup*")
            comp = nvidia_client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct", 
                messages=[{"role": "user", "content": prompt}]
            )
            return comp.choices[0].message.content
        return "AI Error"
