---
description: Show the last 60 lines of the SwiftSage log file and watch for new entries
allowed-tools: PowerShell, Read
---

Show the SwiftSage application logs.

Steps:
1. Check if `logs\swiftsage.log` exists.
   - If it does not exist, tell the user the app has not been run yet or no errors have been logged.
2. Read and display the last 60 lines of `logs\swiftsage.log` using:
   ```powershell
   Get-Content logs\swiftsage.log -Tail 60
   ```
3. Look for any lines containing ERROR or CRITICAL and highlight them to the user.
4. Summarise:
   - How many ERROR lines are present
   - The most recent FieldMapper API call (INFO lines with "FieldMapper:")
   - Whether any "stop_reason" was not "end_turn" (which would indicate truncation)
5. If the user wants to watch logs live, tell them to run in a separate terminal:
   ```powershell
   Get-Content logs\swiftsage.log -Wait -Tail 50
   ```
