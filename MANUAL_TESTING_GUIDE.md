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

### Step 1: Create Tool Registry Record
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

### Step 2: Verify Tool Registry Validation
The Tool Registry should validate:
- Tool name uniqueness
- Python function importability
- JSON validity of parameters_json

### Step 3: Test Tool Loading via Chat
1. Go to **PH Agent → Chat**
2. Create a new chat session or use existing one
3. Send a message that should trigger tool usage, e.g.:
   - "What's the current date and time?"
   - "Can you show me the current time in ISO format?"
   - "Use the datetime tool to show today's date"
   - "What time is it in UTC?"
   - "Show me the full date and time format"

### Step 4: Verify Tool Execution
The agent should:
1. Recognize the tool is available
2. Call the datetime tool with appropriate parameters
3. Return a response like: "Current date/time [User: Administrator, Session: session_name]: 2026-04-21T10:30:45"

**Note**: The actual date/time will be the current system time when the tool is called.

### Step 5: Test Cache Invalidation
1. Edit the Tool Registry record:
   - Change description
   - Disable/enable the tool
2. Send another chat message
3. The tool cache should be invalidated and reloaded

### Step 6: Test Multiple Tool Calls
1. Create additional test tools in Tool Registry
2. Send a message that might require multiple tools
3. Verify the agent can handle multiple tool calls in one response

### Step 7: Test Error Handling
1. Temporarily break the datetime tool (e.g., modify the Python file to raise an exception)
2. Send a message that would use the tool
3. Verify graceful error handling (should return error message in tool result)

## Expected Behavior

### Successful Tool Call
```
User: What's the current date and time?
Agent: [Calls datetime tool]
Agent: The current date and time is Tuesday, April 21, 2026 at 10:30:45 AM UTC.
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
2. The cache should be automatically invalidated
3. Try using the tool again to verify changes take effect

### Step 6: Test Context Injection
Verify that context is injected correctly:
- User name should appear in tool output
- Session name should appear in tool output
- Frappe session should be available in context

### Step 7: Test Multiple Tools (Optional)
1. Create additional tool records for testing
2. Verify all enabled tools are loaded
3. Test tool selection by the agent

## Expected Results

### Successful Implementation
- Tools are loaded from Tool Registry
- Tools are registered with Microsoft Agent Framework
- Agent can call tools during conversation
- Context (user, session) is injected into tool calls
- Cache is invalidated when Tool Registry changes

### Error Handling
- Invalid Python function paths show validation errors
- Disabled tools are not loaded
- Tool errors are logged but don't crash the agent

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
   - Verify Python function path is correct (should be `ph_agent.agent.tools.datetime_tool.show_datetime_tool`)
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

- [ ] Tool Registry record created successfully
- [ ] Tool validation works (unique name, importable function)
- [ ] Agent loads tools from Tool Registry
- [ ] Tool is called during conversation
- [ ] Context (user, session) appears in tool output
- [ ] Cache invalidates on Tool Registry changes
- [ ] Multiple tools can be loaded simultaneously
- [ ] Disabled tools are not loaded
- [ ] Error handling works for invalid tools

## Notes
- The streaming API (`get_agent_response_stream`) does not support tools yet
- Tools only work with the non-streaming API (`get_agent_response`)
- Tool approval workflow (`requires_approval`) is implemented but not fully tested
- Performance: Tools are cached for 1 hour, invalidated on Tool Registry changes