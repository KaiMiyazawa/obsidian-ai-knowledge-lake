---
allowed-tools: Bash(gemini:*)
description: Web search using Gemini CLI
---

## Gemini Search

`gemini` is the Google Gemini CLI. For this command, do web searches through it rather than the built-in web search tool. The result for the query below is already included; for follow-up searches, run `gemini --prompt 'WebSearch: <query>'` via Bash.

Query: $ARGUMENTS

### Execute Search
!`gemini --prompt "WebSearch: $ARGUMENTS"`
