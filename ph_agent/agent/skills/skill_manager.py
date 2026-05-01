"""
SkillManager for PH Agent.

Manages loading, caching, and conversion of Skill Registry DocType records
into agent_framework.Skill objects for use with SkillsProvider.
"""

import importlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Optional

import frappe
from agent_framework import Skill, SkillResource, SkillScript
from ph_agent.utils.debug_logger import debug_log

logger = logging.getLogger(__name__)

class SkillManager:
	"""Manager for loading skills from the Skill Registry DocType."""

	@classmethod
	def get_code_skills(cls) -> list[Skill]:
		"""
		Get all enabled code-defined skills from the Skill Registry.

		Returns:
			List of agent_framework.Skill objects ready to be passed to
			SkillsProvider constructor.
		"""
		# Load from database
		skills = cls._load_skills_from_db()

		debug_log(
			"SkillManager: loaded skills",
			f"Total: {len(skills)}, Names: {[s.name for s in skills]}",
		)
		logger.info("Successfully loaded %d skills from Skill Registry", len(skills))
		return skills

	@classmethod
	def _load_skills_from_db(cls) -> list[Skill]:
		"""Load enabled skills from the Skill Registry database."""
		skills: list[Skill] = []

		# Get all enabled skills
		skill_records = frappe.get_all(
			"Skill Registry",
			filters={"is_enabled": 1},
			fields=["name", "skill_name", "description", "content"],
		)

		logger.info("Loading %d enabled skills from Skill Registry", len(skill_records))

		for record in skill_records:
			try:
				skill = cls._build_skill(record)
				skills.append(skill)
				logger.debug("Successfully built skill: %s", record["skill_name"])
			except Exception as e:
				logger.error(
					"Failed to build skill '%s': %s", record.get("skill_name", record["name"]), str(e)
				)

		logger.info("Successfully built %d/%d skills", len(skills), len(skill_records))
		return skills

	@classmethod
	def _build_skill(cls, record: dict[str, Any]) -> Skill:
		"""
		Build a Skill object from a Skill Registry DocType record.

		Args:
			record: Skill Registry document as dictionary with skill_name,
				description, content fields.

		Returns:
			agent_framework.Skill instance with resources and scripts loaded
			from child tables.
		"""
		skill_name = record["skill_name"]
		description = record["description"] or ""
		content = record["content"] or ""

		# Load resources from child table
		resources = cls._load_resources(skill_name)

		# Load scripts from child table
		scripts = cls._load_scripts(skill_name)

		return Skill(
			name=skill_name,
			description=description,
			content=content,
			resources=resources,
			scripts=scripts,
		)

	@classmethod
	def _load_resources(cls, skill_name: str) -> list[SkillResource]:
		"""
		Load SkillResource objects from the Skill Registry's child table.

		Args:
			skill_name: Name of the parent skill.

		Returns:
			List of SkillResource instances.
		"""
		resources: list[SkillResource] = []

		resource_records = frappe.get_all(
			"Skill Resource",
			filters={"parent": skill_name, "parenttype": "Skill Registry"},
			fields=["resource_name", "description", "resource_type", "content", "python_function"],
			order_by="idx asc",
		)

		for record in resource_records:
			try:
				resource = cls._build_resource(record)
				if resource:
					resources.append(resource)
			except Exception as e:
				logger.error(
					"Failed to build resource '%s' for skill '%s': %s",
					record.get("resource_name", "?"),
					skill_name,
					str(e),
				)

		return resources

	@classmethod
	def _build_resource(cls, record: dict[str, Any]) -> Optional[SkillResource]:
		"""
		Build a SkillResource from a child table record.

		Args:
			record: Skill Resource child table record.

		Returns:
			SkillResource instance or None if build fails.
		"""
		name = record["resource_name"]
		description = record.get("description")
		resource_type = record.get("resource_type", "Static Text")

		if resource_type == "Static Text":
			content = record.get("content", "")
			return SkillResource(name=name, description=description, content=content)

		elif resource_type == "Dynamic Function":
			python_function = record.get("python_function", "")
			if not python_function:
				logger.error("Dynamic Function resource '%s' has no python_function", name)
				return None

			try:
				func = cls._import_callable(python_function)
				return SkillResource(name=name, description=description, function=func)
			except (ImportError, AttributeError, ValueError) as e:
				logger.error(
					"Failed to import function '%s' for resource '%s': %s",
					python_function,
					name,
					str(e),
				)
				return None

		return None

	@classmethod
	def _load_scripts(cls, skill_name: str) -> list[SkillScript]:
		"""
		Load SkillScript objects from the Skill Registry's child table.

		Args:
			skill_name: Name of the parent skill.

		Returns:
			List of SkillScript instances.
		"""
		scripts: list[SkillScript] = []

		script_records = frappe.get_all(
			"Skill Script",
			filters={"parent": skill_name, "parenttype": "Skill Registry"},
			fields=["script_name", "description", "script_type", "python_function", "file"],
			order_by="idx asc",
		)

		for record in script_records:
			try:
				script = cls._build_script(record)
				if script:
					scripts.append(script)
			except Exception as e:
				logger.error(
					"Failed to build script '%s' for skill '%s': %s",
					record.get("script_name", "?"),
					skill_name,
					str(e),
				)

		return scripts

	@classmethod
	def _build_script(cls, record: dict[str, Any]) -> Optional[SkillScript]:
		"""
		Build a SkillScript from a child table record.

		Args:
			record: Skill Script child table record.

		Returns:
			SkillScript instance or None if build fails.
		"""
		name = record["script_name"]
		description = record.get("description")
		script_type = record.get("script_type", "In-Process Function")

		if script_type == "In-Process Function":
			python_function = record.get("python_function", "")
			if not python_function:
				logger.error("In-Process script '%s' has no python_function", name)
				return None

			try:
				func = cls._import_callable(python_function)
				return SkillScript(name=name, description=description, function=func)
			except (ImportError, AttributeError, ValueError) as e:
				logger.error(
					"Failed to import function '%s' for script '%s': %s",
					python_function,
					name,
					str(e),
				)
				return None

		elif script_type == "File Reference":
			file_name = record.get("file", "")
			if not file_name:
				logger.error("File Reference script '%s' has no file attached", name)
				return None

			# Resolve the script path. Files may be:
			# 1. Registered in Frappe's File DocType (file_url stored in "file" field)
			# 2. Plain files on disk at the specified path (e.g. /private/files/skills/...)
			file_path = None

			# Try resolving via Frappe File DocType first
			try:
				if frappe.db.exists("File", {"file_url": file_name}):
					file_doc = frappe.get_doc("File", {"file_url": file_name})
					file_path = file_doc.get_full_path()
			except Exception:
				pass

			# Fall back to plain file path resolution
			if not file_path:
				# Try as a path relative to the site directory
				site_path = Path(frappe.get_site_path())
				candidate = site_path / file_name.lstrip("/")
				if candidate.exists():
					file_path = str(candidate)
				else:
					# Try as a Frappe app file path
					candidate = Path(frappe.get_app_path("ph_agent")) / "private" / "files" / "skills" / Path(file_name).relative_to("/private/files/skills")
					if candidate.exists():
						file_path = str(candidate)

			if file_path:
				return SkillScript(name=name, description=description, path=file_path)
			else:
				logger.error(
					"Failed to resolve path for script '%s' from file '%s'",
					name,
					file_name,
				)
				return None

		return None

	@staticmethod
	def _import_callable(dotted_path: str) -> Any:
		"""
		Import a callable from a dotted Python path.

		Args:
			dotted_path: e.g. 'ph_agent.api.my_function'

		Returns:
			The imported callable.

		Raises:
			ImportError: If the module cannot be imported.
			AttributeError: If the attribute does not exist on the module.
			ValueError: If the path format is invalid.
		"""
		parts = dotted_path.rsplit(".", 1)
		if len(parts) != 2:
			raise ValueError(f"Invalid dotted path: '{dotted_path}'. Expected 'module.function' format.")

		module_path, attr_name = parts
		debug_log(
			"SkillManager: importing callable",
			f"Path: {dotted_path}, Module: {module_path}, Attr: {attr_name}",
		)
		module = importlib.import_module(module_path)
		callable_obj = getattr(module, attr_name)

		if not callable(callable_obj):
			raise TypeError(f"'{dotted_path}' is not callable")

		debug_log(
			"SkillManager: import successful",
			f"Path: {dotted_path}",
		)
		return callable_obj

	@classmethod
	def get_enabled_skill_names(cls) -> list[str]:
		"""
		Get the names of all enabled skills from the Skill Registry.

		Returns:
			List of skill names.
		"""
		return frappe.get_all(
			"Skill Registry",
			filters={"is_enabled": 1},
			pluck="skill_name",
		)


# Module-level convenience functions for hooks


def get_code_skills() -> list[Skill]:
	"""Convenience function to get all code-defined skills."""
	return SkillManager.get_code_skills()


