# PH Agent Implementation Progress

*Document Version: 1.1*  
*Last Updated: 2026-04-22*  
*Maintainer: PH Agent Development Team*

---

## Overview

This document tracks the implementation progress of PH Agent features as outlined in [`FEATURES.md`](FEATURES.md). It serves as a living record of completed work, current tasks, and future plans, while capturing key architectural decisions and technical notes.

## Revised Implementation Plan (Microsoft Agent Framework Integration)

**Note:** This plan has been updated to leverage the Microsoft Agent Framework's built‑in capabilities for tools, workflows, memory, and multi‑agent orchestration. The original phase structure is preserved, but tasks have been revised to use framework components where appropriate.

## Microsoft Agent Framework Documentation Links

To assist developers implementing these features, here are key documentation links for the Microsoft Agent Framework:

- **Main Documentation**: [Microsoft Agent Framework Overview (Python)](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python)
- **Python SDK API Reference**: [Python SDK Overview](https://learn.microsoft.com/en-us/python/api/agent-sdk-python/agents-overview?view=agent-sdk-python-latest)
- **Quickstart (Python)**: [Quickstart: Build your first agent with Python](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/quickstart-python)
- **GitHub Repository (Python)**: [microsoft/agents-for-python](https://github.com/microsoft/agents-for-python)
- **GitHub Repository (Main)**: [microsoft/Agents](https://github.com/microsoft/Agents)

**Key Modules Referenced in This Document**:
- `agents.function_tool` – Function tools with schema validation
- `agents.mcp` – Model Context Protocol server integration  
- `agents.workflows.Workflow` – Graph‑based workflow orchestration
- `agents.vectorstores` – Vector store integrations for memory
- `agents.AIAgent` – Base class for AI agents
- `agents.Skill` – Skills for progressive disclosure
- `AgentSession` – Conversation state persistence
- `IContextProvider` – Memory and RAG context injection
- `ToolApprovalMiddleware` – Human‑in‑the‑loop approval workflow
- `AgentRunMiddleware` – Telemetry and tracing middleware
- `VectorStore` – Vector database abstraction
- `IChatClient` – LLM provider interface
- `HostedAgent` – Pre‑built agent integrations
- `DevUI` – UI framework components

*For a complete mapping of capabilities to framework components, see the [Capabilities Reference](#microsoft-agent-framework-capabilities-reference) table above.*

For detailed API documentation, refer to the Python SDK reference and the samples in the GitHub repositories. The main overview page serves as the primary entry point for Python developers.

## Microsoft Agent Framework Capabilities Reference {#microsoft-agent-framework-capabilities-reference}

The table below maps each major capability area to specific Microsoft Agent Framework components and documentation links. Use this as a quick reference when implementing features.

| Capability Area | Framework Component | Key Classes/Modules | Documentation Link |
|-----------------|---------------------|---------------------|-------------------|
| **Agents** | Default Agent Runtime, AIAgent/BaseAgent | `AIAgent`, `BaseAgent`, `AgentSession` | [Agents Overview](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#agents) |
| **Tools** | Function Tools, MCP Integration, Tool Approval | `function_tool`, `agents.mcp`, `ToolApprovalMiddleware` | [Tools & MCP](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#tools) |
| **Skills** | Skills Framework | `Skill`, `SkillRegistry`, `SkillLoader` | [Skills](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#skills) |
| **Conversations & Memory** | AgentSession, Context Providers, Vector Stores | `AgentSession`, `IContextProvider`, `VectorStore` | [Memory & Context](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#conversations--memory) |
| **Providers** | Provider Abstraction | `IChatClient`, `OpenAIChatClient`, `AzureOpenAIChatClient` | [Providers](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#providers) |
| **Workflows** | Workflow Engine | `Workflow`, `Executor`, `Edge`, `Condition` | [Workflows](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#workflows) |
| **Integrations** | UI Framework, Hosted Agents, Vector Stores | `DevUI`, `HostedAgent`, `VectorStore` | [Integrations](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#integrations) |
| **Middleware** | Agent Run, Function Calling, IChatClient Middleware | `AgentRunMiddleware`, `FunctionCallingMiddleware`, `IChatClientMiddleware` | [Middleware](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python#middleware) |

---

## Phase 1: Foundation

**Status:** 🚧 **In Progress** (Target completion: Weeks 1‑2)

### 1.1 Tool Framework
**Goal:** Enable the agent to call ERPNext functions via a registry of whitelisted tools.

**Detailed Breakdown:**
- **Tool Registry DocType**: Create JSON file in `ph_agent/ph_agent/doctype/tool_registry/`, define fields: `tool_name`, `description`, `python_function`, `parameters_json`, `permission_doctype`, `requires_approval`. Add validation hooks.
- **Tool Registry Access Control**: Add child table `tool_registry_doc_type_access` to link tools with DocTypes and permissions.
- **ToolManager Class**: Create `tool_manager.py` with methods `load_tools()`, `register_tool()`, `validate_schema()`. Integrate with `agents.function_tool`.
- **Tool Approval Middleware**: Implement a middleware that intercepts tool calls marked as `requires_approval` and creates a `Tool Approval` document for human review.
- **MCP Server Integration**: Set up a Model Context Protocol server using `agents.mcp` module, expose web search, file search tools.
- **Built‑in Tools Integration**: Utilize Microsoft Agent Framework's built‑in tools: Code Interpreter, File Search, Web Search, and Hosted/Local MCP tools.
- **Sample ERPNext Tools**: Implement five functions in `ph_agent/agent/tools/erpnext_tools.py` using `@function_tool` decorator.
- **Logging Middleware**: Use Microsoft Agent Framework's `FunctionCallingMiddleware` to capture tool invocations and store in `Chat Message` child table.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 1.1.1 | Create `Tool Registry` DocType | ✅ **Completed** | [task/1.1.1](https://github.com/phalouvas/ph_agent/tree/task/1.1.1) | JSON schema: `tool_name`, `description`, `python_function`, `parameters_json`, `requires_approval`, `is_enabled`. Validation: unique tool_name, importable python_function, valid JSON. Simplified design: No permission fields - relies on Frappe's DocType permissions and tool-level permission checks. |
| 1.1.2 | Implement `ToolManager` class with `function_tool` registration | ✅ **Completed** | [task/1.1.2](https://github.com/phalouvas/ph_agent/tree/task/1.1.2) | ToolManager implemented with caching, context injection, and dynamic tool registration. Includes two test tools: datetime tool and calculator tool. Uses `agent_framework.tool` decorator (not `agents.function_tool` due to compatibility). |
| 1.1.3 | Add Tool Approval middleware for sensitive actions | ✅ **Completed** | [version-16](https://github.com/phalouvas/ph_agent/tree/version-16) | Human‑in‑the‑loop approval workflow for tools marked as `requires_approval`. Created `Tool Approval Request` DocType (fields: tool_name, description, arguments, chat_session, chat_message, status, approver, approval_date, rejection_reason, conversation_state, agent_message_saved). Implements `_handle_tool_approval()` to create approval docs and pause execution, `_execute_approved_tool()` background job to resume after approval. Approve/Reject buttons on DocType form. Cascade delete via `on_trash` doc_events hooks for Chat Session and Chat Message. Real-time UI notifications for pending/resolved approvals. Three bugs fixed: approval_mode propagation, @frappe.whitelist() on approve/reject methods, and cascade delete using frappe.db.delete(). |
| 1.1.4 | Integrate MCP server for external tools (web search, file search) | ⬜ Not Started | | Use Microsoft Agent Framework's MCP integration for hosted/local tools |
| 1.1.5 | Create 5 sample ERPNext tools using `function_tool` | ⬜ Not Started | | `get_customer_details`, `list_sales_orders`, `fetch_stock_levels`, `create_quotation`, `send_email` |
| 1.1.6 | Add tool‑call logging via Function Calling Middleware | ⬜ Not Started | | Store tool invocation details in `Chat Message` using framework middleware |
| 1.1.7 | Implement Tool Registry Access Control using Frappe permissions | ✅ **Simplified** | | Access control handled by Frappe's DocType permissions (System Manager only) and tool-level permission checks in Python functions |

### 1.2 Planning Agent
**Goal:** Add multi‑step reasoning and explicit task decomposition.

**Detailed Breakdown:**
- **PlanningWorkflow Class**: Create `planning_workflow.py` that defines a `Workflow` with `Executors` for decomposition, using `agents.workflows.Workflow`. Integrate with agent's `run` method.
- **Skills Implementation**: Define a `Skill` class that bundles system prompts, scripts, and resources. Register skills with the workflow.
- **Skills Framework**: Leverage Microsoft Agent Framework's Skills system for progressive disclosure, script approval, custom system prompts, and caching behavior.
- **Intermediate Steps Storage**: Add `intermediate_steps` JSON field to `Chat Message` DocType, store each step's reasoning, tool calls, results.
- **UI Toggle Component**: Create a Vue component in `public/js/chat/modules/` that shows/hides reasoning steps with a toggle button.
- **Timeout Handling**: Use Workflow checkpointing to limit max steps and implement timeout detection using `asyncio` or framework's timeout middleware.


| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 1.2.1 | Create `PlanningWorkflow` using Microsoft Agent Framework's Workflow engine | ⬜ Not Started | | Use `agents.workflows.Workflow` with Executors for decomposition |
| 1.2.2 | Implement Skills for progressive disclosure of planning instructions | ⬜ Not Started | | Skills bundle system prompts, scripts, and resources for planning |
| 1.2.3 | Store intermediate steps in `Chat Message` | ⬜ Not Started | | Add `intermediate_steps` field (JSON) to capture planning trace |
| 1.2.4 | Create UI toggle for showing/hiding reasoning | ⬜ Not Started | | Frontend component in Vue Advanced Chat |
| 1.2.5 | Add timeout handling using Workflow checkpointing | ⬜ Not Started | | Prevent infinite loops using workflow checkpointing and max steps |

### 1.3 Enhanced Memory
**Goal:** Move beyond simple conversation history to vector‑based semantic memory.

**Detailed Breakdown:**
- **Vector Store Dependency**: Add `chromadb` or `qdrant-client` to `pyproject.toml`. Install Microsoft Agent Framework's vector store integration (`agents.vectorstores`).
- **VectorMemory Class**: Implement `VectorMemory` in `vector_memory.py` using framework's `VectorStore` abstraction. Methods: `add_conversation()`, `search_similar()`, `delete_old()`.
- **Memory Storage Hook**: Use `AgentSession` and `Context Providers` to automatically embed new chat messages and store them in the vector store.
- **Retrieval Integration**: Use AI Context Providers to inject top‑k relevant past conversations into the agent's context via RAG.
- **Memory Management UI**: Create a Frappe Desk page to view and delete stored memory vectors, with search and filtering.
- **Performance Benchmark**: Measure retrieval latency with synthetic load, ensure <100ms.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 1.3.1 | Install vector store dependency (ChromaDB/Qdrant) and framework integration | ⬜ Not Started | | Add to `pyproject.toml` under `[project.dependencies]` |
| 1.3.2 | Implement `VectorMemory` class using Microsoft Agent Framework's VectorStore abstraction | ⬜ Not Started | | Use framework's `VectorStore` for embeddings and similarity search |
| 1.3.3 | Hook memory storage via AgentSession and Context Providers | ⬜ Not Started | | Automatically embed new messages using AI Context Providers |
| 1.3.4 | Integrate memory retrieval via AI Context Providers for RAG | ⬜ Not Started | | Inject top‑3 relevant past conversations using framework's context injection |
| 1.3.5 | Build memory‑management UI | ⬜ Not Started | | Allow users to view/delete stored memory vectors |
| 1.3.6 | Performance benchmark | ⬜ Not Started | | Measure retrieval latency (<100ms target) |

### 1.4 Provider Management

**Goal:** Manage multiple LLM providers with unified interface using Microsoft Agent Framework's provider abstraction.

**Detailed Breakdown:**
- **Provider Configuration DocType**: Extend `LLM Provider` DocType to include fields for Azure OpenAI, OpenAI, Foundry, Anthropic, Ollama, etc. Add validation for endpoint URLs and API keys.
- **IChatClient Integration**: Implement provider‑specific `IChatClient` adapters for each supported provider using Microsoft Agent Framework's built‑in clients (`OpenAIChatClient`, `AzureOpenAIChatClient`, `FoundryChatClient`, `AnthropicChatClient`, `OllamaChatClient`).
- **Provider Switching**: Use framework's provider routing to dynamically switch between providers based on availability, cost, or performance.
- **Fallback & Retry Logic**: Implement middleware for automatic fallback to backup providers when primary fails, using framework's retry policies.
- **Usage Tracking**: Track token usage, costs per provider, and store metrics in `LLM Provider` records.
- **UI for Provider Management**: Create a Frappe Desk page to configure providers, test connections, and view usage analytics.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 1.4.1 | Extend `LLM Provider` DocType for all supported providers | ⬜ Not Started | | Add fields for endpoint URLs, API keys, model mappings, rate limits |
| 1.4.2 | Implement IChatClient adapters using framework's built‑in clients | ⬜ Not Started | | Use `OpenAIChatClient`, `AzureOpenAIChatClient`, `FoundryChatClient`, etc. |
| 1.4.3 | Add provider‑switching logic with fallback | ⬜ Not Started | | Use framework's provider routing and retry policies for high availability |
| 1.4.4 | Implement usage tracking per provider | ⬜ Not Started | | Store token counts, costs, latency metrics in provider records |
| 1.4.5 | Build provider‑management UI | ⬜ Not Started | | Test connections, view analytics, configure priorities |

### 1.5 Middleware Architecture

**Goal:** Leverage Microsoft Agent Framework's middleware stack for cross‑cutting concerns: telemetry, security, validation, and tool approval.

**Detailed Breakdown:**
- **Middleware Configuration**: Define a configuration system to enable/disable middleware chains per agent or globally.
- **Agent Run Middleware**: Use `AgentRunMiddleware` to log input/output of every agent invocation, measure latency, and capture errors.
- **Function Calling Middleware**: Use `FunctionCallingMiddleware` to intercept tool calls for logging, validation, and transformation before execution.
- **Tool Approval Middleware**: Implement human‑in‑the‑loop approval workflow using `ToolApprovalMiddleware` for sensitive tools.
- **IChatClient Middleware**: Use `IChatClientMiddleware` to modify requests to LLM providers (add headers, retry logic, fallback).
- **Telemetry Integration**: Integrate OpenTelemetry via middleware for distributed tracing across agent runs, tool calls, and LLM requests.
- **Custom Middleware**: Create custom middleware for Frappe‑specific concerns (permission checking, audit logging).

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 1.5.1 | Configure Agent Run Middleware for telemetry | ⬜ Not Started | | Log agent inputs/outputs, measure latency, capture errors |
| 1.5.2 | Implement Function Calling Middleware for tool logging | ⬜ Not Started | | Intercept tool calls, validate parameters, log results |
| 1.5.3 | Set up Tool Approval Middleware for sensitive actions | ⬜ Not Started | | Human‑in‑the‑loop approval workflow for tools marked `requires_approval` |
| 1.5.4 | Add IChatClient Middleware for request modification | ⬜ Not Started | | Add headers, implement retry logic, handle provider fallback |
| 1.5.5 | Integrate OpenTelemetry for distributed tracing | ⬜ Not Started | | Trace across agent runs, tool calls, LLM requests |
| 1.5.6 | Create custom middleware for Frappe permissions | ⬜ Not Started | | Check `has_permission` before tool execution, log audit trails |

---

## Phase 2: Advanced Capabilities

**Status:** ⏳ **Not Started** (Target completion: Weeks 3‑4)

### 2.1 Multi‑Agent System
**Goal:** Enable specialist agents (sales, support, accounting) with orchestration.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 2.1.1 | Create `Agent Profile` DocType | ⬜ Not Started | | Fields: `specialty`, `instructions`, `allowed_tools`, `model_preferences` |
| 2.1.2 | Implement `Orchestrator` class using Microsoft Agent Framework's Teams/AgentGroup | ⬜ Not Started | | Routes queries to appropriate specialist using framework's team routing |
| 2.1.3 | Build 3 specialist agents using `AIAgent` with domain-specific prompts and Skills | ⬜ Not Started | | `SalesAgent`, `SupportAgent`, `AccountingAgent` with Skills for domain knowledge |
| 2.1.4 | Add inter‑agent communication via A2A protocol and Frappe realtime events | ⬜ Not Started | | Use A2A for agent-to-agent calls, Frappe events for UI updates |
| 2.1.5 | Create agent‑selection UI | ⬜ Not Started | | Dropdown in chat interface to pick specialist manually/auto |
| 2.1.6 | Implement load balancing using framework's agent routing policies | ⬜ Not Started | | Distribute concurrent requests across available agents with round‑robin or least‑loaded |

### 2.2 Workflow Engine
**Goal:** Support state‑based guided conversations with conditional branching.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 2.2.1 | Design `Workflow` DocType compatible with Microsoft Agent Framework's Workflow engine | ⬜ Not Started | | Store workflow definition as JSON compatible with framework's `Workflow` |
| 2.2.2 | Implement `WorkflowRunner` that converts DocType to framework's `Workflow` and executes | ⬜ Not Started | | Manages state, triggers agent steps, pauses for human approval using framework's Executors and Edges |
| 2.2.3 | Create sample workflow: Customer Onboarding using framework's Executors and Edges | ⬜ Not Started | | 5 states: welcome → collect details → verify → setup → notify with conditional transitions |
| 2.2.4 | Add workflow visualization using Mermaid.js | ⬜ Not Started | | Mermaid.js diagrams showing current state and possible transitions |
| 2.2.5 | Build workflow editor UI that generates framework-compatible workflow definitions | ⬜ Not Started | | Drag‑and‑drop state designer for admins |
| 2.2.6 | Integrate with agent tools using framework's tool integration | ⬜ Not Started | | Workflow steps can invoke any registered tool via framework's tool calling |

### 2.3 Evaluation & Observability
**Goal:** Comprehensive monitoring, tracing, and quality assessment.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 2.3.1 | Add OpenTelemetry instrumentation using Microsoft Agent Framework's Middleware | ⬜ Not Started | | Trace agent reasoning, tool calls, LLM latency via Agent Run Middleware and Function Calling Middleware |
| 2.3.2 | Create `Agent Metrics` DocType | ⬜ Not Started | | Store response time, token usage, tool success rate, cost |
| 2.3.3 | Build real‑time dashboard using framework's events system | ⬜ Not Started | | Frappe Desk page showing key metrics and alerts from framework telemetry |
| 2.3.4 | Implement automated quality scoring using framework's evaluation hooks | ⬜ Not Started | | Heuristics for relevance, accuracy, helpfulness using framework's evaluation APIs |
| 2.3.5 | Set up A/B testing framework using framework's provider switching | ⬜ Not Started | | Compare different agent configurations using framework's provider routing |
| 2.3.6 | Create anomaly detection using framework's telemetry data | ⬜ Not Started | | Flag unusual token usage or repeated tool failures using framework's metrics |

### 2.4 Integration Patterns

**Goal:** Leverage Microsoft Agent Framework's extensive integration ecosystem for enterprise scenarios.

**Detailed Breakdown:**
- **UI Framework Integration**: Use DevUI components to embed agent capabilities into Frappe Desk pages and custom web apps.
- **Hosted Agents Integration**: Integrate with Microsoft Foundry Hosted Agents for pre‑built business scenarios (e.g., customer support, sales analysis).
- **Vector Store Integrations**: Connect to Azure AI Search, PostgreSQL, Qdrant, Redis, and other vector stores for semantic memory and RAG.
- **Memory AI Context Providers**: Use built‑in memory injection providers to dynamically inject conversation history and external data into agent context.
- **RAG AI Context Providers**: Implement retrieval‑augmented generation using framework's RAG providers for document search.
- **Azure Functions (Durable) Integration**: Orchestrate long‑running workflows with Azure Functions and Durable Tasks.
- **A2A Protocol**: Enable agent‑to‑agent communication across network boundaries for distributed multi‑agent systems.
- **M365 Integration**: Connect to Microsoft 365 data sources (Outlook, SharePoint, Teams) using framework's M365 connectors.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 2.4.1 | Integrate DevUI components for embedding agents in Frappe Desk | ⬜ Not Started | | Use framework's DevUI components for chat interfaces, agent controls |
| 2.4.2 | Connect to Microsoft Foundry Hosted Agents for business scenarios | ⬜ Not Started | | Pre‑built agents for customer support, sales analysis, etc. |
| 2.4.3 | Implement vector store integrations (Azure AI Search, PostgreSQL, Qdrant) | ⬜ Not Started | | Use framework's VectorStore abstraction for semantic memory |
| 2.4.4 | Add Memory AI Context Providers for dynamic memory injection | ⬜ Not Started | | Inject conversation history and external data via framework's context providers |
| 2.4.5 | Integrate RAG AI Context Providers for document search | ⬜ Not Started | | Retrieval‑augmented generation using framework's RAG providers |
| 2.4.6 | Orchestrate workflows with Azure Functions (Durable) | ⬜ Not Started | | Long‑running workflow integration using framework's Azure Functions connectors |
| 2.4.7 | Enable A2A protocol for distributed multi‑agent systems | ⬜ Not Started | | Agent‑to‑agent communication across network boundaries |
| 2.4.8 | Connect to Microsoft 365 data sources (Outlook, SharePoint, Teams) | ⬜ Not Started | | Use framework's M365 connectors for enterprise data integration |

---

## Phase 3: Production Readiness

**Status:** ⏳ **Not Started** (Target completion: Weeks 5‑6)

### 3.1 Security Hardening
**Goal:** Ensure all agent actions respect Frappe permissions and prevent abuse.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 3.1.1 | Add `has_permission` checks to every tool | ⬜ Not Started | | Use `frappe.has_permission(doctype, perm_type)` |
| 3.1.2 | Implement input sanitization | ⬜ Not Started | | Strip dangerous characters, validate JSON schemas |
| 3.1.3 | Add rate limiting per user/agent | ⬜ Not Started | | Use `frappe.rate_limiter` with configurable thresholds |
| 3.1.4 | Create `Audit Log` DocType | ⬜ Not Started | | Record all tool calls, agent decisions, permission denials |
| 3.1.5 | Implement session‑based authorization | ⬜ Not Started | | Restrict tool access based on chat‑session context |
| 3.1.6 | Add security‑headers middleware | ⬜ Not Started | | CSP, X‑Frame‑Options for chat UI |

### 3.2 Performance Optimization
**Goal:** Achieve sub‑second response times under concurrent load.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 3.2.1 | Implement Redis caching for tool results | ⬜ Not Started | | Cache frequent queries (e.g., customer lists) with TTL |
| 3.2.2 | Add database connection pooling | ⬜ Not Started | | Reuse MariaDB connections across agent instances |
| 3.2.3 | Optimize vector‑memory retrieval | ⬜ Not Started | | Index embeddings with FAISS for faster similarity search |
| 3.2.4 | Implement lazy agent initialization | ⬜ Not Started | | Load agent models only when first used |
| 3.2.5 | Add background job batching | ⬜ Not Started | | Group small tool calls into single transactions |
| 3.2.6 | Load‑test with 100 concurrent users | ⬜ Not Started | | Simulate realistic traffic, measure p95 latency |

### 3.3 UI Enhancements
**Goal:** Professional, intuitive interface for power users.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 3.3.1 | Add workflow‑visualization pane | ⬜ Not Started | | Sidebar showing current workflow state and next steps |
| 3.3.2 | Implement agent‑selection dropdown | ⬜ Not Started | | Icons, specialties, real‑time availability |
| 3.3.3 | Display real‑time token usage | ⬜ Not Started | | Progress bar showing context‑window consumption |
| 3.3.4 | Build settings modal for agent config | ⬜ Not Started | | Temperature, max‑tokens, planning depth |
| 3.3.5 | Add dark/light theme support | ⬜ Not Started | | Respect system preference, toggle button |
| 3.3.6 | Create keyboard shortcuts | ⬜ Not Started | | `Ctrl+Enter` to send, `Esc` to cancel, `/` for commands |

---

## Phase 4: Extensibility & Ecosystem

**Status:** ⏳ **Not Started** (Target completion: Weeks 7‑8)

### 4.1 Plugin System
**Goal:** Allow third‑party developers to add custom tools and agents.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 4.1.1 | Define plugin interface | ⬜ Not Started | | `register_tools()`, `register_agents()`, `on_activate()` hooks |
| 4.1.2 | Create `Plugin` DocType | ⬜ Not Started | | Metadata, version, dependencies, activation status |
| 4.1.3 | Implement hot‑reloading | ⬜ Not Started | | Load plugins without server restart (development mode) |
| 4.1.4 | Build plugin‑validation sandbox | ⬜ Not Started | | Security review: no `eval`, no filesystem writes, no network calls |
| 4.1.5 | Create plugin‑development kit | ⬜ Not Started | | Template repository, CLI tool, documentation |
| 4.1.6 | Add plugin‑dependency resolution | ⬜ Not Started | | Handle conflicting tool names, version constraints |

### 4.2 Marketplace
**Goal:** Central repository for sharing and discovering plugins.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 4.2.1 | Design marketplace REST API | ⬜ Not Started | | Browse, search, install, update plugins |
| 4.2.2 | Implement GitHub‑based backend | ⬜ Not Started | | Store plugin metadata in GitHub releases |
| 4.2.3 | Build marketplace UI in Frappe Desk | ⬜ Not Started | | Star ratings, reviews, installation counts |
| 4.2.4 | Add secure installation flow | ⬜ Not Started | | Download, verify checksum, register with plugin manager |
| 4.2.5 | Create revenue‑share model | ⬜ Not Started | | Support paid plugins with license keys |
| 4.2.6 | Implement plugin‑update notifications | ⬜ Not Started | | Alert admins when new versions are available |

### 4.3 API Gateway
**Goal:** Expose agent capabilities to external systems via REST/Webhook.

| # | Task | Status | PR/Commit | Notes |
|---|------|--------|-----------|-------|
| 4.3.1 | Design REST API specification | ⬜ Not Started | | OpenAPI 3.0, consistent error codes, pagination |
| 4.3.2 | Implement `/v1/agent/run` endpoint | ⬜ Not Started | | Accept natural‑language query, return agent response |
| 4.3.3 | Add webhook support | ⬜ Not Started | | Trigger agent on external events (e.g., new CRM lead) |
| 4.3.4 | Create `API Key` DocType | ⬜ Not Started | | Scoped permissions, rate limits, expiration |
| 4.3.5 | Build API documentation portal | ⬜ Not Started | | Interactive Swagger UI with examples |
| 4.3.6 | Implement usage analytics | ⬜ Not Started | | Track API calls per key, response times, errors |

---

## Existing Capabilities (Baseline)

The following features are **already implemented** and form the foundation for the phases below. These were completed prior to the roadmap defined in `FEATURES.md`.

| Feature | Implementation Status | Notes |
|---------|----------------------|-------|
| **Multi‑Provider LLM Support** | ✅ Complete | Configurable providers with API keys, URLs, model settings |
| **Real‑time Streaming** | ✅ Complete | Chunked responses via Frappe realtime events |
| **Conversation Memory** | ✅ Complete | Full history passed to LLM each turn |
| **File Attachments** | ✅ Complete | PDF, images, documents stored as Frappe Files |
| **File Text Extraction** | ✅ Complete | Automatic content extraction using markitdown (PDF, DOCX, PPTX, XLSX, HTML, etc.) |
| **Session Management** | ✅ Complete | Create, browse, delete chat sessions |
| **Message Editing** | ✅ Complete | Edit user messages with auto‑regeneration |
| **Message Regeneration** | ✅ Complete | Regenerate agent responses with one click |
| **Stop Generation** | ✅ Complete | Cancel ongoing LLM processing |
| **Auto‑Title Generation** | ✅ Complete | LLM‑generated session titles after first exchange |
| **Conversation Summarization** | ✅ Complete | Generate summaries of long conversations |
| **Follow‑up Suggestions** | ✅ Complete | Context‑aware question suggestions |
| **Token Tracking** | ✅ Complete | Monitor conversation token usage |

**Technical Stack in Place:**
- **Frontend**: Vue Advanced Chat web component + modular JavaScript
- **Backend**: Frappe Framework (Python) with Microsoft Agent Framework (`agents` library)
- **LLM Integration**: OpenAI SDK compatible with multiple providers
- **Storage**: Frappe MariaDB for structured data, File storage for attachments
- **Real‑time**: Frappe Socket.IO server
- **Background Jobs**: Redis Queue (RQ) via `frappe.enqueue`
- **Build System**: flit (PEP 517/518) with pre‑commit hooks

---

## Current Status Summary

| Metric | Value | Target |
|--------|-------|--------|
| **Overall progress** | 0% | 100% |
| **Phase 1 completion** | 0% | 100% |
| **Phase 2 completion** | 0% | 100% |
| **Phase 3 completion** | 0% | 100% |
| **Phase 4 completion** | 0% | 100% |

## Key Decisions & Architecture Notes

### 2026‑04‑20: Initial Planning
- **Vector Database Choice**: Selected ChromaDB over Pinecone/Weaviate for simplicity and zero‑cost on‑premise deployment. Embeddings will be generated using `sentence‑transformers/all‑MiniLM‑L6‑v2` (local) or OpenAI’s `text‑embedding‑3‑small` (cloud).
- **Permission Model**: Tools will respect Frappe’s standard `has_permission` checks; no custom permission system will be built.
- **UI Framework**: Continue using Vue Advanced Chat component; no migration to a different chat UI library planned.
- **Agent Framework**: Use Microsoft Agent Framework's built‑in middleware, session management, workflows, and MCP server integration to accelerate development and ensure robustness.
- **Deployment Target**: Primary environment is Frappe Bench (v16) with ERPNext; secondary target is Frappe Cloud.

### 2026‑04‑20: Implementation Priority
1. **Tool Framework** must be completed before Planning Agent (agents need tools to plan with).
2. **Enhanced Memory** can be developed in parallel with Planning Agent.
3. **Multi‑Agent System** depends on Tool Framework being stable.
4. **Security Hardening** must be part of each phase, not left until Phase 3.

### 2026‑04‑20: Testing Strategy
- **Manual Testing**: Rigorous human testing of each feature before deployment.
- **Integration Testing**: End‑to‑end workflow validation with real‑world scenarios.
- **Exploratory Testing**: Ad‑hoc testing to uncover edge cases and usability issues.
- **Security Review**: Manual review of tool permissions, input validation, and data handling.

## Recent Changes & PRs

| Date | PR/Commit | Description | Status |
|------|-----------|-------------|--------|
| – | – | No implementation work started yet | – |

## Next Immediate Actions

1. **Create GitHub Issues** for Phase‑1 tasks (Tool Framework).
2. **Start implementation** of `Tool Registry` DocType (estimated 2‑3 hours).
3. **Establish manual testing protocols** and checklist for each feature.
4. **Update this document** as progress is made.

---

*This document should be updated after each significant milestone, PR merge, or architectural decision.*  
*Refer to [`FEATURES.md`](FEATURES.md) for the strategic vision and rationale behind each feature.*