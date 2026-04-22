# Manual Testing Guide for ToolManager Implementation

## Overview
The ToolManager has been implemented to load tools from the Tool Registry and register them with the Microsoft Agent Framework. This guide will help you test the implementation manually in the Frappe GUI.

## Important Fixes Applied

### Fix 1: "Hosted tools are not supported with the ChatCompletions API" error
Fixed by:
1. Using `agent_framework` package consistently (instead of mixing `agent_framework` and `agents` packages)
2. Using `OpenAIChatClient` from `agent_framework.openai` instead of `OpenAIChatCompletionsModel` from `agents.models.openai_chatcompletions`
3. Using `OpenAIChatOptions` for temperature and max_tokens configuration instead of `ModelSettings`
4. Passing `client` parameter to `Agent` instead of `model` parameter
5. Using `agent.run(messages=...)` instead of `Runner.run(agent, input=...)`

### Fix 2: "'dict' object has no attribute 'role'" error
Fixed by converting dictionaries to `Message` objects from `agent_framework`:
```python
# Before (wrong):
messages = [{"role": "user", "content": "Hello"}]

# After (correct):
from agent_framework import Message
messages = [Message(role="user", contents=["Hello"])]
```

### Fix 3: Character splitting in Message serialization
Fixed by using list format for `contents`:
```python
# Before (causes character splitting):
Message(role="user", contents="Hello")

# After (correct):
Message(role="user", contents=["Hello"])
```

### Fix 4: "Error code: 404" with DeepSeek API
Fixed by using standard OpenAI client instead of `agent_framework` for `get_agent_response()`:
- `agent_framework` uses Azure-like format that DeepSeek rejects
- Standard OpenAI client uses correct OpenAI format that DeepSeek accepts
- Tool execution is now implemented in `get_agent_response()` using direct `FunctionTool` calls

### Fix 5: Tool execution implementation
Tools are now properly executed when called by the LLM:
1. LLM returns tool calls in response
2. ToolManager loads matching `FunctionTool` objects
3. Tools are executed with provided arguments using direct function call: `tool(**args)`
4. Tool results are sent back to LLM for final response generation

## Prerequisites
1. Frappe bench environment running
2. PH Agent app installed
3. LLM Provider configured with API key
4. **Important**: Restart bench server after implementing changes:
   ```bash
   bench restart
   ```

## Test Steps

### Step 1: Create Tool Registry Records

#### 1.1 Create DateTime Tool Record
1. Go to **PH Agent → Tool Registry**
2. Click **New**
3. Fill in the following details:
   - **Tool Name**: `show_datetime`
   - **Description**: `Shows the current date and time. Useful for testing tool registration and verifying the system is working.`
   - **Python Function**: `ph_agent.agent.tools.datetime_tool.show_datetime_tool`
   - **Parameters JSON**: `{}` (leave empty or use `{}`)
   - **Is Enabled**: Checked ✓
   - **Requires Approval**: Unchecked (for testing)
4. Click **Save**

#### 1.2 Create Calculator Tool Record
1. Go to **PH Agent → Tool Registry**
2. Click **New**
3. Fill in the following details:
   - **Tool Name**: `calculate`
   - **Description**: `Performs mathematical calculations. Supports basic arithmetic, percentages, and common math functions.`
   - **Python Function**: `ph_agent.agent.tools.calculator_tool.calculate_tool`
   - **Parameters JSON**: `{}` (leave empty or use `{}`)
   - **Is Enabled**: Checked ✓
   - **Requires Approval**: Unchecked (for testing)
4. Click **Save**

### Step 2: Verify Tool Registry Validation
The Tool Registry should validate:
- Tool name uniqueness
- Python function importability
- JSON validity of parameters_json

### Step 3: Test Tool Loading via Chat
1. Go to **PH Agent → Chat**
2. Create a new chat session or use existing one
3. Send messages that should trigger different tools, e.g.:

   **For DateTime Tool:**
   - "What's the current date and time?"
   - "Can you show me the current time in ISO format?"
   - "Use the datetime tool to show today's date"
   - "What time is it in UTC?"
   - "Show me the full date and time format"

   **For Calculator Tool:**
   - "Calculate 15 + 27"
   - "What is 20% of 150?"
   - "Multiply 12 by 8"
   - "Calculate the square root of 64"
   - "What is 100 divided by 4?"
   - "Calculate 5 to the power of 3"
   - "Subtract 42 from 100"

