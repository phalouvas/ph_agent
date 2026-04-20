# PH Agent Implementation Prompt Templates

This document contains prompt templates to use when asking the AI agent to prepare implementation plans for each phase of PH Agent development.

## General Guidelines

When using these prompts:
1. **Copy and paste** the entire prompt into the chat interface
2. **Replace `[PHASE_NUMBER]`** with the phase number (1, 2, 3, or 4)
3. **Replace `[PHASE_NAME]`** with the phase name from IMPLEMENTATION.md
4. **Replace `[PHASE_DESCRIPTION]`** with a brief description of the phase
5. **Review** the generated plan before starting implementation

## Generic Prompt Template

Use this template for any phase by filling in the placeholders:

```
Act as a senior software architect and developer for the PH Agent Frappe application. I need you to prepare a detailed implementation plan for Phase [PHASE_NUMBER]: [PHASE_NAME].

**Context:**
- Project: PH Agent (Frappe app for AI agent chatbots in ERPNext)
- Current status: Baseline features implemented (see IMPLEMENTATION.md)
- Phase [PHASE_NUMBER] goal: [PHASE_DESCRIPTION]
- Reference document: /workspace/development/v16/apps/ph_agent/IMPLEMENTATION.md

**Requirements for your implementation plan:**

1. **Break down into small steps**: Each step should be a single, atomic task that can be completed in 1-4 hours of focused work.

2. **Include testing checkpoints**: After each major component or logical grouping of steps, add a "TESTING CHECKPOINT" that asks me to manually test the functionality before proceeding. Do NOT create automated unit tests - I want manual verification only.

3. **Prioritize dependencies**: Order steps so that dependencies are built first.

4. **Be specific**: For each step, include:
   - What files need to be created/modified
   - What functions/classes need to be implemented
   - Any configuration changes required
   - Expected behavior/outcome

5. **Consider existing codebase**: Leverage existing patterns from the codebase (Frappe conventions, existing agent framework usage, etc.)

6. **Include integration points**: Note how the new functionality integrates with existing components.

**Output format:**
- Provide a numbered list of steps
- Group related steps under subheadings
- Mark testing checkpoints with ✅ **TESTING CHECKPOINT**
- Include estimated time for each step (in hours)
- For complex steps, break them down further with bullet points

**Important:** Do not actually write any code or create any files. Just provide the implementation plan. I will implement each step manually based on your plan.

Now, please prepare the implementation plan for Phase [PHASE_NUMBER]: [PHASE_NAME].
```

## Phase-Specific Prompts

### Phase 1: Foundation
**Use this prompt for Phase 1 (Tool Framework, Planning Agent, Enhanced Memory):**

```
Act as a senior software architect and developer for the PH Agent Frappe application. I need you to prepare a detailed implementation plan for Phase 1: Foundation.

**Context:**
- Project: PH Agent (Frappe app for AI agent chatbots in ERPNext)
- Current status: Baseline features implemented (see IMPLEMENTATION.md)
- Phase 1 goal: Implement the foundational components: Tool Framework, Planning Agent, and Enhanced Memory
- Reference document: /workspace/development/v16/apps/ph_agent/IMPLEMENTATION.md
- Phase 1 tasks from IMPLEMENTATION.md:
  1.1 Tool Framework: Enable the agent to call ERPNext functions via a registry of whitelisted tools
  1.2 Planning Agent: Add multi-step reasoning and explicit task decomposition
  1.3 Enhanced Memory: Move beyond simple conversation history to vector-based semantic memory

**Requirements for your implementation plan:**

1. **Break down into small steps**: Each step should be a single, atomic task that can be completed in 1-4 hours of focused work.

2. **Include testing checkpoints**: After each major component or logical grouping of steps, add a "TESTING CHECKPOINT" that asks me to manually test the functionality before proceeding. Do NOT create automated unit tests - I want manual verification only.

3. **Prioritize dependencies**: Tool Framework must be completed before Planning Agent (agents need tools to plan with). Enhanced Memory can be developed in parallel.

4. **Be specific**: For each step, include:
   - What files need to be created/modified
   - What functions/classes need to be implemented
   - Any configuration changes required
   - Expected behavior/outcome

5. **Consider existing codebase**: Leverage existing patterns from:
   - `ph_agent/agent/deepseek_agent.py` for agent framework integration
   - `ph_agent/api/chat.py` for API endpoint patterns
   - `ph_agent/ph_agent/doctype/` for Frappe DocType examples
   - Existing PDF extraction tool in `ph_agent/utils/pdf.py`

6. **Include integration points**: Note how the new functionality integrates with existing chat UI, agent responses, and session management.

**Output format:**
- Provide a numbered list of steps
- Group related steps under subheadings (Tool Framework, Planning Agent, Enhanced Memory)
- Mark testing checkpoints with ✅ **TESTING CHECKPOINT**
- Include estimated time for each step (in hours)
- For complex steps, break them down further with bullet points

**Important:** Do not actually write any code or create any files. Just provide the implementation plan. I will implement each step manually based on your plan.

Now, please prepare the implementation plan for Phase 1: Foundation.
```

