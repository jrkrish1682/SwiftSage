---
description: Run the SwiftSage pytest test suite and report results
allowed-tools: PowerShell, Read
---

Run the automated test suite for SwiftSage.

Steps:
1. Run the tests using the project virtual environment:
   ```powershell
   .venv\Scripts\python.exe -m pytest tests/ -v --tb=short 2>&1
   ```
2. Parse the output and report:
   - Total tests: passed / failed / errored
   - Any FAILED tests — show the test name and the short traceback
   - Any import errors that prevented collection
3. If all tests pass, confirm with a summary line.
4. If tests fail, suggest which source file to look at based on the test name
   (e.g. `test_comparator.py` → `src/comparator/xml_comparator.py`).

Note: Tests do NOT require an Anthropic API key — they use pre-built sample XMLs only.