### Step 4: Verify Tool Execution
The agent should:
1. Recognize which tool is appropriate for the query
2. Call the correct tool with appropriate parameters
3. Return responses like:

   **For DateTime Tool:**
   "Current date/time [User: Administrator, Session: session_name]: 2026-04-21T10:30:45"

   **For Calculator Tool:**
   "15 + 27 = 42 [User: Administrator, Session: session_name]"
   "20% of 150 = 30.0 [User: Administrator, Session: session_name]"
   "√64 = 8.0 [User: Administrator, Session: session_name]"

**Note**: The actual date/time will be the current system time when the tool is called.

### Step 5: Test Cache Invalidation
1. Edit the Tool Registry record:
   - Change description
   - Disable/enable the tool
2. Send another chat message
3. The tool cache should be invalidated and reloaded

### Step 6: Test Multiple Tool Calls
1. With both datetime and calculator tools created
2. Send messages that test tool selection:
   - "What time is it and also calculate 25 * 4" (should use both tools)
   - "Calculate 10 + 20 and show me the date" (should use both tools)
   - "What's 15% of 200?" (should use calculator only)
   - "What's today's date?" (should use datetime only)
3. Verify the agent can:
   - Select the correct tool(s) for each query
   - Handle multiple tool calls in one response when appropriate
   - Provide clear responses showing which tools were used

### Step 7: Test Error Handling
1. Temporarily break the datetime tool (e.g., modify the Python file to raise an exception)
2. Send a message that would use the tool
3. Verify graceful error handling (should return error message in tool result)

## Expected Behavior

### Successful Tool Calls

**DateTime Tool:**
```
User: What's the current date and time?
Agent: [Calls datetime tool]
Agent: The current date and time is Tuesday, April 21, 2026 at 10:30:45 AM UTC.
```

**Calculator Tool:**
```
User: Calculate 15 + 27
Agent: [Calls calculator tool]
Agent: 15 + 27 = 42
```

**Percentage Calculation:**
```
User: What is 20% of 150?
Agent: [Calls calculator tool]
Agent: 20% of 150 = 30.0
```

**Multiple Tools:**
```
User: What time is it and calculate 25 * 4
Agent: [Calls datetime tool, then calculator tool]
Agent: Current time is 10:30:45. 25 * 4 = 100
```

### Tool Not Found
```
User: Use a non-existent tool
Agent: [Attempts to call tool]
Agent: Error: Tool 'non_existent_tool' not found
```

### Tool Execution Error
```
User: Use datetime tool with invalid format
Agent: [Calls datetime tool with invalid args]
Agent: The datetime tool returned an error: Invalid format specified
```

```
User: Calculate 10 divided by 0
Agent: [Calls calculator tool]
Agent: Error: Division by zero is not allowed
```

## Troubleshooting

### Common Issues

#### 1. "Module not found" error when saving Tool Registry
- Check that the Python module path is correct
- Verify the function exists in the module
- Ensure the module is in the Python path

#### 2. Tools not appearing in chat responses
- Check if tools are enabled in Tool Registry
- Verify LLM Provider supports function calling
- Check browser console for JavaScript errors
- Restart bench server: `bench restart`

#### 3. "Error code: 404" with DeepSeek
- This is now fixed by using standard OpenAI client
- Ensure you're using the latest code with the fix

### 5. "Object of type method is not JSON serializable"
- **Cause**: Using `tool.parameters` (a method) instead of `tool.parameters()` (a dictionary)
- **Fix**: Call the method: `tool.parameters()` not `tool.parameters`
- **Location**: In `deepseek_agent.py` line 191, changed to `"parameters": tool.parameters() or {}`

### 6. Tool calls detected but not executed
- The implementation now executes tools properly
- Check that `FunctionTool` objects are being loaded correctly
- Verify tool execution code is in place

### Debug Logs
Check Frappe error logs for tool-related errors:
```bash
bench --site [site-name] logs
```

