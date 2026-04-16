### PH Agent

A Frappe app that integrates agentic AI chatbots into ERPNext, enabling autonomous, intelligent conversations and task automation within your business workflows.

### Features

- **AI Chat UI** — A full-featured chat interface embedded in the ERPNext desk, powered by `vue-advanced-chat`
- **Multiple LLM Providers** — Configure multiple providers (DeepSeek, OpenAI-compatible APIs) and switch between them per session
- **Real-time responses** — Agent replies appear instantly via Frappe's built-in WebSocket system
- **File attachments** — Attach files to chat messages; files are stored as Frappe `File` records linked to the message
- **Session management** — Create, browse, and delete chat sessions from the chat UI
- **Error handling** — Friendly error messages for misconfigured or disabled providers

### Requirements

- Frappe / ERPNext v16
- Python 3.11+
- A DeepSeek API key (or any OpenAI-compatible LLM provider)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app ph_agent
bench --site <your-site> migrate
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
5. Attach files using the paperclip icon in the message footer

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
