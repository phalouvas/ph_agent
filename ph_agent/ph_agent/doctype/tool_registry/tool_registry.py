import importlib
import json
import re

import frappe
from frappe.model.document import Document


# Validation constants for tool names
TOOL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$")
MAX_TOOL_NAME_LENGTH = 140
MAX_DESCRIPTION_LENGTH = 2000


# Safe namespace template for compiling custom/server scripts.
# Provides controlled access to common modules.
# __import__ is included so user scripts can use 'import math' etc.
SAFE_NAMESPACE_TEMPLATE = {
    "__builtins__": {
        "__import__": __import__,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "callable": callable,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "getattr": getattr,
        "hasattr": hasattr,
        "hash": hash,
        "hex": hex,
        "id": id,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "object": object,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    },
    "math": __import__("math"),
    "datetime": __import__("datetime"),
    "json": __import__("json"),
    "random": __import__("random"),
    "re": __import__("re"),
    "decimal": __import__("decimal"),
    "statistics": __import__("statistics"),
    "frappe": frappe,
}


class ToolRegistry(Document):
        def validate(self):
                """Validate Tool Registry document."""
                # 1. Validate tool_name uniqueness
                self._validate_unique_name()

                # 2. Validate script based on script_type
                script_type = getattr(self, "script_type", "Existing Function")
                if script_type == "Existing Function":
                        self._validate_function_path()
                elif script_type == "Custom Script":
                        self._validate_custom_script()

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

        def _validate_custom_script(self):
                """Validate custom_script contains valid Python with a run_tool function."""
                if not self.custom_script:
                        frappe.throw(frappe._("Custom Script is required when Script Type is 'Custom Script'."))

                # Check Python syntax via compile()
                try:
                        compile(self.custom_script, "<custom_script>", "exec")
                except SyntaxError as e:
                        frappe.throw(
                                frappe._("Custom Script contains syntax error at line {0}: {1}").format(
                                        e.lineno, e.msg
                                )
                        )

                # Check that run_tool is defined
                namespace = dict(SAFE_NAMESPACE_TEMPLATE)
                try:
                        exec(self.custom_script, namespace)
                except Exception as e:
                        frappe.throw(
                                frappe._("Custom Script raised an error during validation: {0}").format(str(e))
                        )

                if "run_tool" not in namespace or not callable(namespace["run_tool"]):
                        frappe.throw(
                                frappe._(
                                        "Custom Script must define a top-level callable function named 'run_tool' "
                                        "that serves as the tool entry point."
                                )
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
