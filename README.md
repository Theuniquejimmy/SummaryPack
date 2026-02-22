# SummaryPack
Suite of apps to get summaries of Books, TV Shows, and Comics.
files too big for here but here they are on google:

Comic Book Analyzer:
https://drive.google.com/file/d/1qOJHsJv2MF-LfZSKVy5rRkq6OidcS6O8/view?usp=sharing

TV Episode Summaries:
https://drive.google.com/file/d/1Jo4KFf5YOffoXcI1saF5hJ3S0dG_Aytw/view?usp=sharing

Book Summaries:
https://drive.google.com/file/d/1_n9892RzORmvMdbLY8tQRk2TlHkZ4scC/view?usp=sharing

------
This application is a specialized AI-driven comic book historian and digital archivist. It bridges the gap between structured database metadata (from Comic Vine) and live web research (via Gemini Google Search) to create high-quality, narrated deep dives of individual comic issues.

Here is a breakdown of the "brain" and the "engine" behind your program.
🛠️ The Core Architecture

The program operates in a three-stage pipeline: Fetch, Synthesize, and Export.
1. Data Retrieval (The Fetch)

When you enter a series and issue number, the app talks to the Comic Vine API.

    The Problem: Comic databases are often missing detailed plot summaries for specific issues (like your Daredevil #3 example).

    The Solution: If the database returns an empty plot, the app triggers a "Grounding" event. It instructs the Gemini AI to use its internal Google Search Tool to find the missing lore from sites like the Marvel or DC Fandom Wikis.

2. AI Synthesis (The Historian)

The app uses a Multi-Model Hierarchy to ensure reliability:

    Gemini 2.5 Flash: Used as the primary "speed demon" to generate the summary quickly.

    Gemini 3.1 Pro: Used as a fallback for high-complexity reasoning if the plot is particularly messy or confusing.

    Sniper Filtering: The prompt is engineered to force the AI to verify that it is only summarizing the events of a single issue, ignoring broader "story arc" summaries it might find online.

3. Digital Archiving (The Export)

Once the text is generated, the app processes the data into two formats for your digital library:

    Neural TTS (Audio): Using the edge-tts engine, the text is converted into high-fidelity "neural" speech (using voices like "Christopher" or "Ryan") so you can listen to the deep-dive like a podcast.

    EPUB (E-Book): The app packages the summary into a structured EPUB file, complete with your metadata and the official comic cover image injected as the book's cover art.

🚀 Key Technical Features
🧠 Smart "Vol" Translation

Because comic databases use years (e.g., Daredevil 2019) and Wikis use volumes (e.g., Vol 6), the Wiki/Vol Override box allows you to manually bridge the naming gap. This tells the AI exactly which "shelf" on the internet to look at for the plot.
⏳ Exponential Backoff & Jitter

To prevent Google from blocking your app for "spamming" the API, the code uses a mathematical delay system:

    If it gets a "Too Many Requests" (429) error, it waits.

    It adds a random "Jitter" (a few extra seconds) to the wait time so it doesn't look like a bot to Google's security filters.

🕰️ Persistent History

The app saves every comic you analyze into a local comic_history.json file. This populates the "Recent" dropdown in your sidebar, allowing you to quickly jump back to previous analyses without re-spending your API search credits.
📖 How to use it efficiently

    Search the Series: Enter the name and pick the correct year/volume from the dropdown.

    Toggle the Issue: Use the ◄ and ► buttons to move through a run.

    Check for Plot: If the AI says it doesn't know the plot, enter the Wiki volume number (like "Vol 6") in the Override box.

    Export: Download the EPUB and drop it into your favorite reader (Kindle, Kobo, or Apple Books).
