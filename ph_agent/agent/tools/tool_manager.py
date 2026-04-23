"""
ToolManager for PH Agent.

Manages loading, caching, and registration of tools from the Tool Registry
for use with the Microsoft Agent Framework.
"""

import importlib
import json
import logging
from typing import List, Optional, Dict, Any

import frappe
from agent_framework import FunctionInvocationContext, FunctionTool, tool

logger = logging.getLogger(__name__)


class ToolManager:
    """Manager for loading and registering tools from the Tool Registry."""
    
    # Cache key for storing loaded tools
    CACHE_KEY = "ph_agent:tools:registered"
    
    @classmethod
    def get_tools(cls, session_name: Optional[str] = None, user: Optional[str] = None) -> List:
        """
        Get all enabled tools from the Tool Registry.
        
        Args:
            session_name: Optional chat session name for context injection
            user: Optional user name for context injection
            
        Returns:
            List of tool objects ready to be passed to Agent constructor
        """
        # Try to get from cache first
        cached_tools = cls._get_cached_tools()
        if cached_tools is not None:
            logger.debug("Returning %d tools from cache", len(cached_tools))
            return cls._inject_context_into_tools(cached_tools, session_name, user)
        
        # Load from database
        tools = cls._load_tools_from_db()
        
        # Cache the tools
        cls._cache_tools(tools)
        
        # Inject context if needed
        return cls._inject_context_into_tools(tools, session_name, user)
    
    @classmethod
    def _load_tools_from_db(cls) -> List:
        """Load enabled tools from the Tool Registry database."""
        tools = []
        
        # Get all enabled tools from Tool Registry
        tool_records = frappe.get_all(
            "Tool Registry",
            filters={"is_enabled": 1},
            fields=["name", "tool_name", "description", "python_function", "parameters_json", "requires_approval"]
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
        
        Args:
            record: Tool Registry document as dictionary
            
        Returns:
            Registered tool object or None if registration fails
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

        return FunctionTool(
            name=original_tool.name,
            description=original_tool.description,
            approval_mode=getattr(original_tool, 'approval_mode', None),
            # Reuse the original tool's Pydantic input model so the LLM sees
            # the same parameter schema (properties, types, descriptions, defaults).
            input_model=original_tool.input_model,
            func=injecting_func,
        )
    
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