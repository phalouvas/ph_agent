# PH Agent — Upcoming Features

This document lists planned features for future development of PH Agent.

---

## Web Search Tool

Enable the agent to search the web for current information.

**Use cases:**
- "What's the current EUR/USD exchange rate?"
- "What are the latest ERPNext release notes?"
- "Find the current market price for raw material X"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `web_search_tool.py`)
- Could use a free API (DuckDuckGo, SerpAPI free tier) or a paid one (Google Custom Search, SerpAPI)
- Register in Tool Registry via a patch
- Consider rate limiting and caching to avoid excessive API costs

---

## Multi-Modal Input (Vision)

Support image attachments so the agent can analyze screenshots, photos, diagrams, and charts.

**Use cases:**
- Upload a screenshot of an error message and ask the agent what it means
- Take a photo of a receipt and have the agent extract line items
- Upload a chart and ask for analysis

**Implementation notes:**
- Extend the file attachment system in `api/chat.py` to accept images (PNG, JPG, JPEG, GIF, WebP)
- Pass image data to vision-capable models (DeepSeek-VL, GPT-4V, etc.)
- Update the LLM Provider DocType to flag which providers support vision
- Update the chat UI to display image thumbnails inline
- Handle size limits and format validation

---

## Conversation Branching

Let users branch off from any point in a conversation to explore alternative paths.

**Use cases:**
- Ask "What if we used a different supplier?" and explore that path without losing the original thread
- Compare two analytical approaches side-by-side
- Revisit a previous decision point and try a different direction

**Implementation notes:**
- Add a "Branch" action to messages in the chat UI
- When branching, create a new Chat Session that inherits the conversation history up to that point
- Display branched sessions in a tree or tabbed view
- Allow users to switch between branches and compare outcomes
- Consider a visual indicator showing which branch is currently active

---

## Voice Input

Enable hands-free interaction using speech-to-text.

**Use cases:**
- Ask questions while working in a warehouse or on the shop floor
- Dictate complex queries without typing
- Accessibility for users who cannot type easily

**Implementation notes:**
- Use the browser's built-in Web Speech API (`SpeechRecognition`) — no external dependencies
- Add a microphone button to the chat input area
- Show a recording indicator while listening
- Transcribe speech to text and submit as a normal message
- Handle browser compatibility and permission prompts
- Consider adding a "push-to-talk" mode for noisy environments
