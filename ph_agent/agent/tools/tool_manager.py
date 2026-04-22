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
from agent_framework import tool, FunctionInvocationContext

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
        Create a wrapper function that injects context into tool calls.
        
        Args:
            original_tool: The original tool function
            session_name: Chat session name
            user: User name
            
        Returns:
            Wrapped tool function with context injection
        """
        # Get the original function from the tool
        original_func = original_tool.func if hasattr(original_tool, 'func') else original_tool
        
        @tool(
            name=original_tool.name,
            description=original_tool.description,
            approval_mode=getattr(original_tool, 'approval_mode', 'never_require')
        )
        def wrapped_tool(*args, ctx: FunctionInvocationContext = None, **kwargs):
            # Inject context if not already provided
            if ctx is None:
                # Create a mock context with our injected values
                class MockContext:
                    def __init__(self):
                        self.kwargs = {}
                        if user:
                            self.kwargs["user"] = user
                        if session_name:
                            self.kwargs["session_name"] = session_name
                        self.kwargs["frappe_session"] = frappe.session
                
                ctx = MockContext()
            
            # Add our values to existing context
            if user and "user" not in ctx.kwargs:
                ctx.kwargs["user"] = user
            if session_name and "session_name" not in ctx.kwargs:
                ctx.kwargs["session_name"] = session_name
            if "frappe_session" not in ctx.kwargs:
                ctx.kwargs["frappe_session"] = frappe.session
            
            # Call the original function
            return original_func(*args, ctx=ctx, **kwargs)
        
        return wrapped_tool
    
    @classmethod
    def _get_cached_tools(cls) -> Optional[List]:
        """Get tools from cache if available."""
        try:
            cached = frappe.cache().get_value(cls.CACHE_KEY)
            if cached:
                logger.debug("Found tools in cache")
                return cached
        except Exception as e:
            logger.warning("Failed to read from cache: %s", str(e))
        
        return None
    
    @classmethod
    def _cache_tools(cls, tools: List):
        """Cache the loaded tools."""
        try:
            frappe.cache().set_value(cls.CACHE_KEY, tools, expires_in_sec=3600)  # 1 hour
            logger.debug("Cached %d tools", len(tools))
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