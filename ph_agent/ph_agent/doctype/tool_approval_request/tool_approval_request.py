import json

import frappe
from frappe.model.document import Document


class ToolApprovalRequest(Document):
	"""DocType for tracking tool approval requests requiring human-in-the-loop approval."""

	def validate(self):
		"""Validate Tool Approval Request."""
		if self.is_new() and self.status != "Pending":
			self.status = "Pending"

	def before_insert(self):
		"""Set default status on insert."""
		self.status = "Pending"

	@frappe.whitelist()
	def approve(self):
		"""
		Approve this tool request.
		Executes the tool and resumes the conversation.
		"""
		if self.status != "Pending":
			frappe.throw(
				frappe._("Tool Approval Request {0} is already {1}. Only pending requests can be approved.").format(
					self.name, self.status
				)
			)

		self.status = "Approved"
		self.approver = frappe.session.user
		self.approval_date = frappe.utils.now_datetime()
		self.save(ignore_permissions=True)
		frappe.db.commit()

		# Enqueue background job to execute tool and resume conversation
		frappe.enqueue(
			"ph_agent.api.agent_jobs._execute_approved_tool",
			approval_name=self.name,
			queue="long",
			timeout=600,
			now=False,
		)

		return {"status": "ok", "approval": self.name}

	@frappe.whitelist()
	def reject(self, reason=None):
		"""
		Reject this tool request.
		Sends a rejection message to the chat session.
		"""
		if self.status != "Pending":
			frappe.throw(
				frappe._("Tool Approval Request {0} is already {1}. Only pending requests can be rejected.").format(
					self.name, self.status
				)
			)

		self.status = "Rejected"
		self.approver = frappe.session.user
		self.approval_date = frappe.utils.now_datetime()
		self.rejection_reason = reason
		self.save(ignore_permissions=True)
		frappe.db.commit()

		# Send rejection message to chat
		self._send_rejection_message()

		return {"status": "ok", "approval": self.name}

	def cancel(self):
		"""Cancel this tool request (e.g., session deleted or generation cancelled)."""
		if self.status != "Pending":
			return

		self.status = "Cancelled"
		self.save(ignore_permissions=True)
		frappe.db.commit()

	def _send_rejection_message(self):
		"""Send a rejection message to the chat session."""
		reason_text = f" Reason: {self.rejection_reason}" if self.rejection_reason else ""
		rejection_content = f"⛔ Tool '{self.tool_name}' was rejected.{reason_text}"

		rejection_msg = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"chat_session": self.chat_session,
				"sender_type": "Agent",
				"message_type": "Agent",
				"content": rejection_content,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		# Publish realtime event for the new rejection message
		frappe.publish_realtime(
			event="new_message",
			message={
				"session": self.chat_session,
				"name": rejection_msg.name,
				"sender_type": "Agent",
				"content": rejection_content,
				"creation": str(rejection_msg.creation),
			},
			room="website",
		)

		# Also publish approval_resolved event
		frappe.publish_realtime(
			event="approval_resolved",
			message={
				"session": self.chat_session,
				"approval_name": self.name,
				"status": "Rejected",
				"tool_name": self.tool_name,
				"reason": self.rejection_reason or "",
			},
			room="website",
		)
