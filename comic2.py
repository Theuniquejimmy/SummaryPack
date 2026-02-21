def generate_ai_summary(issue_data, series_name, issue_num):
    char_list = issue_data.get('character_credits') or []
    character_names = ", ".join([char['name'] for char in char_list])
    
    # We increased the character limit here to 5000 to give the AI more to work with
    raw_desc = issue_data.get('deck') or issue_data.get('description') or "No description provided."
    safe_desc = str(raw_desc)[:5000] 
    
    # Updated Prompt: Added "Deep Dive" instructions
    prompt = f"""
    Act as an expert comic book historian giving a deep-dive, comprehensive summary of {series_name} #{issue_num}. 
    
    Structure your response with these specific sections:
    1. CONTEXT: Where does this fit in the character's history or current story arc?
    2. DETAILED PLOT: Give a thorough, multi-paragraph breakdown of the events in this issue.
    3. KEY MOMENTS: List the most important character beats or reveals using dashes (-).
    4. SIGNIFICANCE: Why does this issue matter? Is it a first appearance, a major death, or a famous creative team-up?
    
    RULES: 
    - Write at least 4-5 substantial paragraphs.
    - DO NOT use spoilers for issues AFTER this one.
    - Use a professional yet enthusiastic tone.
    - Do NOT use Markdown formatting (like ** or #).
    
    DATA:
    Series: {series_name}
    Issue: {issue_num}
    Title: {issue_data.get('name', 'Unknown')}
    Plot Snippet: {safe_desc}
    Characters: {character_names}
    """
    
    try:
        # Gemini-2.0-Flash is great for long-form generation
        response = ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return f"**[Gemini Deep Dive]**\n\n{response.text}"
    
    except Exception:
        if groq_client:
            st.caption("ℹ️ *Gemini busy; using Groq for Deep Dive*")
            # We use the same detailed prompt for Groq as a backup
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
            )
            return f"**[Groq Deep Dive]**\n\n{completion.choices[0].message.content}"
        return "AI failed to generate a deep dive summary."
