"""
ToolManager for PH Agent.

Manages loading, caching, and registration of tools from the Tool Registry
for use with the Microsoft Agent Framework.
"""

import importlib
import json
import logging
from typing import List, Optional, Dict, Any, get_type_hints

import frappe
from agent_framework import FunctionInvocationContext, FunctionTool, tool
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)


# Safe namespace for executing custom scripts.
# Provides controlled access to common modules without dangerous builtins.
SAFE_NAMESPACE = {
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
    "FunctionInvocationContext": FunctionInvocationContext,
}


class ToolManager:
    """Manager for loading and registering tools from the Tool Registry."""
    
    # Cache key for storing loaded tools
    CACHE_KEY = "ph_agent:tools:registered"
    
    @classmethod
    def get_tools(cls, session_name: Optional[str] = None, user: Optional[str] = None, persona: Optional[str] = None) -> List:
        """
        Get all enabled tools from the Tool Registry.
        
        Args:
            session_name: Optional chat session name for context injection
            user: Optional user name for context injection
            persona: Optional persona name; if the persona has tool_groups configured,
                     only tools matching those groups are returned.
            
        Returns:
            List of tool objects ready to be passed to Agent constructor
        """
        # Try to get from cache first
        cached_tools = cls._get_cached_tools()
        if cached_tools is not None:
            logger.debug("Returning %d tools from cache", len(cached_tools))
            tools = cached_tools
        else:
            # Load from database
            tools = cls._load_tools_from_db()
            # Cache the tools
            cls._cache_tools(tools)

        # Filter by persona tool groups if configured
        tools = cls._filter_by_persona(tools, persona)

        # Inject context if needed
        return cls._inject_context_into_tools(tools, session_name, user)
    
    @classmethod
    def _filter_by_persona(cls, tools: List, persona: Optional[str]) -> List:
        """Filter tools by the persona's configured tool groups.

        If the persona has ``disable_tools = 1``, returns an empty list.
        If the persona has no tool_groups rows (or persona is None), all tools
        are returned (backward-compatible default).
        """
        if not persona:
            return tools

        try:
            persona_doc = frappe.get_doc("Persona", persona)
        except Exception as e:
            logger.warning("Failed to load persona '%s': %s", persona, str(e))
            return tools

        # Hard override: no tools at all
        if persona_doc.get("disable_tools"):
            logger.debug("[tool_filter] Persona '%s' has disable_tools=1, returning []", persona)
            return []

        persona_groups = [row.tool_group for row in (persona_doc.get("tool_groups") or [])]

        if not persona_groups:
            # Persona exists but has no groups configured → return all tools
            return tools

        filtered = [t for t in tools if getattr(t, "tool_group", "General") in persona_groups]
        logger.debug(
            "Persona '%s' groups %s: filtered %d → %d tools",
            persona, persona_groups, len(tools), len(filtered)
        )
        return filtered

    @classmethod
    def _load_tools_from_db(cls) -> List:
        """Load enabled tools from the Tool Registry database."""
        tools = []
        
        # Get all enabled tools from Tool Registry
        tool_records = frappe.get_all(
            "Tool Registry",
            filters={"is_enabled": 1},
            fields=[
                "name", "tool_name", "description", "script_type",
                "tool_group", "python_function", "custom_script",
                "parameters_json", "requires_approval"
            ]
        )
        
        logger.info("Loading %d enabled tools from Tool Registry", len(tool_records))
        
        for record in tool_records:
            try:
                tool_obj = cls._register_tool(record)
                if tool_obj:
                    tools.append(tool_obj)
                    logger.debug("Successfully registered tool: %s", record["tool_name"])
            except Exception as e:
                logger.error("Failed to register tool %s: %s", record["tool_name"], str(e))
                # Continue with other tools even if one fails
        
        logger.info("Successfully loaded %d/%d tools", len(tools), len(tool_records))
        return tools
    
    @classmethod
    def _register_tool(cls, record: Dict[str, Any]):
        """
        Register a single tool from Tool Registry record.
        
        Dispatches to the appropriate registration method based on script_type.
        
        Args:
            record: Tool Registry document as dictionary
            
        Returns:
            Registered tool object or None if registration fails
        """
        script_type = record.get("script_type", "Existing Function")
        
        if script_type == "Custom Script":
            tool_obj = cls._register_custom_script_tool(record)
        else:
            tool_obj = cls._register_existing_function_tool(record)

        # Attach tool_group so _filter_by_persona can use it without a DB round-trip
        if tool_obj is not None:
            setattr(tool_obj, "tool_group", record.get("tool_group") or "General")

        return tool_obj
    
    @classmethod
    def _get_safe_namespace(cls) -> Dict[str, Any]:
        """Return a copy of the safe namespace dict."""
        return dict(SAFE_NAMESPACE)
    
    @classmethod
    def _build_input_model_from_schema(cls, parameters_json: Optional[str]) -> Optional[type[BaseModel]]:
        """
        Build a Pydantic input model from a JSON Schema string.
        
        Args:
            parameters_json: JSON Schema string describing tool parameters
            
        Returns:
            A Pydantic BaseModel subclass, or None if no schema provided
        """
        if not parameters_json:
            return None
        
        schema = json.loads(parameters_json)
        properties = schema.get("properties", {})
        required_fields = set(schema.get("required", []))
        
        fields = {}
        for field_name, field_schema in properties.items():
            field_type = cls._json_schema_type_to_python(field_schema)
            field_description = field_schema.get("description", "")
            
            if field_name in required_fields:
                # Required — use Field with no default
                fields[field_name] = (
                    field_type,
                    Field(..., description=field_description),
                )
            else:
                # Optional — wrap in Optional and set default None
                default_value = field_schema.get("default", None)
                fields[field_name] = (
                    Optional[field_type],
                    Field(default=default_value, description=field_description),
                )
        
        if not fields:
            return None
        
        # Add additionalProperties: false to the schema to help DeepSeek
        # correctly populate required parameters instead of sending empty {}
        schema["additionalProperties"] = False
        
        return create_model("ToolInputModel", **fields)
    
    @classmethod
    def _json_schema_type_to_python(cls, field_schema: Dict[str, Any]) -> type:
        """Map JSON Schema types to Python types."""
        json_type = field_schema.get("type", "string")
        
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        return type_map.get(json_type, str)
    
    @classmethod
    def _register_existing_function_tool(cls, record: Dict[str, Any]):
        """
        Register a tool backed by an existing Python function.
        
        This is the original behaviour: import a dotted function path and
        wrap it with @tool.
        """
        try:
            # Import the function
            module_path, func_name = record["python_function"].rsplit('.', 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            
            # Check if function is already decorated with @tool
            if hasattr(func, 'name') and hasattr(func, 'description'):
                # Function is already a tool, use it as-is
                # But apply requires_approval from Tool Registry if set
                if record.get("requires_approval"):
                    func.approval_mode = "always_require"
                    logger.debug("Tool %s: set approval_mode=always_require from registry", record["tool_name"])
                logger.debug("Tool %s is already decorated with @tool", record["tool_name"])
                return func
            
            # Apply @tool decorator dynamically
            tool_kwargs = {
                "name": record["tool_name"],
                "description": record["description"] or "No description provided"
            }
            
            # Add approval mode if required
            if record.get("requires_approval"):
                tool_kwargs["approval_mode"] = "always_require"
            
            # Create decorated tool
            decorated_tool = tool(**tool_kwargs)(func)
            
            logger.debug("Dynamically decorated tool %s", record["tool_name"])
            return decorated_tool
            
        except (ImportError, AttributeError, ValueError) as e:
            logger.error("Failed to import tool function %s: %s", record["python_function"], str(e))
            raise
        except Exception as e:
            logger.error("Unexpected error registering tool %s: %s", record["tool_name"], str(e))
            raise
    
    @classmethod
    def _register_custom_script_tool(cls, record: Dict[str, Any]):
        """
        Register a tool backed by a Custom Script stored in the Tool Registry.
        
        The script must define a top-level ``run_tool`` function.
        The ``parameters_json`` field provides the JSON Schema for LLM arguments.
        """
        script_code = record.get("custom_script", "")
        if not script_code:
            raise ValueError(f"Tool '{record['tool_name']}' has no custom script content.")
        
        # Compile and exec in safe namespace
        namespace = cls._get_safe_namespace()
        try:
            exec(script_code, namespace)
        except Exception as e:
            raise ValueError(f"Failed to execute custom script for tool '{record['tool_name']}': {e}") from e
        
        run_tool_func = namespace.get("run_tool")
        if not callable(run_tool_func):
            raise ValueError(
                f"Custom script for tool '{record['tool_name']}' must define a callable 'run_tool' function."
            )
        
        # Build input model from parameters_json
        parameters_json = record.get("parameters_json")
        input_model = cls._build_input_model_from_schema(parameters_json)
        
        # Create approval kwargs
        tool_kwargs = {
            "name": record["tool_name"],
            "description": record["description"] or "No description provided",
        }
        if record.get("requires_approval"):
            tool_kwargs["approval_mode"] = "always_require"
        
        # If we have an input model (schema defined), use FunctionTool directly
        # with the model so the LLM sees proper typed parameters.
        if input_model is not None:
            return FunctionTool(
                **tool_kwargs,
                input_model=input_model,
                func=run_tool_func,
            )
        
        # Otherwise use the @tool decorator which infers from type hints
        return tool(**tool_kwargs)(run_tool_func)
    
    @classmethod
    def _inject_context_into_tools(cls, tools: List, session_name: Optional[str] = None, user: Optional[str] = None) -> List:
        """
        Create tool wrappers that inject context into tool calls.
        
        Args:
            tools: List of tool objects
            session_name: Chat session name to inject
            user: User name to inject
            
        Returns:
            List of tools with context injection
        """
        if not session_name and not user:
            # No context to inject, return tools as-is
            return tools
        
        context_tools = []
        for tool_obj in tools:
            # Create a wrapper that injects context
            context_tool = cls._create_context_wrapper(tool_obj, session_name, user)
            context_tools.append(context_tool)
        
        return context_tools
    
    @classmethod
    def _create_context_wrapper(cls, original_tool, session_name: Optional[str] = None, user: Optional[str] = None):
        """
        Create a FunctionTool that injects session/user context into tool calls while
        preserving the original tool's parameter schema.

        The previous implementation wrapped with ``@tool(*args, **kwargs)`` which lost
        all type annotations, causing the LLM to see an empty ``properties: {}`` schema.
        We now build a ``FunctionTool`` directly, passing the original ``input_model``
        so the schema is identical to the source tool.
        """
        original_func = original_tool.func if hasattr(original_tool, 'func') else original_tool

        # Close over session_name and user so the injecting function is self-contained.
        _session_name = session_name
        _user = user

        def injecting_func(ctx: FunctionInvocationContext = None, **kwargs):
            """Thin wrapper: injects user/session into ctx.kwargs, then delegates."""
            if ctx is not None:
                if _user and "user" not in ctx.kwargs:
                    ctx.kwargs["user"] = _user
                if _session_name and "session_name" not in ctx.kwargs:
                    ctx.kwargs["session_name"] = _session_name
                if "frappe_session" not in ctx.kwargs:
                    ctx.kwargs["frappe_session"] = frappe.session
            return original_func(ctx=ctx, **kwargs)

        wrapped = FunctionTool(
            name=original_tool.name,
            description=original_tool.description,
            approval_mode=getattr(original_tool, 'approval_mode', None),
            # Reuse the original tool's Pydantic input model so the LLM sees
            # the same parameter schema (properties, types, descriptions, defaults).
            input_model=original_tool.input_model,
            func=injecting_func,
        )
        # Preserve tool_group so persona filtering survives context injection
        setattr(wrapped, "tool_group", getattr(original_tool, "tool_group", "General"))
        return wrapped
    
    @classmethod
    def _get_cached_tools(cls) -> Optional[List]:
        """Get tools from cache if available.
        
        Note: Only metadata is cached; actual FunctionTool objects can't be pickled.
        Returns None to force fresh load from DB each time.
        """
        return None
    
    @classmethod
    def _cache_tools(cls, tools: List):
        """Cache the loaded tools (metadata only, not callable objects)."""
        try:
            # Store only serializable metadata — FunctionTool objects can't be pickled
            tool_meta = []
            for t in tools:
                tool_meta.append({
                    "name": t.name,
                    "description": t.description,
                    "approval_mode": getattr(t, "approval_mode", "never_require"),
                })
            frappe.cache().set_value(cls.CACHE_KEY, tool_meta, expires_in_sec=3600)  # 1 hour
            logger.debug("Cached metadata for %d tools", len(tools))
        except Exception as e:
            logger.warning("Failed to cache tools: %s", str(e))
    
    @classmethod
    def invalidate_cache(cls):
        """Invalidate the tool cache."""
        try:
            frappe.cache().delete_value(cls.CACHE_KEY)
            logger.info("Invalidated tool cache")
        except Exception as e:
            logger.warning("Failed to invalidate cache: %s", str(e))
    
    @classmethod
    def tool_requires_approval(cls, tool_name: str) -> bool:
        """
        Check if a tool requires human approval before execution.
        
        Args:
            tool_name: Name of the tool to check
            
        Returns:
            True if the tool requires approval, False otherwise
        """
        tools = cls.get_tools()
        for tool_obj in tools:
            if tool_obj.name == tool_name:
                return getattr(tool_obj, 'approval_mode', 'never_require') == 'always_require'
        return False
    
    @classmethod
    def get_tool_by_name(cls, tool_name: str) -> Optional[Any]:
        """
        Get a specific tool by name.
        
        Args:
            tool_name: Name of the tool to retrieve
            
        Returns:
            Tool object or None if not found
        """
        tools = cls.get_tools()
        for tool_obj in tools:
            if tool_obj.name == tool_name:
                return tool_obj
        return None
    
    @classmethod
    def reload_tools(cls):
        """Force reload tools from database and update cache."""
        cls.invalidate_cache()
        return cls.get_tools()


def invalidate_tool_cache(doc, method):
    """
    Function to invalidate tool cache.
    This is used by Frappe's doc_events hook system.
    
    Args:
        doc: The document instance
        method: The method being called (e.g., 'on_update', 'after_insert', 'on_trash')
    """
    ToolManager.invalidate_cache()


# Singleton instance for convenience
tool_manager = ToolManager()