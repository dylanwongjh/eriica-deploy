# Empathy & Reassurance in Illness Conversation Assistant (ERICA)

### An AI Chatbot dedicated to train nurses for the more difficult conversations with End-of-life patients.

### STEPS/CHANGES PERFORMED
1. Adapted AI chatbot from Project Mindfull.
2. Changed the interface and SYSTEM PROMPT to adapt to a different context.
3. Implemented an interface to pop up before the chatbot such that users can input their specific scenario, and load the scenario into the chatbot.
4. Implemented RAG into the chatbot to provide better context-appropriate responses.
5. extract_cases.py curated to extract case studies from MedDiaLog (HuggingFace).
6. app.py updated to include call for relevant scenario in the ChromaDB.
7. extract_cases.py curated to extract case studies from ShenLab/MentalChat16K (HuggingFace).
8. clean_cases.py curated to clean the extracted .txt files, making them more appropriate for use in the AI chatbot training.
9. encountered error where 16084 cases are too large for ingesting (only 5k case files max), ingest.py is adapted to ingest in batches instead.
10. current (as of 18 May) case files are too simple, containing only the transcript of the conversation, so build_enriched_cases.py is curated to run each case file through an LLM to perform feature enrichment before ingesting.
11. Optimisation by combining clean.py and build_enriched_cases.py such that the data is cleaned and stored locally before being passed into the LLM for enrichment, reduces steps and risk of clutter.
12. Adapted build_enriched_cases.py to use free LLM models on Openrouter to analyse and process the case studies and arrange each case file neatly in appropriate sections.
13. Installed and used Ollama to use local LLM to run through each case file. 
14. Changed the "Helpful Resources" button to include helpful conversational frameworks. 
15. reset_and_reingest.py implemented to wipe out the existing ingested case files in ChromaDB, keeping only the enriched case files.
16. Implemented Patient Profile to replace the previous Disclaimer function, Patient Profile is pulled from the number one most similar case file in the ChromaDB when compared to the user's input scenario.
17. Adapted the starting message to take into account the case file selected for that particular scenario, added more variety for fallback messages when encounter error.
18. Added scoring system based on the guidelines and frameworks given.
19. Implemented a debrief feature to show what can be done better, what is done well, etc.
20. Implemented scenario library for selection of scenarios if the user is unsure of what to input.
21. Implemented refresh button for the scenario library to refresh selection of scenarios.
22. Implemeneted a "Continue Session" feature to continue where the user last left off the conversation before clicking "End Session".
23. Included chat container background image customisation.
24. Updated difficulty settings to be more strict with the tougher cases, included a baseline for beginner scenarios.


### PROCESS TO RUN THE APPLICATION
0. reset_and_reingest.py (To reset the ChromaDB, leaving only the desired case files)
1. extract_cases.py (To extract the relevant cases from the HuggingFace database)
2. build_enriched_cases.py (Feature enrichment for case files)
3. ingest.py (Ingest into the ChromaDB)
4. app.py (Run the application)


### Small Changes / Bug Fixes ###
18/5/2026 - Just implemented RAG using MentalChat16K dataset
- chat history rolling window (app.py)
- session-based state isolation (app.py)
- removed orphaned "Connecting to ERICA..." message (script.js)
- moved the resources panel inside chat interface so it does not pop up early (index.html)
- changed model version and increased max tokens to fix cutting the response (app.py)

19/5/2026
- fixed the formatting (style.css)
- fixed the formatting (index.html)

20/5/2026
- cleaned code (app.py)
- cleaned code (index.html)
- cleaned code (script.js)

21/5/2026
- adjusted the system prompt to show signs of improvement if user is doing well (app.py)

26/5/2026
- adjusted colour template (style.css)
- replaced background image and logo (index.html)
- removed SIC framework guide (app.py, script.js)

28/5/2026
- cleaned code (app.py)
- cleaned code (index.html)
- cleaned code (script.js)
- cleaned code (style.css)