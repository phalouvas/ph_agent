import frappe
from frappe.model.document import Document


class UserTokenUsage(Document):
	"""Tracks per-user token consumption and cost across all sessions.

	One record per user (autoname = user field). Created on first chat page
	visit and updated after every agent response.
	"""

	def has_permission(self, ptype: str | None = None, user: str | None = None) -> bool:
		"""Restrict PH Agent User to only see their own record.

		System Manager can see all records.
		"""
		if not user:
			user = frappe.session.user

		# System Manager has full access
		if "System Manager" in frappe.get_roles(user):
			return True

		# PH Agent User can only see their own record
		if ptype == "read":
			return self.user == user

		# Other operations (write, create, delete) not allowed for PH Agent User
		return False

	@staticmethod
	def get_or_create_for_user(user: str) -> str:
		"""Get existing User Token Usage record for user, or create one.

		Args:
			user: Frappe User name.

		Returns:
			The name (user) of the User Token Usage record.
		"""
		if frappe.db.exists("User Token Usage", user):
			return user

		doc = frappe.get_doc({
			"doctype": "User Token Usage",
			"user": user,
			"total_input_tokens": 0,
			"total_output_tokens": 0,
			"total_cost": 0,
			"last_updated": frappe.utils.now_datetime(),
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name
