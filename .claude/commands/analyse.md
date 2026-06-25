---
description: Dry-run the Transform Advisor on the Meridian Bank sample XML and print a mapping summary
allowed-tools: PowerShell, Read, Bash
---

Run a quick analysis of the built-in sample internal bank payment message.

Steps:
1. Read `data/samples/internal/sample_bank_payment.xml` and confirm it exists.
2. Run the parser to count fields:
   ```powershell
   .venv\Scripts\python.exe -c "
   from src.transformer.message_parser import parse_xml_fields
   from pathlib import Path
   fields = parse_xml_fields(Path('data/samples/internal/sample_bank_payment.xml').read_text(encoding='utf-8'))
   print(f'Fields parsed: {len(fields)}')
   for f in fields:
       print(f'  {f.xpath} = {repr(f.sample[:40])}')
   "
   ```
3. Display the field list in a readable format grouped by parent element.
4. Remind the user that the full Claude-powered mapping (DIRECT/DERIVED/UNMAPPED classification)
   requires launching the Streamlit app (`/run`) and entering an API key — this command only
   runs the XML parser locally, without an API call.
5. Summarise what the demo scenario showcases:
   - Domestic payment (BACS): sort codes need IBAN/BIC derivation → DERIVED mappings
   - Cross-border (CHAPS): IBAN + BIC already present → DIRECT mappings
   - Internal fields (CostCentre, WorkflowId, ApprovalStatus) → UNMAPPED
   - Missing ChrgBr → BLOCKING gap requiring business decision