### Manual Verification
To manually verify tool loading:
```python
from ph_agent.agent.tools.tool_manager import ToolManager
tools = ToolManager.get_tools()
print(f"Loaded {len(tools)} tools")
for tool in tools:
    print(f"- {tool.name}: {tool.description}")
```

You should see both tools loaded:
```
Loaded 2 tools
- show_datetime: Shows the current date and time...
- calculate: Performs mathematical calculations...
```

2. The cache should be automatically invalidated
3. Try using the tools again to verify changes take effect

### Step 6: Test Context Injection
Verify that context is injected correctly:
- User name should appear in tool output
- Session name should appear in tool output
- Frappe session should be available in context

### Step 7: Test Tool Selection Logic
1. With both tools enabled, test how the agent selects between them:
   - **Clear tool selection**: "Calculate 15 + 20" → Should use calculator
   - **Clear tool selection**: "What's the time?" → Should use datetime
   - **Ambiguous queries**: "What's today?" → May use datetime or ask for clarification
   - **Combined queries**: "Time and calculate 5*5" → Should use both tools

2. Test edge cases:
   - Disable one tool and verify it's not loaded
   - Test with invalid parameters
   - Test error handling for both tools

## Expected Results

### Successful Implementation
- Both tools are loaded from Tool Registry
- Tools are registered with Microsoft Agent Framework
- Agent can select appropriate tool based on query
- Agent can handle multiple tools in one conversation
- Context (user, session) is injected into tool calls
- Cache is invalidated when Tool Registry changes

### Error Handling
- Invalid Python function paths show validation errors
- Disabled tools are not loaded
- Tool errors are logged but don't crash the agent
- Division by zero and other math errors are handled gracefully
- Invalid parameters return helpful error messages

## Troubleshooting

### Common Issues

1. **TypeError: invalidate_tool_cache() takes 0 positional arguments but 2 were given**
   - **Error**: Hook function doesn't accept required arguments
   - **Solution**: Restart bench server after fix: `bench restart`
   - **Cause**: Hook functions must accept `(doc, method)` parameters

2. **ModuleNotFoundError when saving Tool Registry**
   - **Error**: `No module named 'ph_agent.agent.tools.tool_manager.ToolManager'; 'ph_agent.agent.tools.tool_manager' is not a package`
   - **Solution**: Restart bench server: `bench restart`
   - **Cause**: Old code cached in memory, hook path needs to be reloaded

3. **Tool not found in Tool Registry**
   - Check if tool is enabled (`is_enabled = 1`)
   - Verify Python function path is correct:
     - DateTime: `ph_agent.agent.tools.datetime_tool.show_datetime_tool`
     - Calculator: `ph_agent.agent.tools.calculator_tool.calculate_tool`
   - Check Frappe logs for import errors

4. **Agent doesn't use tool**
   - Check LLM provider supports function calling
   - Verify system prompt doesn't restrict tool usage
   - Test with explicit tool invocation

5. **Cache not updating**
   - Check `doc_events` in hooks.py
   - Manually invalidate cache: `ToolManager.invalidate_cache()`
   - Restart bench if needed

6. **Context not injected**
   - Verify `session_name` is passed to `ToolManager.get_tools()`
   - Check `frappe.session.user` is available
   - Look for context in tool output (should show `[User: ..., Session: ...]` in the response)

7. **"Hosted tools are not supported with the ChatCompletions API" error**
   - **Error**: This occurs when mixing imports from `agent_framework` and `agents` packages
   - **Solution**: Ensure all imports are from `agent_framework` package only
   - **Check**: Verify `deepseek_agent.py` uses:
     - `from agent_framework import Agent` (not `from agents import Agent, Runner`)
     - `from agent_framework.openai import OpenAIChatClient, OpenAIChatOptions` (not `from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel`)
     - `Agent(client=chat_client, ...)` (not `Agent(model=model, ...)`)
     - `OpenAIChatOptions(temperature=..., max_tokens=...)` (not `ModelSettings(...)`)
     - `agent.run(messages=...)` (not `Runner.run(agent, input=...)`)
   - **Cause**: Inconsistent SDK usage causes tools to be classified as "Hosted tools" instead of "Function tools"

