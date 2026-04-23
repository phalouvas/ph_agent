# PH Agent: AI Agent Framework Integration

## Introduction

PH Agent is a Frappe application that brings agentic AI chatbots into ERPNext, enabling intelligent conversations and task automation within business workflows. Built on the Microsoft Agent Framework (`agents` Python library) and integrated with the Frappe framework, PH Agent provides a robust foundation for AI-driven interactions.

This document outlines the current architecture, explores opportunities for deeper integration with the Agent Framework, and proposes a roadmap for transforming PH Agent into a fully-fledged multi-agent system capable of complex reasoning, tool usage, and workflow automation.

## Architecture Overview

### High-Level Component Architecture

```mermaid
graph TB
    subgraph "Frontend Layer"
        UI[Vue Advanced Chat UI]
        S[State Manager]
        EH[Event Handlers]
        RL[Realtime Listeners]
        RS[Room Service]
        UH[UI Helpers]
        UT[Utilities]
    end

    subgraph "Backend Layer (Frappe)"
        API[Chat API]
        AJ[Agent Jobs]
        PDF[PDF Extractor]
        DB[(Database)]
        RT[Realtime Events]
        Q[Background Queue]
    end

    subgraph "Agent Framework Layer (Current)"
        AG[DeepSeek Agent]
        SM[Streaming Module]
        SUM[Summarizer]
        TITLE[Title Generator]
        SUGG[Suggestions Generator]
        AF[Agent Framework Wrapper]
        LLM[LLM Provider Interface]
    end

    subgraph "Proposed Extensions"
        ORCH[Orchestrator]
        TOOLS[Tools Registry]
        MEM[Memory Store]
        EVAL[Evaluation & Observability]
        WORKFLOW[Workflow Engine]
        MULTI[Multi-Agent System]
    end

    subgraph "External Services"
        LLMAPI[LLM APIs (DeepSeek, OpenAI, etc.)]
        ERP[ERPNext Data]
        VEC[Vector Database]
    end

    UI --> API
    UI --> RT
    API --> AJ
    AJ --> AG
    AG --> LLMAPI
    AG --> AF
    AF --> LLM
    LLM --> LLMAPI

    ORCH --> AG
    ORCH --> TOOLS
    TOOLS --> ERP
    ORCH --> MEM
    MEM --> VEC
    ORCH --> MULTI
    MULTI --> AG
    ORCH --> WORKFLOW
    WORKFLOW --> EVAL

    style ORCH fill:#e1f5e1
    style TOOLS fill:#e1f5e1
    style MEM fill:#e1f5e1
    style EVAL fill:#e1f5e1
    style WORKFLOW fill:#e1f5e1
    style MULTI fill:#e1f5e1
```

### Current Data Flow

1. **User Interaction** → Frontend sends message via `send_message` API
2. **Message Storage** → Chat Message document created, linked to Chat Session
3. **Background Processing** → Agent job enqueued via RQ
4. **Agent Execution** → DeepSeek Agent processes conversation history
5. **LLM Interaction** → API call to configured LLM provider
6. **Response Streaming** → Real-time events push chunks to frontend
7. **Response Storage** → Agent response saved as Chat Message
8. **UI Update** → Frontend displays complete message

### Key Integration Points

- **Frappe Hooks**: App lifecycle integration via `hooks.py`
- **DocType System**: Chat Session, Chat Message, LLM Provider as core data models
- **Permission System**: Frappe's role-based access control
- **Realtime Framework**: WebSocket-based event broadcasting
- **Background Jobs**: Redis Queue (RQ) for asynchronous processing

## Current Capabilities

### ✅ Implemented Features

