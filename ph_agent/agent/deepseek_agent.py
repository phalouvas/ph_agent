"""Compatibility shim for legacy deepseek_agent imports.

The project has migrated to Microsoft Agent Framework in framework_agent.py.
This module is intentionally kept as a thin forwarder to avoid breaking
external imports during rollout.
"""

from ph_agent.agent.framework_agent import (
	generate_conversation_summary,
	generate_followup_suggestions,
	generate_session_title,
	get_agent_response,
	get_agent_response_stream,
	run_after_approval,
)

__all__ = [
	"generate_conversation_summary",
	"generate_followup_suggestions",
	"generate_session_title",
	"get_agent_response",
	"get_agent_response_stream",
	"run_after_approval",
]
