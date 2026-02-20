import requests
import os
import io
import threading
import customtkinter as ctk
from PIL import Image
from google import genai 

# --- CONFIGURATION ---
COMIC_VINE_KEY = os.environ.get("COMIC_VINE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not COMIC_VINE_KEY or not GEMINI_KEY:
    print("Error: Missing API keys in environment variables!")
    exit()

ai_client = genai.Client(api_key=GEMINI_KEY)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ComicSummaryApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Comic Vault Analyzer")
        self.geometry("1000x750")
        
        self.volume_map = {}
        self.build_ui()

    def build_ui(self):
        # --- LEFT PANEL: Controls & Image ---
        self.left_frame = ctk.CTkFrame(self, width=280)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)

        ctk.CTkLabel(self.left_frame, text="1. Search Series", font=("Arial", 16, "bold")).pack(pady=(10, 5))
        self.series_entry = ctk.CTkEntry(self.left_frame, placeholder_text="e.g., Daredevil")
        self.series_entry.pack(pady=5, padx=10, fill="x")
        
        self.search_btn = ctk.CTkButton(self.left_frame, text="Find Volumes", command=self.thread_search_volumes)
        self.search_btn.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(self.left_frame, text="2. Select Year", font=("Arial", 16, "bold")).pack(pady=(20, 5))
        self.volume_dropdown = ctk.CTkComboBox(self.left_frame, values=["Search series first..."])
        self.volume_dropdown.pack(pady=5, padx=10, fill="x")

        ctk.CTkLabel(self.left_frame, text="3. Issue Number", font=("Arial", 16, "bold")).pack(pady=(20, 5))
        
        # --- NEW: Horizontal Frame for Arrow Buttons ---
        self.issue_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.issue_frame.pack(pady=5, padx=10, fill="x")
        
        self.prev_btn = ctk.CTkButton(self.issue_frame, text="<", width=30, command=self.prev_issue)
        self.prev_btn.pack(side="left", padx=(0, 5))
        
        self.issue_entry = ctk.CTkEntry(self.issue_frame, placeholder_text="e.g., 1")
        self.issue_entry.pack(side="left", fill="x", expand=True)
        
        self.next_btn = ctk.CTkButton(self.issue_frame, text=">", width=30, command=self.next_issue)
        self.next_btn.pack(side="left", padx=(5, 0))

        self.analyze_btn = ctk.CTkButton(self.left_frame, text="Analyze Issue", command=self.thread_analyze_issue)
        self.analyze_btn.pack(pady=20, padx=10, fill="x")

        # Status Label
        self.status_label = ctk.CTkLabel(self.left_frame, text="Ready.", text_color="gray", wraplength=250)
        self.status_label.pack(pady=10)

        # Image Label
        self.cover_label = ctk.CTkLabel(self.left_frame, text="Cover Image", width=200, height=300)
        self.cover_label.pack(side="bottom", pady=20)

        # --- RIGHT PANEL: Massive Text Box ---
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)

        self.summary_box = ctk.CTkTextbox(self.right_frame, wrap="word", font=("Arial", 15))
        self.summary_box.pack(fill="both", expand=True, padx=10, pady=10)

    # --- NEW: Arrow Button Logic ---
    def prev_issue(self):
        current_val = self.issue_entry.get()
        try:
            num = int(current_val)
            if num > 1: # Let's prevent it from going to issue 0 or negative
                self.issue_entry.delete(0, "end")
                self.issue_entry.insert(0, str(num - 1))
                self.thread_analyze_issue() # Automatically analyze!
        except ValueError:
            pass # If the box is empty or has text in it, do nothing

    def next_issue(self):
        current_val = self.issue_entry.get()
        try:
            num = int(current_val)
            self.issue_entry.delete(0, "end")
            self.issue_entry.insert(0, str(num + 1))
            self.thread_analyze_issue() # Automatically analyze!
        except ValueError:
            pass

    # --- THREADING ---
    def thread_search_volumes(self):
        self.status_label.configure(text="Searching archives...")
        threading.Thread(target=self.fetch_volumes, daemon=True).start()

    def thread_analyze_issue(self):
        self.status_label.configure(text="Analyzing and generating...")
        threading.Thread(target=self.process_issue, daemon=True).start()

    # --- API CALLS ---
    def fetch_volumes(self):
        query = self.series_entry.get()
        if not query:
            self.status_label.configure(text="Please enter a series name.")
            return

        search_url = "https://comicvine.gamespot.com/api/search/"
        params = {
            "api_key": COMIC_VINE_KEY,
            "format": "json",
            "query": query,
            "resources": "volume",
            "limit": 20
        }
        headers = {"User-Agent": "ComicVaultUI/1.0"}
        
        try:
            response = requests.get(search_url, params=params, headers=headers).json()
            results = response.get('results', [])
            
            if not results:
                self.status_label.configure(text="No volumes found.")
                return

            def get_year(res):
                try:
                    return int(res.get('start_year'))
                except (TypeError, ValueError):
                    return 9999 
            
            results.sort(key=get_year)

            self.volume_map.clear()
            dropdown_values = []
            
            for res in results:
                title = res.get('name', 'Unknown')
                year = res.get('start_year', 'Unknown Year')
                display_name = f"{title} ({year})"
                
                self.volume_map[display_name] = res['id']
                dropdown_values.append(display_name)
            
            self.volume_dropdown.configure(values=dropdown_values)
            self.volume_dropdown.set(dropdown_values[0])
            self.status_label.configure(text="Volumes loaded & sorted!")

        except Exception as e:
            self.status_label.configure(text="Network Error.")

    def process_issue(self):
        selected_vol = self.volume_dropdown.get()
        issue_num = self.issue_entry.get()
        
        if selected_vol not in self.volume_map or not issue_num:
            self.status_label.configure(text="Please select a volume and issue.")
            return

        volume_id = self.volume_map[selected_vol]
        
        issue_url = "https://comicvine.gamespot.com/api/issues/"
        params = {
            "api_key": COMIC_VINE_KEY,
            "format": "json",
            "filter": f"volume:{volume_id},issue_number:{issue_num}",
            "field_list": "name,deck,description,character_credits,image"
        }
        headers = {"User-Agent": "ComicVaultUI/1.0"}
        
        try:
            data_resp = requests.get(issue_url, params=params, headers=headers).json()
            results = data_resp.get('results')
            
            if not results:
                self.status_label.configure(text="Issue not found in this volume.")
                return
                
            issue_data = results[0]

            # 1. Fetch and Display Image
            img_url = issue_data.get('image', {}).get('medium_url')
            if img_url:
                img_data = requests.get(img_url, headers=headers).content
                img = Image.open(io.BytesIO(img_data))
                
                img.thumbnail((200, 300))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                
                self.cover_label.configure(image=ctk_img, text="")
                self.cover_label.image = ctk_img

            # 2. Generate AI Summary 
            self.generate_ai_summary(issue_data, selected_vol, issue_num)

        except Exception as e:
            self.status_label.configure(text=f"Error processing issue.")

    def generate_ai_summary(self, raw_data, series_name, issue_num):
        char_list = raw_data.get('character_credits') or []
        character_names = ", ".join([char['name'] for char in char_list])
        raw_desc = raw_data.get('deck') or raw_data.get('description') or "No description provided by database."
        safe_desc = str(raw_desc)[:3000] 
        
        # --- The Natural AI Prompt ---
        prompt = f"""
        Act exactly like a helpful, conversational AI assistant answering a user who just asked: "What is {series_name} #{issue_num} about?"
        
        Using the raw data provided and your own extensive knowledge of comic books, give a natural, engaging, and easy-to-read response. 
        
        CRITICAL RULES:
        1. NO SPOILERS for future issues or major twists.
        2. Write in a conversational, friendly tone, just like a helpful AI.
        3. Break the text into short, digestible paragraphs. 
        4. Use standard dashes (-) for bullet points. 
        5. Do NOT use Markdown formatting (like ** or #) since this will be displayed in a plain text window. 
        
        RAW DATA:
        Series: {series_name}
        Issue Number: {issue_num}
        Chapter Title: {raw_data.get('name', 'Unknown Chapter')}
        Plot Snippet: {safe_desc}
        Characters: {character_names}
        
        Structure your response naturally, with this flow:
        - A friendly opening acknowledging the specific run, era, or creative team.
        - A brief setup of where the character is at the start of the issue.
        - The main plot points or conflict (use a brief bulleted list with dashes).
        - How the conflic of the issue resolves itself.
        - A quick wrap-up about why this issue is a great read or a fun piece of trivia.
        """
        
        try:
            self.status_label.configure(text="Finding compatible AI model...")
            
            working_model = None
            available_models = list(ai_client.models.list())
            
            for m in available_models:
                if m.supported_actions and 'generateContent' in m.supported_actions and 'flash' in m.name.lower():
                    working_model = m.name
                    break
            
            if not working_model:
                for m in available_models:
                    if m.supported_actions and 'generateContent' in m.supported_actions:
                        working_model = m.name
                        break
            
            if not working_model:
                self.status_label.configure(text="Error: No valid models.")
                return
                
            clean_model_name = working_model.replace("models/", "")
            self.status_label.configure(text=f"Writing summary...")
            
            response = ai_client.models.generate_content(
                model=clean_model_name,
                contents=prompt
            )
            
            self.summary_box.delete("1.0", "end")
            self.summary_box.insert("1.0", response.text)
            self.status_label.configure(text="Summary Complete!")
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "exhausted" in error_msg.lower():
                self.status_label.configure(text="API limit reached. Wait 60s.")
            else:
                self.status_label.configure(text="AI Generation Failed. Check console.")
                print(f"Error details: {e}")

if __name__ == "__main__":
    app = ComicSummaryApp()
    app.mainloop()