### Phase 2: Advanced Capabilities
**Use this prompt for Phase 2 (Multi-Agent System, Workflow Engine, Evaluation & Observability):**

```
Act as a senior software architect and developer for the PH Agent Frappe application. I need you to prepare a detailed implementation plan for Phase 2: Advanced Capabilities.

**Context:**
- Project: PH Agent (Frappe app for AI agent chatbots in ERPNext)
- Current status: Phase 1 completed, Tool Framework, Planning Agent, and Enhanced Memory implemented
- Phase 2 goal: Implement advanced capabilities: Multi-Agent System, Workflow Engine, and Evaluation & Observability
- Reference document: /workspace/development/v16/apps/ph_agent/IMPLEMENTATION.md
- Phase 2 tasks from IMPLEMENTATION.md:
  2.1 Multi-Agent System: Enable specialist agents (sales, support, accounting) with orchestration
  2.2 Workflow Engine: Support state-based guided conversations with conditional branching
  2.3 Evaluation & Observability: Comprehensive monitoring, tracing, and quality assessment

**Requirements for your implementation plan:**

1. **Break down into small steps**: Each step should be a single, atomic task that can be completed in 1-4 hours of focused work.

2. **Include testing checkpoints**: After each major component or logical grouping of steps, add a "TESTING CHECKPOINT" that asks me to manually test the functionality before proceeding. Do NOT create automated unit tests - I want manual verification only.

3. **Prioritize dependencies**: Multi-Agent System depends on Tool Framework being stable. Workflow Engine can be developed in parallel with Evaluation & Observability.

4. **Be specific**: For each step, include:
   - What files need to be created/modified
   - What functions/classes need to be implemented
   - Any configuration changes required
   - Expected behavior/outcome

5. **Consider existing codebase**: Build upon Phase 1 components:
   - Tool Framework for agent tool integration
   - Planning Agent for multi-step reasoning
   - Enhanced Memory for context management

6. **Include integration points**: Note how the new functionality integrates with existing Tool Framework, chat UI, and agent orchestration.

**Output format:**
- Provide a numbered list of steps
- Group related steps under subheadings (Multi-Agent System, Workflow Engine, Evaluation & Observability)
- Mark testing checkpoints with ✅ **TESTING CHECKPOINT**
- Include estimated time for each step (in hours)
- For complex steps, break them down further with bullet points

**Important:** Do not actually write any code or create any files. Just provide the implementation plan. I will implement each step manually based on your plan.

Now, please prepare the implementation plan for Phase 2: Advanced Capabilities.
```

### Phase 3: Production Readiness
**Use this prompt for Phase 3 (Security Hardening, Performance Optimization, Deployment Automation):**

