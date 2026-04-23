"""
Secure script runner for file-based skill scripts.

Implements the SkillScriptRunner protocol from agent_framework, executing
file-based scripts via subprocess with sandboxing guards.
"""

import logging
import subprocess
import sys
from typing import Any, Optional

import frappe
from agent_framework import Skill, SkillScript

logger = logging.getLogger(__name__)


def run_file_script(
	skill: Skill,
	script: SkillScript,
	args: Optional[dict[str, Any]] = None,
) -> Any:
	"""
	Execute a file-based skill script via subprocess with sandboxing.

	Implements the ``SkillScriptRunner`` protocol.  Only handles scripts
	with a ``path`` (file-based).  Code-defined scripts (with a ``function``)
	are handled directly by the framework and should not reach this runner.

	Args:
		skill: The skill that owns the script.
		script: The script to run (must have a ``path`` set).
		args: Optional keyword arguments for the script.

	Returns:
		The stdout of the script, or an error message on failure.

	Raises:
		ValueError: If the script is code-defined (no path).
	"""
	if script.function is not None:
		# Code-defined scripts are handled in-process by the framework.
		# This runner should not be called for them.
		raise ValueError(
			f"run_file_script called for code-defined script '{script.name}' "
			"in skill '{skill.name}'. Use the framework's in-process runner instead."
		)

	if not script.path:
		return f"Error: Script '{script.name}' in skill '{skill.name}' has no path."

	# Build command arguments
	script_args = _build_script_args(args)

	# Sandboxing: timeout, cwd isolation
	timeout_seconds = 30

	try:
		logger.info(
			"Running file script '%s' from skill '%s' (path=%s)",
			script.name,
			skill.name,
			script.path,
		)

		result = subprocess.run(
			[sys.executable, script.path, *script_args],
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			cwd=skill.path if skill.path else None,
			env={
				"PYTHONIOENCODING": "utf-8",
				"PATH": "/usr/local/bin:/usr/bin:/bin",
			},
		)

		if result.returncode != 0:
			logger.warning(
				"Script '%s' from skill '%s' exited with code %d: %s",
				script.name,
				skill.name,
				result.returncode,
				result.stderr[:500],
			)
			return (
				f"Script '{script.name}' exited with code {result.returncode}.\n"
				f"stdout: {result.stdout}\n"
				f"stderr: {result.stderr}"
			)

		logger.info(
			"Script '%s' from skill '%s' completed successfully (%d chars)",
			script.name,
			skill.name,
			len(result.stdout),
		)

		return result.stdout

	except subprocess.TimeoutExpired:
		logger.warning(
			"Script '%s' from skill '%s' timed out after %ds",
			script.name,
			skill.name,
			timeout_seconds,
		)
		return (
			f"Error: Script '{script.name}' in skill '{skill.name}' "
			f"timed out after {timeout_seconds} seconds."
		)
	except FileNotFoundError:
		logger.error(
			"Script file not found: '%s' for skill '%s'",
			script.path,
			skill.name,
		)
		return f"Error: Script file not found at '{script.path}'."
	except Exception as e:
		logger.exception(
			"Unexpected error running script '%s' from skill '%s': %s",
			script.name,
			skill.name,
			str(e),
		)
		return f"Error: Failed to run script '{script.name}': {str(e)}."


def _build_script_args(args: Optional[dict[str, Any]] = None) -> list[str]:
	"""Build command-line arguments from a dict of keyword args.

	Converts ``{"length": 24, "uppercase": True}`` to
	``["--length", "24", "--uppercase", "True"]``.

	Args:
		args: Optional keyword arguments dict.

	Returns:
		List of CLI argument strings.
	"""
	if not args:
		return []

	cli_args = []
	for key, value in args.items():
		cli_args.append(f"--{key}")
		cli_args.append(str(value))

	return cli_args