| Feature | Description | Implementation Status |
|---------|-------------|----------------------|
| **Multi-Provider LLM Support** | Configurable providers with API keys, URLs, and model settings | ✅ Complete |
| **Real-time Streaming** | Chunked responses via Frappe realtime events | ✅ Complete |
| **Conversation Memory** | Full history passed to LLM each turn | ✅ Complete |
| **File Attachments** | PDF, images, documents stored as Frappe Files | ✅ Complete |
| **File Text Extraction** | Automatic content extraction using markitdown (PDF, DOCX, PPTX, XLSX, HTML, etc.) | ✅ Complete |
| **Session Management** | Create, browse, delete chat sessions | ✅ Complete |
| **Message Editing** | Edit user messages with auto-regeneration | ✅ Complete |
| **Message Regeneration** | Regenerate agent responses with one click | ✅ Complete |
| **Stop Generation** | Cancel ongoing LLM processing | ✅ Complete |
| **Auto-Title Generation** | LLM-generated session titles after first exchange | ✅ Complete |
| **Conversation Summarization** | Generate summaries of long conversations | ✅ Complete |
| **Follow-up Suggestions** | Context-aware question suggestions | ✅ Complete |
| **Token Tracking** | Monitor conversation token usage | ✅ Complete |

### 🔧 Current Technical Stack

- **Frontend**: Vue Advanced Chat web component + modular JavaScript
- **Backend**: Frappe Framework (Python) with Microsoft Agent Framework (`agents` library)
- **LLM Integration**: OpenAI SDK compatible with multiple providers
- **Storage**: Frappe MariaDB for structured data, File storage for attachments
- **Real-time**: Frappe Socket.IO server
- **Background Jobs**: Redis Queue (RQ) via `frappe.enqueue`
- **Build System**: flit (PEP 517/518) with pre-commit hooks

### 📈 Current vs Future State

| Aspect | Current State | Future State with Microsoft Agent Framework |
|--------|---------------|---------------------------------------------|
| **Reasoning** | Single‑step response | Multi‑step planning using Workflow engine with Executors and conditional edges, plus Skills for progressive disclosure |
| **Tools** | PDF extraction only | Function Tools with schema validation, MCP server integration, Tool Approval middleware, Code Interpreter, File Search, Web Search |
| **Memory** | Conversation history | AgentSession persistence, Vector Store integrations (15+ providers), AI Context Providers for RAG and memory injection |
| **Agents** | Single general‑purpose agent | Simple inference agents, Complex custom agents, Remote agents via A2A protocol, Specialist agents with Skills |
| **Workflows** | Linear conversations | Graph‑based orchestration with Executors and Edges, Checkpointing, Human‑in‑the‑loop patterns |
| **Observability** | Basic logging | Agent Run, Function Calling, and IChatClient middleware for telemetry, Events system, OpenTelemetry integration |

## Microsoft Agent Framework Capabilities Overview

Microsoft Agent Framework provides a comprehensive set of building blocks for creating AI agents and workflows. Based on the official documentation, here are the key capabilities available:

