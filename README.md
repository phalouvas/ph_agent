### PH Agent

A Frappe app that integrates agentic AI chatbots into ERPNext, enabling autonomous, intelligent conversations and task automation within your business workflows.

### Features

- **AI Chat UI** — A full-featured chat interface embedded in the ERPNext desk, powered by `vue-advanced-chat`
- **Multiple LLM Providers** — Configure multiple providers (DeepSeek, OpenAI-compatible APIs) and switch between them per session
- **Real-time responses** — Agent replies appear instantly via Frappe's built-in WebSocket system
- **File attachments** — Attach files to chat messages; files are stored as Frappe `File` records linked to the message
- **PDF extraction** — Attach a PDF file and the agent automatically reads its content using PyPDF2
- **Conversation memory** — Full message history is passed to the agent on every turn, enabling follow-up questions and contextual replies
- **Auto-generated session titles** — After the first exchange, the LLM generates a concise title for the session automatically
- **Session management** — Create, browse, and delete chat sessions from the chat UI
- **Message editing** — Edit your own messages; subsequent messages are automatically deleted and the agent regenerates its response
- **Message deletion** — Delete individual messages or batch delete selected messages
- **Message regeneration** — Regenerate agent responses with a single click; the message stays in place with a spinner indicator
- **Stop generation** — Cancel ongoing AI generation with a stop button
- **Error handling** — Friendly error messages for misconfigured or disabled providers

### Requirements

- Frappe / ERPNext v16
- Python 3.11+
- A DeepSeek API key (or any OpenAI-compatible LLM provider)
- `PyPDF2` Python package (installed automatically via `bench pip install PyPDF2`)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app ph_agent
bench --site <your-site> migrate
bench pip install PyPDF2
```

### Configuration

After installation, configure at least one LLM Provider:

1. Log into the ERPNext desk
2. Navigate to **PH Agent → LLM Provider**
3. Create a new record:
   - **Provider Name**: e.g. `DeepSeek`
   - **API Key**: your DeepSeek API key (from [platform.deepseek.com](https://platform.deepseek.com))
   - **API URL**: `https://api.deepseek.com/v1` (default)
   - **Default Model**: `deepseek-chat` (default)
   - Check **Enabled** and **Default**
4. Save

To add additional providers (e.g. a local Ollama instance):
- Create another LLM Provider record with the appropriate API URL and model
- Only one provider can be set as **Default** at a time
- Users can select a provider when starting a new chat session

### Usage

1. Open the ERPNext desk
2. Navigate to **PH Agent → AI Chat** in the sidebar
3. Click **New Chat** — select a provider and start chatting
4. Click the room header to change the provider for an existing session
5. Attach files using the paperclip icon in the message footer — PDF files are automatically read and their content is passed to the agent
6. The agent remembers the full conversation history within a session — ask follow-up questions naturally
7. After your first message, the session title updates automatically to reflect the topic
8. **Message actions** (hover over a message to reveal):
   - **Edit** your own messages (only visible on your messages)
   - **Delete** any message (requires permission)
   - **Select** multiple messages for batch deletion
   - **Regenerate** agent responses (only visible on agent messages)
9. **Stop generation** — Click the red stop button that appears while the AI is responding to cancel generation
10. **Regeneration flow** — When regenerating an agent response, the message stays in place with a spinner until the new response arrives

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/ph_agent
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

gpl-3.0
