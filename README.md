### PH Agent

A Frappe app that integrates agentic AI chatbots into ERPNext, enabling autonomous, intelligent conversations and task automation within your business workflows.

### Features

- **AI Chat UI** — A full-featured chat interface embedded in the ERPNext desk, powered by `vue-advanced-chat`
- **Multiple LLM Providers** — Configure multiple providers (DeepSeek, OpenAI-compatible APIs) and switch between them per session
- **Real-time responses** — Agent replies appear instantly via Frappe's built-in WebSocket system
- **File attachments** — Attach files to chat messages; files are stored as Frappe `File` records linked to the message
- **File extraction** — Attach files (PDF, DOCX, PPTX, XLSX, HTML, etc.) and the agent automatically reads their content using markitdown
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
- `markitdown[pdf,docx,pptx,xlsx,html]` Python package (installed automatically via bench)
- `agent-framework-core` Python package (installed automatically as a dependency of `agent-framework`)

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

### Agent Skills

PH Agent includes an **Agent Skills** system that lets you teach the AI how to perform domain-specific tasks. Skills follow a **progressive disclosure** pattern — the AI reads a high-level `SKILL.md`, then optionally loads reference resources and executes scripts.

#### Skill Sources

Skills come from two sources (merged at runtime):

1. **DocType-based** — Create records in the **Skill Registry** (`PH Agent → Skill Registry`) with rich content, resources, and scripts.
2. **File-based** — Place skill folders under `private/files/skills/<skill-name>/` on your site. A skill folder must contain at least a `SKILL.md` file.

If a file-based skill has the same name as a DocType-based skill, the DocType version wins (the file directory is excluded).

#### Skill Structure

Each skill folder (or Skill Registry record) can contain:

```
<skill-name>/
├── SKILL.md              # Required: skill instructions with YAML frontmatter
├── references/           # Optional: reference resources
│   └── doc_types.md      #   Static content or dynamic functions
└── scripts/              # Optional: executable scripts
    └── query_generator.py
```

- **SKILL.md** — Markdown with YAML frontmatter (`name`, `description`). Contains instructions the AI reads to understand when and how to use the skill.
- **Resources** — Supplementary reference material. Can be static Markdown text or a dynamic Python function that returns a string.
- **Scripts** — Executable Python scripts. Can be an **In-Process Function** (imported callable) or a **File Reference** (run as a subprocess with 30s timeout).

#### Security

- **Script approval** is required by default — the AI cannot execute scripts without user confirmation.
- File-based scripts run in a subprocess with a restricted environment and isolated working directory.
- DocType-based skills can use `Dynamic Function` resources and `In-Process Function` scripts that are imported from dotted Python paths — only load code you trust.

#### Creating a Sample Skill

PH Agent ships with a `frappe-data-query` sample skill that teaches the AI to query Frappe/ERPNext data safely. To use it after installation:

```bash
bench --site <your-site> migrate
```

The migration copies the sample skill files from the app package to your site's `private/files/skills/` directory and seeds a corresponding Skill Registry record.

You can create your own skills:

1. **Via the Desk**: Go to **PH Agent → Skill Registry** and create a new record with `SKILL.md` content, resources, and scripts.
2. **Via files**: Create a folder in `private/files/skills/<skill-name>/` on your site with a `SKILL.md` file.

> **Tip**: Use the Skill Registry when you need rich content editing. Use file-based skills when you want to version-control skill files directly on the server.

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