| Capability Category | Key Features | Description |
|---------------------|--------------|-------------|
| **Agents** | - **Default Agent Runtime Execution Model**: Built-in execution pipeline for simple inference agents<br>- **Simple agents based on inference services**: Use `IChatClient` for LLM interaction<br>- **Complex custom agents**: Subclass `AIAgent`/`BaseAgent` for custom logic<br>- **Proxies for remote agents**: A2A protocol for calling remote endpoints<br>- **Azure and OpenAI SDK Options**: Integration with Azure OpenAI and OpenAI SDKs | Support for multiple agent types with unified programming model. Simple agents handle chat completion; complex agents enable custom reasoning loops, tool usage, and state management. A2A protocol enables distributed multi‑agent systems. |
| **Tools** | - **Function Tools**: Declarative tool definitions with schema validation using `function_tool` decorator<br>- **Tool Approval**: Human‑in‑the‑loop approval workflow for sensitive actions<br>- **Code Interpreter**: Execute Python code in secure sandbox<br>- **File Search**: Semantic search across local or cloud files<br>- **Web Search**: Internet search integration<br>- **Hosted/Local MCP Tools**: Connect to Model Context Protocol servers for tool discovery and execution<br>- **Provider Support Matrix**: Comprehensive compatibility across LLM providers | Rich tool ecosystem with built‑in security and validation. Tools can be composed, chained, and approved via middleware. MCP integration allows extensibility with external tool providers. |
| **Skills** | - **Skill Structure**: Portable packages containing instructions, scripts, and resources<br>- **Progressive Disclosure**: Skills advertise capabilities that can be loaded on‑demand<br>- **File‑based Skills**: YAML‑defined skills with metadata and prompts<br>- **Code‑defined Skills**: Programmatic skill creation using Python classes<br>- **Class‑based Skills**: Advanced multi‑source scenarios with dependency injection<br>- **Script Approval**: Security controls for script execution<br>- **Custom System Prompt**: Dynamic prompt injection based on skill context<br>- **Caching Behavior**: Performance optimization for frequently used skills<br>- **Security Best Practices**: Sandboxing and permission validation | Skills bundle domain‑specific knowledge and capabilities that can be dynamically loaded by agents. Supports filtering, versioning, and progressive disclosure to manage complexity. |
| **Conversations & Memory** | - **AgentSession**: State serialization and rehydration for conversation persistence<br>- **Context Providers**: Plug‑ins that inject external data (memory, RAG results) into agent context<br>- **Context Compaction**: Automatic reduction of conversation history to fit token limits<br>- **Storage Patterns**: Built‑in support for in‑memory, service‑managed, and third‑party storage<br>- **Chat History Providers**: Customizable history storage with session‑scoped state management<br>- **Vector Store Integrations**: 15+ vector databases (Azure AI Search, PostgreSQL, Qdrant, Redis, etc.)<br>- **AI Context Providers**: Memory and RAG providers for semantic search and recall | Comprehensive memory management with multiple storage backends. Context providers enable dynamic memory injection, while compaction optimizes token usage. Vector store integrations support long‑term semantic memory. |
| **Providers** | - **Azure OpenAI**: Chat completion, Responses API, tool calling, streaming<br>- **OpenAI**: Same capabilities as Azure OpenAI with direct API<br>- **Microsoft Foundry**: Hosted models with chat completion and responses<br>- **Anthropic**: Claude models with tool calling support<br>- **Ollama**: Local model hosting<br>- **GitHub Copilot**: Code‑focused models<br>- **Copilot Studio**: Custom conversational AI models<br>- **Custom Providers**: Implement `IChatClient` for any LLM service | Broad provider support with unified interface. Each provider supports chat completion, responses API, tool calling, and streaming where available. Provider‑specific optimizations and configurations. |
| **Workflows** | - **Graph‑based Orchestration**: Directed graphs of Executors and Edges for multi‑step processes<br>- **Executors**: AI agents or custom logic nodes that perform work<br>- **Edges**: Conditional routing between executors based on output or state<br>- **Events**: Observability hooks for workflow lifecycle monitoring<br>- **Checkpointing**: Save workflow state to durable storage for long‑running processes<br>- **Type Safety**: Strongly‑typed workflow definitions and execution<br>- **Flexible Control Flow**: Supports sequential, parallel, conditional, and loop patterns<br>- **External Integration**: Connect to external systems via events and callbacks<br>- **Multi‑Agent Orchestration**: Coordinate multiple specialist agents within a workflow | Type‑safe workflow engine for complex business processes. Supports human‑in‑the‑loop patterns, error recovery, and distributed execution. Visual design tools available for workflow creation. |
| **Integrations** | - **Microsoft Foundry Hosted Agents**: Pre‑built agents for common business scenarios<br>- **UI Framework Integrations**: DevUI components for embedding agents in applications<br>- **Chat History Providers**: Plug‑in storage backends for conversation history<br>- **Memory AI Context Providers**: Pre‑built memory injection providers<br>- **RAG AI Context Providers**: Retrieval‑augmented generation providers for document search<br>- **Vector Stores**: Native support for Azure AI Search, Cosmos DB, PostgreSQL, Qdrant, Redis, etc.<br>- **Azure Functions (Durable)**: Integration with serverless workflows<br>- **A2A Protocol**: Agent‑to‑agent communication across network boundaries<br>- **M365 Integration**: Microsoft 365 data connectors | Extensive ecosystem integrations for enterprise scenarios. Pre‑built components accelerate development and ensure best practices. |
| **Middleware** | - **Agent Run Middleware**: Intercept and modify agent runs (pre‑/post‑processing)<br>- **Agent Run Streaming Middleware**: Handle streaming responses with real‑time modifications<br>- **Function Calling Middleware**: Intercept tool calls for logging, validation, or transformation<br>- **IChatClient Middleware**: Modify requests to LLM providers (headers, retries, fallbacks)<br>- **Tool Approval Middleware**: Human‑in‑the‑loop approval for sensitive tool calls<br>- **Telemetry Middleware**: OpenTelemetry integration for distributed tracing | Pipeline interception for cross‑cutting concerns: logging, security, validation, performance monitoring, and fault tolerance. Middleware can be chained and configured per agent |

