import importlib
import json

import frappe
from frappe.model.document import Document


class ToolRegistry(Document):
	def validate(self):
		"""Validate Tool Registry document."""
		# 1. Validate tool_name uniqueness
		self._validate_unique_name()
		
		# 2. Validate python_function is importable
		self._validate_function_path()
		
		# 3. Validate parameters_json is valid JSON
		self._validate_parameters_json()
	
	def _validate_unique_name(self):
		"""Ensure tool_name is unique."""
		if not self.tool_name:
			return
		
		existing = frappe.get_list(
			"Tool Registry",
			filters={"tool_name": self.tool_name, "name": ("!=", self.name)},
			pluck="name",
		)
		if existing:
			frappe.throw(
				frappe._("Tool name '{0}' already exists in record {1}").format(
					self.tool_name, existing[0]
				)
			)
	
	def _validate_function_path(self):
		"""Validate python_function path is valid and importable."""
		if not self.python_function:
			return
		
		parts = self.python_function.rsplit('.', 1)
		if len(parts) != 2:
			frappe.throw(
				frappe._("Invalid function path: {0}. Expected format: 'module.submodule.function_name'").format(
					self.python_function
				)
			)
		
		module_path, func_name = parts
		try:
			module = importlib.import_module(module_path)
			func = getattr(module, func_name)
			if not callable(func):
				raise TypeError("Not callable")
		except (ImportError, AttributeError, TypeError) as e:
			frappe.throw(
				frappe._("Cannot import function '{0}': {1}").format(self.python_function, str(e))
			)
	
	def _validate_parameters_json(self):
		"""Validate parameters_json is valid JSON."""
		if not self.parameters_json:
			return
		
		try:
			json.loads(self.parameters_json)
		except json.JSONDecodeError as e:
			frappe.throw(
				frappe._("Invalid JSON in parameters_json: {0}").format(str(e))
			)
	
