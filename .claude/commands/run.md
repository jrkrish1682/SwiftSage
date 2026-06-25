---
description: Start the SwiftSage Streamlit app on localhost:8501
allowed-tools: PowerShell, Bash
---

Start the SwiftSage Streamlit application.

Steps:
1. Check that the virtual environment exists at `.venv\Scripts\streamlit.exe`. If it does not exist, tell the user to run `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt` first.
2. Run the app using PowerShell:
   ```
   .venv\Scripts\streamlit.exe run app.py
   ```
3. Tell the user the app is opening at http://localhost:8501 and to enter their Anthropic API key in the sidebar.

Do not open a browser — Streamlit opens it automatically.