### Agent Framework Integration Opportunities

#### 1. Multi‑Step Reasoning & Planning

**Current Limitation**: The agent responds to single messages without explicit planning or decomposition of complex tasks.

**Microsoft Agent Framework Capabilities**:
- **Agent Session with Context Providers**: Use `AgentSession` to maintain conversation state across multiple turns and integrate context providers for dynamic memory.
- **Skills for Progressive Disclosure**: Package planning instructions and scripts as Skills that can be loaded on‑demand.
- **Workflow Engine for Explicit Orchestration**: Model planning steps as a Workflow graph with Executors for each sub‑task and conditional edges.

**Implementation Approach**:
```python
# Example using Agent Framework's workflow capabilities
from agents import AIAgent, AgentSession
from agents.workflows import Workflow, Executor, Edge

class PlanningWorkflow:
    def __init__(self, provider_doc):
        self.agent = AIAgent.from_provider(provider_doc)
        self.session = AgentSession()
        self.workflow = Workflow(
            executors=[
                Executor("analyzer", self.agent, instructions="Analyze the problem"),
                Executor("planner", self.agent, instructions="Break down into steps"),
                Executor("executor", self.agent, instructions="Execute each step")
            ],
            edges=[
                Edge("analyzer", "planner"),
                Edge("planner", "executor")
            ]
        )
```

#### 2. Tool Integration & ERPNext Actions

**Current Limitation**: Limited to PDF extraction; no integration with ERPNext data or actions.

**Microsoft Agent Framework Capabilities**:
- **Function Tools with Schema Validation**: Declarative tool definitions using `function_tool` decorator, automatically exposed to agents with parameter validation.
- **MCP Server Integration**: Connect to Model Context Protocol servers for tool discovery and execution (supports hosted and local MCP servers).
- **Tool Approval Middleware**: Human‑in‑the‑loop approval workflow for sensitive tool calls using the framework’s `ToolApproval` feature.
- **Tool Registry Access Control**: Fine‑grained permission mapping using Frappe DocType‑level permissions via child table linking.

**Proposed Tool Categories**:

| Tool Category | Example Tools | Framework Feature Used |
|---------------|---------------|------------------------|
| **Data Query** | `get_customer_details`, `list_open_orders` | Function Tools + ERPNext Python API |
| **Document Actions** | `create_quotation`, `update_lead_status` | MCP Server integration for Frappe DocType methods |
| **Analytics** | `calculate_margin`, `forecast_sales` | Code Interpreter tool for Python scripts |
| **System Actions** | `send_email`, `create_calendar_event` | Hosted MCP tools (e.g., Microsoft Graph connector) |

#### 3. Memory & Context Management

**Current Limitation**: Simple conversation history with token limits; no long‑term memory.

