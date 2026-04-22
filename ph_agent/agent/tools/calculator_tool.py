"""
Math Calculator tool for performing basic mathematical operations.

This tool provides a simple calculator for testing the tool registration system
with multiple available tools.
"""

from typing import Annotated, Optional, Union
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext
import math


@tool(
    name="calculate",
    description="Performs mathematical calculations. Supports basic arithmetic, percentages, and common math functions."
)
def calculate_tool(
    expression: Annotated[
        Optional[str],
        Field(description="Mathematical expression to evaluate (e.g., '2 + 2', '10 * 5')")
    ] = None,
    operation: Annotated[
        Optional[str],
        Field(description="Operation to perform: 'add', 'subtract', 'multiply', 'divide', 'percentage', 'power', 'sqrt', 'log'")
    ] = None,
    a: Annotated[
        Optional[Union[int, float]],
        Field(description="First number for binary operations")
    ] = None,
    b: Annotated[
        Optional[Union[int, float]],
        Field(description="Second number for binary operations")
    ] = None,
    percentage: Annotated[
        Optional[Union[int, float]],
        Field(description="Percentage value (e.g., 20 for 20%)")
    ] = None,
    of_value: Annotated[
        Optional[Union[int, float]],
        Field(description="Value to calculate percentage of")
    ] = None,
    ctx: FunctionInvocationContext = None
) -> str:
    """
    Perform mathematical calculations.
    
    Args:
        expression: Direct mathematical expression to evaluate
        operation: Specific operation to perform
        a: First number for binary operations
        b: Second number for binary operations
        percentage: Percentage value
        of_value: Value to calculate percentage of
        ctx: Function invocation context (injected by framework)
        
    Returns:
        Calculation result as string with explanation
    """
    # Get context information if available
    user_info = ""
    session_info = ""
    if ctx and hasattr(ctx, 'kwargs'):
        if 'user' in ctx.kwargs:
            user_info = f" [User: {ctx.kwargs['user']}]"
        if 'session_name' in ctx.kwargs:
            session_info = f" [Session: {ctx.kwargs['session_name']}]"
    
    context_str = f"{user_info}{session_info}" if user_info or session_info else ""
    
    try:
        # Method 1: Direct expression evaluation
        if expression:
            # Basic safety check - only allow safe characters
            safe_chars = set("0123456789+-*/.()%^ ")
            if not all(c in safe_chars for c in expression):
                return f"Error: Expression contains unsafe characters{context_str}"
            
            # Replace ^ with ** for power operation
            expr = expression.replace('^', '**')
            
            # Evaluate the expression
            result = eval(expr, {"__builtins__": {}}, {"math": math})
            return f"Result of '{expression}': {result}{context_str}"
        
        # Method 2: Specific operation with parameters
        if operation:
            if operation == "add":
                if a is None or b is None:
                    return f"Error: Both 'a' and 'b' are required for addition{context_str}"
                result = a + b
                return f"{a} + {b} = {result}{context_str}"
            
            elif operation == "subtract":
                if a is None or b is None:
                    return f"Error: Both 'a' and 'b' are required for subtraction{context_str}"
                result = a - b
                return f"{a} - {b} = {result}{context_str}"
            
            elif operation == "multiply":
                if a is None or b is None:
                    return f"Error: Both 'a' and 'b' are required for multiplication{context_str}"
                result = a * b
                return f"{a} × {b} = {result}{context_str}"
            
            elif operation == "divide":
                if a is None or b is None:
                    return f"Error: Both 'a' and 'b' are required for division{context_str}"
                if b == 0:
                    return f"Error: Division by zero is not allowed{context_str}"
                result = a / b
                return f"{a} ÷ {b} = {result}{context_str}"
            
            elif operation == "percentage":
                if percentage is None or of_value is None:
                    return f"Error: Both 'percentage' and 'of_value' are required for percentage calculation{context_str}"
                result = (percentage / 100) * of_value
                return f"{percentage}% of {of_value} = {result}{context_str}"
            
            elif operation == "power":
                if a is None or b is None:
                    return f"Error: Both 'a' and 'b' are required for power calculation{context_str}"
                result = a ** b
                return f"{a}^{b} = {result}{context_str}"
            
            elif operation == "sqrt":
                if a is None:
                    return f"Error: 'a' is required for square root calculation{context_str}"
                if a < 0:
                    return f"Error: Cannot calculate square root of negative number{context_str}"
                result = math.sqrt(a)
                return f"√{a} = {result}{context_str}"
            
            elif operation == "log":
                if a is None:
                    return f"Error: 'a' is required for logarithm calculation{context_str}"
                if a <= 0:
                    return f"Error: Cannot calculate logarithm of non-positive number{context_str}"
                result = math.log(a)
                return f"log({a}) = {result}{context_str}"
            
            else:
                return f"Error: Unknown operation '{operation}'. Supported operations: add, subtract, multiply, divide, percentage, power, sqrt, log{context_str}"
        
        # If no valid input provided
        return f"Error: Please provide either an 'expression' or an 'operation' with required parameters{context_str}"
        
    except ZeroDivisionError:
        return f"Error: Division by zero is not allowed{context_str}"
    except ValueError as e:
        return f"Error: Invalid value - {str(e)}{context_str}"
    except Exception as e:
        return f"Error: Calculation failed - {str(e)}{context_str}"