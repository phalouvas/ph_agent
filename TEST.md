Here's a step-by-step testing guide to verify everything works:

---

## Testing Guide: Persona Feature

### 1. Verify Persona DocType

| Step | Expected Result |
|------|----------------|
| Go to the Frappe desk → search "Persona" in the awesomebar | Persona list appears |
| Click **New Persona** | Form opens with fields: Persona Name, User, Default Persona, Icon, Color, System Prompt, Default LLM Provider, Temperature, etc. |
| Create a persona named "Business" with system prompt "You are an ERP consultant" | Saved successfully |
| Create another persona named "Personal" with system prompt "You are a friendly assistant" | Saved successfully |
| Try creating a second "Business" persona for the same user | Validation error — unique constraint on `(user, persona_name)` |
| Create 6 personas | Informational warning appears: *"You now have 6 personas. Consider grouping..."* — creation is NOT blocked |

### 2. Verify Persona Selector in Chat UI

| Step | Expected Result |
|------|----------------|
| Open the **AI Chat** page | A persona dropdown selector appears next to the "New Chat" button |
| The dropdown shows your personas (e.g., "Business", "Personal") | Options are populated |
| The default persona is pre-selected | First persona or the one marked `is_default` is shown |

### 3. Verify Persona-Scoped Sessions

| Step | Expected Result |
|------|----------------|
| Select "Business" persona from dropdown | Room list shows only Business sessions (or empty if none exist) |
| Click **New Chat** | A new session is created, assigned to the Business persona |
| Check the Chat Session record in Frappe desk | `persona` field is set to "Business" |
| Send a message: "Analyze our Q4 revenue" | Agent responds with the Business system prompt context |
| Switch to "Personal" persona in the dropdown | Room list now shows only Personal sessions (or empty) |
| Click **New Chat** | New session is assigned to Personal persona |
| Send a message: "Plan a weekend trip" | Agent responds with the Personal system prompt — no mention of Q4 revenue |

### 4. Verify Memory Isolation

| Step | Expected Result |
|------|----------------|
| In **Business** persona, say: "My name is John and I work at Acme Corp" | Memory is extracted and stored with `persona: Business` |
| In **Personal** persona, say: "I love hiking" | Memory is extracted and stored with `persona: Personal` |
| In **Business** persona, ask: "What do you know about me?" | Agent mentions John, Acme Corp — does NOT mention hiking |
| Switch to **Personal** persona, ask: "What do you know about me?" | Agent mentions hiking — does NOT mention John or Acme Corp |

### 5. Verify Preference Isolation

| Step | Expected Result |
|------|----------------|
| In **Business** persona, say: "Please be concise" | Preference `response_style: concise` is stored on the Business persona |
| In **Personal** persona, say: "Explain in detail" | Preference `response_style: detailed` is stored on the Personal persona |
| In **Business** persona, ask a question | Agent responds concisely |
| Switch to **Personal** persona, ask a question | Agent responds in detail |

### 6. Verify Cross-Session Context (Per Persona)

| Step | Expected Result |
|------|----------------|
| In **Business** persona, have 3 long conversations (let them auto-summarize or trigger Summarize) | Summaries are stored |
| Create a new **Business** session | The new session's system prompt includes context from the 3 previous Business sessions |
| Create a new **Personal** session | The new session does NOT include Business summaries |

### 7. Verify Migration (Existing Data)

| Step | Expected Result |
|------|----------------|
| Check that all your old Chat Sessions have a `persona` field set | They should all be assigned to the "Default" persona |
| Check that a "Default" persona exists for your user | It should have `is_default=1` |
| Check that old User Memory records have `persona` set | They should be assigned to "Default" |
| Open the chat page | The "Default" persona is pre-selected, all old sessions appear |

### 8. Verify API Directly (Optional)

```python
# In bench console:
import frappe

# Create a session with a persona
session = frappe.get_doc({
    "doctype": "Chat Session",
    "title": "Test",
    "user": "Administrator",
    "persona": "<your-persona-name>",
    "llm_provider": "<your-provider>",
    "status": "Open",
}).insert()

# Verify persona was set
print(f"Persona: {session.persona}")

# Verify persona defaults were inherited
print(f"System prompt: {session.system_prompt[:100] if session.system_prompt else 'None'}")
```

### 9. Edge Cases to Test

| Scenario | Expected |
|----------|----------|
| Delete a persona that has sessions | Frappe's Link validation prevents deletion (or you need to handle cascade) |
| Create a session without specifying persona | Falls back to the user's default persona |
| Set temperature to 2.0 on a persona | Validation error — must be 0–1.5 |
| Two users with same persona name | Allowed — unique constraint is `(user, persona_name)`, not just `persona_name` |