**Microsoft Agent Framework Capabilities**:
- **AgentSession Persistence**: Built‑in serialization and storage of conversation state with automatic rehydration.
- **Vector Store Integrations**: Native support for 15+ vector stores (Azure AI Search, PostgreSQL, Qdrant, Redis, etc.) via `Microsoft.Extensions.VectorData.Abstractions`.
- **AI Context Providers**: Plug‑ins for `ChatClientAgent` that inject memories or RAG results into the conversation context.

**Implementation Architecture**:
- **Short‑term**: `AgentSession` with in‑memory chat history provider (existing)
- **Medium‑term**: Vector store (Azure AI Search / PostgreSQL) for semantic search across past conversations
- **Long‑term**: Structured entity memory using Frappe DocTypes with relationship mapping

#### 4. Multi‑Agent Collaboration

**Current Limitation**: Single agent architecture; no specialist collaboration.

**Microsoft Agent Framework Capabilities**:
- **Workflow‑Based Orchestration**: Use the Workflow engine to coordinate multiple agents as Executors, with edges controlling message flow.
- **A2A Protocol for Remote Agents**: Proxy agents can call remote endpoints, enabling distributed multi‑agent systems.
- **Specialist Skills**: Package domain‑specific knowledge as Skills that can be dynamically loaded by specialist agents.

**Example Multi‑Agent Workflow**:
```
User: "I need help with a customer complaint and creating a refund"
└── Workflow Orchestrator
    ├── Support Agent (Skill: complaint‑resolution)
    └── Accounting Agent (Skill: refund‑processing)
```

#### 5. Workflow Engine & State Management

**Current Limitation**: Linear conversation flow; no support for structured workflows.

**Microsoft Agent Framework Capabilities**:
- **Graph‑Based Workflows**: Define workflows as directed graphs of Executors (AI agents or custom logic) and Edges (conditional routing).
- **Checkpointing**: Save workflow state to durable storage, allowing long‑running processes to be paused and resumed.
- **Human‑in‑the‑Loop Patterns**: Built‑in request/response patterns for integrating human approvals and interventions.

**Use Case Example**:
```python
from agents.workflows import Workflow, Executor, Edge, Condition

refund_workflow = Workflow(
    executors=[
        Executor("collect", agent, instructions="Gather refund details"),
        Executor("verify", agent, instructions="Check refund policy"),
        Executor("approve", agent, instructions="Await manager approval"),
        Executor("process", agent, instructions="Execute refund in ERP"),
        Executor("notify", agent, instructions="Send confirmation")
    ],
    edges=[
        Edge("collect", "verify"),
        Edge("verify", "approve", condition=Condition("amount > 1000")),
        Edge("approve", "process"),
        Edge("process", "notify")
    ]
)
```

#### 6. Evaluation & Observability

**Current Limitation**: Limited logging; no performance metrics or quality evaluation.

**Microsoft Agent Framework Capabilities**:
- **Middleware for Telemetry**: Agent Run, Function Calling, and IChatClient middleware enable detailed tracing of every step.
- **Events System**: Workflow and executor lifecycle events provide observability hooks.
- **Integration with OpenTelemetry**: Built‑in support for distributed tracing and metrics export.

**Implementation Strategy**:
- **Agent Run Middleware**: Log input/output of every agent invocation.
- **Function Calling Middleware**: Record tool usage and results for auditing.
- **Workflow Events**: Monitor workflow progression and capture performance metrics.

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
- **Tool Framework**: Leverage Microsoft Agent Framework's tool registry and MCP server integration for ERPNext tools
- **Planning Agent**: Utilize Microsoft Agent Framework's planning middleware for multi‑step reasoning
- **Enhanced Memory**: Use Microsoft Agent Framework's session management and vector memory support

### Phase 2: Advanced Capabilities (Weeks 3-4)
- **Multi‑Agent System**: Specialist agents with orchestration using Microsoft Agent Framework's orchestration middleware
- **Workflow Engine**: State‑based conversation flows using Microsoft Agent Framework's workflow middleware
- **Evaluation Framework**: Metrics collection and tracing with Microsoft Agent Framework's observability features