8. **"type object 'Runner' has no attribute 'run'" error**
   - **Error**: `Runner.run()` doesn't exist in `agent_framework`
   - **Solution**: Use `agent.run(messages=...)` instead of `Runner.run(agent, input=...)`
   - **Check**: Verify `deepseek_agent.py` uses:
     - `agent.run(messages=history)` for main agent
     - `title_agent.run(messages=prompt)` for title generation
     - `summary_agent.run(messages=conversation_text)` for summarization
     - `suggestions_agent.run(messages=context)` for suggestions
   - **Cause**: `agent_framework.Agent` has a `run()` method, but `Runner` is a class for workflows, not a function

9. **"'dict' object has no attribute 'role'" error**
   - **Error**: This occurs when agent_framework expects Message objects but receives dictionaries
   - **Solution**: Ensure all messages passed to agent.run() are Message objects, not dictionaries
   - **Check**: Verify `deepseek_agent.py`:
     - Imports `Message` from `agent_framework`: `from agent_framework import Agent, Message`
     - Converts message dictionaries to Message objects in `get_agent_response()`:
       - `Message(role="user", contents="message")` instead of `{"role": "user", "content": "message"}`
       - `Message(role="system", contents="instructions")` instead of `{"role": "system", "content": "instructions"}`
       - `Message(role="assistant", contents="response")` instead of `{"role": "assistant", "content": "response"}`
     - Wraps strings in Message objects in other functions:
       - `Message(role="user", contents=prompt)` instead of just `prompt` (string) in `generate_conversation_title()`
       - `Message(role="user", contents=conversation_text)` instead of just `conversation_text` in `generate_conversation_summary()`
       - `Message(role="user", contents=context)` instead of just `context` in `generate_followup_suggestions()`
   - **Cause**: `agent_framework._types.prepend_instructions_to_messages` tries to access `.role` and `.text` attributes on message objects, which dictionaries don't have

10. **"Error code: 404" or "service failed to complete the prompt" error**
   - **Error**: This occurs when `agent_framework` serializes messages incorrectly, causing API endpoint not found errors
   - **Solution**: Ensure all `Message` objects use list format for `contents` parameter
   - **Check**: Verify `deepseek_agent.py` uses list format for all `Message` creations:
     - `Message(role="user", contents=["message"])` instead of `Message(role="user", contents="message")`
     - `Message(role="system", contents=["instructions"])` instead of `Message(role="system", contents="instructions")`
     - `Message(role="assistant", contents=["response"])` instead of `Message(role="assistant", contents="response")`
   - **Cause**: When a string is passed to `Message(contents=...)`, `agent_framework` splits it into individual characters, creating invalid API requests that result in 404 errors
   - **Note**: The `.text` property works correctly with both formats, but serialization to API calls requires list format

## Verification Checklist

### Basic Functionality
- [ ] DateTime Tool Registry record created successfully
- [ ] Calculator Tool Registry record created successfully
- [ ] Tool validation works (unique name, importable function)
- [ ] Agent loads both tools from Tool Registry
- [ ] Tools are called during conversation
- [ ] Context (user, session) appears in tool output
- [ ] Cache invalidates when Tool Registry changes

### Multiple Tool Testing
- [ ] Both tools can be loaded simultaneously
- [ ] Agent selects correct tool for date/time queries
- [ ] Agent selects correct tool for math queries
- [ ] Agent can handle queries requiring both tools
- [ ] Disabled tools are not loaded

### Error Handling
- [ ] Error handling works for invalid tools
- [ ] Math errors (division by zero) are handled gracefully
- [ ] Invalid parameters return helpful error messages
- [ ] Tool execution errors don't crash the agent

### Advanced Testing
- [ ] Test with different parameter combinations
- [ ] Test tool selection with ambiguous queries
- [ ] Verify cache invalidation after tool edits
- [ ] Test with one tool disabled

## Notes
- The streaming API (`get_agent_response_stream`) does not support tools yet
- Tools only work with the non-streaming API (`get_agent_response`)
- Tool approval workflow (`requires_approval`) is implemented but not fully tested
- Performance: Tools are cached for 1 hour, invalidated on Tool Registry changes