```
Act as a senior software architect and developer for the PH Agent Frappe application. I need you to prepare a detailed implementation plan for Phase 3: Production Readiness.

**Context:**
- Project: PH Agent (Frappe app for AI agent chatbots in ERPNext)
- Current status: Phase 2 completed, advanced capabilities implemented
- Phase 3 goal: Ensure production readiness through Security Hardening, Performance Optimization, and Deployment Automation
- Reference document: /workspace/development/v16/apps/ph_agent/IMPLEMENTATION.md
- Phase 3 tasks from IMPLEMENTATION.md:
  3.1 Security Hardening: Ensure all agent actions respect Frappe permissions and prevent abuse
  3.2 Performance Optimization: Optimize agent response times and resource usage
  3.3 Deployment Automation: Streamline installation and updates

**Requirements for your implementation plan:**

1. **Break down into small steps**: Each step should be a single, atomic task that can be completed in 1-4 hours of focused work.

2. **Include testing checkpoints**: After each major component or logical grouping of steps, add a "TESTING CHECKPOINT" that asks me to manually test the functionality before proceeding. Do NOT create automated unit tests - I want manual verification only.

3. **Prioritize dependencies**: Security Hardening should be applied to existing components. Performance Optimization can be done in parallel with Deployment Automation.

4. **Be specific**: For each step, include:
   - What files need to be created/modified
   - What functions/classes need to be implemented
   - Any configuration changes required
   - Expected behavior/outcome

5. **Consider existing codebase**: Apply security and performance improvements to:
   - Tool Framework and tool execution
   - Agent responses and memory management
   - Chat UI and real-time components

6. **Include integration points**: Note how security, performance, and deployment changes integrate with the existing Frappe ecosystem.

**Output format:**
- Provide a numbered list of steps
- Group related steps under subheadings (Security Hardening, Performance Optimization, Deployment Automation)
- Mark testing checkpoints with ✅ **TESTING CHECKPOINT**
- Include estimated time for each step (in hours)
- For complex steps, break them down further with bullet points

**Important:** Do not actually write any code or create any files. Just provide the implementation plan. I will implement each step manually based on your plan.

Now, please prepare the implementation plan for Phase 3: Production Readiness.
```

### Phase 4: Extensibility & Ecosystem
**Use this prompt for Phase 4 (Plugin System, Marketplace, API Gateway):**

```
Act as a senior software architect and developer for the PH Agent Frappe application. I need you to prepare a detailed implementation plan for Phase 4: Extensibility & Ecosystem.

**Context:**
- Project: PH Agent (Frappe app for AI agent chatbots in ERPNext)
- Current status: Phase 3 completed, production-ready system
- Phase 4 goal: Create extensibility features and ecosystem: Plugin System, Marketplace, and API Gateway
- Reference document: /workspace/development/v16/apps/ph_agent/IMPLEMENTATION.md
- Phase 4 tasks from IMPLEMENTATION.md:
  4.1 Plugin System: Allow third-party developers to add custom tools and agents
  4.2 Marketplace: Central repository for sharing and discovering plugins
  4.3 API Gateway: Expose agent capabilities to external systems via REST/Webhook

**Requirements for your implementation plan:**

1. **Break down into small steps**: Each step should be a single, atomic task that can be completed in 1-4 hours of focused work.

2. **Include testing checkpoints**: After each major component or logical grouping of steps, add a "TESTING CHECKPOINT" that asks me to manually test the functionality before proceeding. Do NOT create automated unit tests - I want manual verification only.

3. **Prioritize dependencies**: Plugin System must be built before Marketplace. API Gateway can be developed in parallel.

4. **Be specific**: For each step, include:
   - What files need to be created/modified
   - What functions/classes need to be implemented
   - Any configuration changes required
   - Expected behavior/outcome

5. **Consider existing codebase**: Build upon existing:
   - Tool Framework for plugin tool integration
   - Agent system for plugin agent registration
   - Frappe's web framework for API endpoints

6. **Include integration points**: Note how plugins, marketplace, and API integrate with the core PH Agent system.

**Output format:**
- Provide a numbered list of steps
- Group related steps under subheadings (Plugin System, Marketplace, API Gateway)
- Mark testing checkpoints with ✅ **TESTING CHECKPOINT**
- Include estimated time for each step (in hours)
- For complex steps, break them down further with bullet points

**Important:** Do not actually write any code or create any files. Just provide the implementation plan. I will implement each step manually based on your plan.

Now, please prepare the implementation plan for Phase 4: Extensibility & Ecosystem.
```

## Usage Instructions

1. **Select the appropriate prompt** for the phase you want to implement
2. **Copy the entire prompt** (from the code block)
3. **Paste into the PH Agent chat interface**
4. **Wait for the AI agent** to generate the implementation plan
5. **Review the plan** and ask for clarifications if needed
6. **Implement steps manually**, following the plan and testing checkpoints

## Customization Tips

- **Add specific requirements**: Modify the prompt to include any additional constraints or preferences
- **Adjust time estimates**: Change the "1-4 hours" guideline based on your available time
- **Include references**: Add links to specific documentation or code examples you want the AI to consider
- **Specify testing methods**: Describe exactly how you want to test each component (manual UI testing, API testing, etc.)

---

*Last Updated: 2026-04-20*  
*Maintainer: PH Agent Development Team*
```

*Note: These prompts are designed to work with the PH Agent's AI chat interface. The AI will generate implementation plans but will not execute code or make changes to the codebase.*