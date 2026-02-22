# --- THE ALL-IN-ONE GEMINI HISTORIAN ---
@st.cache_data(show_spinner=False)
def generate_ai_summary(issue_data, series_name, issue_num):
    chars = ", ".join([c['name'] for c in (issue_data.get('character_credits') or [])])
    creators = ", ".join([p['name'] for p in (issue_data.get('person_credits') or [])])
    plot = str(issue_data.get('deck') or issue_data.get('description') or "")[:5000]
    
    needs_search = len(plot.strip()) < 50
    
    prompt = f"""
    You are an expert comic book historian. Write a highly detailed, 500+ word deep-dive summary into {series_name} #{issue_num} by {creators}.
    """
    
    if needs_search:
        prompt += f"""
        CRITICAL INSTRUCTION: The local database is empty. YOU MUST ACTIVELY USE YOUR GOOGLE SEARCH TOOL to find the exact plot for "{series_name} issue {issue_num}".
        Do not make an educated guess. Do not apologize. 
        FILTERING RULE: Ensure you are ONLY summarizing the exact events of issue #{issue_num}. Do not summarize the entire story arc or previous issues.
        """
    else:
        prompt += f"""
        Use the "Plot Snippet" below as your absolute source of truth. Do not guess the plot.
        Plot Snippet: {plot}
        """
        
    prompt += f"""
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
    """
    
    wait_time = 10 
    for attempt in range(3):
        try:
            from google.genai import types
            
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())] if needs_search else None
            )
                
            resp = ai_client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt,
                config=config
            )
            return resp.text
        except Exception as e:
            if "429" in str(e):
                # Using standard time.sleep without the UI toast
                import time
                time.sleep(wait_time)
                wait_time *= 2  
            else:
                break 
                
    if nvidia_client:
        try:
            comp = nvidia_client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct", 
                messages=[{"role": "user", "content": prompt}]
            )
            return comp.choices[0].message.content
        except Exception as nvidia_err:
             return f"NVIDIA Error: {nvidia_err}"
             
    return "AI Error: Both primary and backup APIs failed."
