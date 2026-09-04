# PharmStock handoff script — PowerShell 5.1 v2 hotfix

This patch replaces `make_pharmstock_chat_handoff.ps1` with a Windows PowerShell 5.1-compatible implementation.

Fixes:
- removes reliance on `.NET Path.GetRelativePath`;
- removes fragile `System.Char` conversions that caused `Cannot convert value "\\" to type System.Char`;
- validates every copied path remains under `ProjectRoot`;
- validates the output ZIP exists and is non-empty;
- always cleans the temporary handoff directory in `finally`;
- keeps the original exclusion policy and Stage 7K handoff note.

Extract this ZIP directly into the project root and overwrite the existing script.
