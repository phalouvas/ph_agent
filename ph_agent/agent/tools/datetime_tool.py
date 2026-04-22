"""
Date/Time tool for testing the tool registration system.

This tool shows the current date and time, useful for testing
the Tool Registry and ToolManager implementation.
"""

from datetime import datetime
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="show_datetime",
    description="Shows the current date and time. Useful for testing tool registration and verifying the system is working."
)
def show_datetime_tool(
    format: Annotated[
        Optional[str], 
        Field(description="Date/time format (e.g., 'iso', 'full', 'short', or custom strftime format)")
    ] = "iso",
    timezone: Annotated[
        Optional[str],
        Field(description="Timezone name (e.g., 'UTC', 'US/Eastern', 'Europe/London')")
    ] = None,
    ctx: FunctionInvocationContext = None
) -> str:
    """
    Show the current date and time.
    
    Args:
        format: Date/time format:
            - 'iso': ISO 8601 format (default)
            - 'full': Full readable format
            - 'short': Short date/time format
            - Custom strftime format string
        timezone: Optional timezone name
        ctx: Function invocation context (injected by framework)
        
    Returns:
        Current date and time in specified format
    """
    # Get current time
    now = datetime.now()
    
    # Apply format
    if format == "iso":
        formatted = now.isoformat()
    elif format == "full":
        formatted = now.strftime("%A, %B %d, %Y at %I:%M:%S %p")
    elif format == "short":
        formatted = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # Try custom strftime format
        try:
            formatted = now.strftime(format)
        except Exception:
            formatted = now.isoformat()  # Fallback to ISO
    
    # Add context information if available
    context_info = ""
    if ctx and ctx.kwargs:
        user = ctx.kwargs.get("user", "unknown")
        session = ctx.kwargs.get("session_name", "unknown")
        context_info = f" [User: {user}, Session: {session}]"
    
    # Add timezone info if specified
    timezone_info = ""
    if timezone:
        timezone_info = f" (Timezone: {timezone})"
    
    return f"Current date/time{context_info}{timezone_info}: {formatted}"