### Phase 3: Production Readiness (Weeks 5-6)
- **Security Hardening**: Permission checks on all tool calls
- **Performance Optimization**: Caching, batching, rate limiting
- **UI Enhancements**: Workflow visualization, agent selection

### Phase 4: Extensibility & Ecosystem (Weeks 7-8)
- **Plugin System**: Third-party tool and agent contributions
- **Marketplace**: Share agent configurations and workflows
- **API Gateway**: External system integration via REST/Webhook

## Technical Considerations

### Frappe Integration Patterns

1. **Tool Permission Model**: Leverage Frappe's permission system for data access control
2. **Document Lifecycle**: Use Frappe Document hooks for automatic tool execution
3. **Background Job Management**: Extend existing RQ infrastructure for agent workflows
4. **Real-time Updates**: Enhance current WebSocket events for multi-agent coordination

### Performance & Scalability

- **Caching Strategy**: Redis caching for frequent tool results and agent outputs
- **Connection Pooling**: Reusable database connections across agent instances
- **Async Processing**: Asyncio support for concurrent tool execution
- **Load Testing**: Benchmark agent performance under realistic loads

### Security & Compliance

- **Data Isolation**: Ensure agent access respects user permissions and data boundaries
- **Audit Trail**: Complete logging of all agent actions and tool calls
- **Input Validation**: Robust validation of all user inputs and tool parameters
- **Rate Limiting**: Prevent abuse through comprehensive rate limiting

## Use Cases & Examples

### 1. Customer Service Automation
- **Scenario**: Customer requests order status and initiates return
- **Agents Involved**: Order Lookup Agent, Returns Agent, Notification Agent
- **Tools Used**: `get_order_details`, `create_return_request`, `send_email`
- **Business Value**: 80% reduction in manual customer service tasks

### 2. Sales Pipeline Management
- **Scenario**: Sales rep needs help qualifying leads and scheduling follow-ups
- **Agents Involved**: Lead Scoring Agent, Calendar Agent, Email Agent
- **Tools Used**: `analyze_lead_score`, `check_calendar_availability`, `draft_followup_email`
- **Business Value**: 30% increase in lead conversion rate

### 3. Financial Reporting & Analysis
- **Scenario**: Manager requests profitability analysis for product lines
- **Agents Involved**: Data Collection Agent, Analysis Agent, Visualization Agent
- **Tools Used**: `fetch_sales_data`, `calculate_margins`, `generate_chart`
- **Business Value**: Real-time insights without manual data preparation

### 4. Inventory Optimization
- **Scenario**: Warehouse manager needs to identify slow-moving items
- **Agents Involved**: Inventory Analysis Agent, Reorder Agent, Supplier Agent
- **Tools Used**: `analyze_turnover_rates`, `check_supplier_pricing`, `create_purchase_order`
- **Business Value**: 15% reduction in inventory carrying costs

## Conclusion

PH Agent represents a significant foundation for AI-powered automation within ERPNext. By leveraging the Agent Framework's advanced capabilities—planning, tool integration, memory management, multi-agent collaboration, workflow orchestration, and observability—we can transform PH Agent from a sophisticated chatbot into a comprehensive AI automation platform.

The proposed roadmap provides a phased approach that balances immediate business value with long-term architectural vision. Each phase delivers measurable improvements while building toward a system that can handle increasingly complex business processes.

### Next Steps

1. **Phase 1 Implementation**: Begin with tool framework and enhanced memory
2. **Community Engagement**: Gather feedback from early adopters and contributors
3. **Documentation**: Create comprehensive guides for developers and administrators
4. **Pilot Programs**: Deploy advanced features with select users for validation

By embracing the Agent Framework's capabilities, PH Agent can become the premier platform for AI-driven business automation within the Frappe/ERPNext ecosystem, delivering tangible value through intelligent automation, enhanced decision support, and seamless workflow integration.

---

*Document Version: 1.0*  
*Last Updated: 2024-01-15*  
*Maintainer: PH Agent Development Team*