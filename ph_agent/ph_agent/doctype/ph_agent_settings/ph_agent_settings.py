# Copyright (c) 2026, phalouvas and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PHAgentSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		debug_log_level: DF.Literal["DEBUG", "INFO", "WARNING"]
		enable_debug_logging: DF.Check
	# end: auto-generated types

	pass
