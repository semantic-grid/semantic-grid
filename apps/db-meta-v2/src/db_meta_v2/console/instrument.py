"""Instrumentation utilities for tracing MCP tool calls."""

import functools
import inspect
import time
from typing import Any, Callable, TypeVar

from opentelemetry import trace

F = TypeVar("F", bound=Callable[..., Any])

tracer = trace.get_tracer("dbmeta.tools")


def traced_tool(name: str | None = None) -> Callable[[F], F]:
    """Decorator to add tracing to a tool function.

    Usage:
        @traced_tool()
        async def my_tool(arg1: str) -> dict:
            ...

        @traced_tool("custom_name")
        def another_tool() -> str:
            ...
    """

    def decorator(func: F) -> F:
        tool_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                with tracer.start_as_current_span(
                    tool_name,
                    attributes={
                        "tool.name": tool_name,
                        "tool.args": _safe_repr(kwargs),
                    },
                ) as span:
                    try:
                        result = await func(*args, **kwargs)
                        span.set_attribute("tool.success", True)
                        return result
                    except Exception as e:
                        span.set_attribute("tool.success", False)
                        span.set_attribute("tool.error", str(e))
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                with tracer.start_as_current_span(
                    tool_name,
                    attributes={
                        "tool.name": tool_name,
                        "tool.args": _safe_repr(kwargs),
                    },
                ) as span:
                    try:
                        result = func(*args, **kwargs)
                        span.set_attribute("tool.success", True)
                        return result
                    except Exception as e:
                        span.set_attribute("tool.success", False)
                        span.set_attribute("tool.error", str(e))
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return sync_wrapper  # type: ignore

    return decorator


def _safe_repr(obj: Any, max_len: int = 200) -> str:
    """Safely convert object to string representation."""
    try:
        s = repr(obj)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except Exception:
        return "<unrepresentable>"


def instrument_server(server) -> None:
    """Instrument all tools on a FastMCP server with tracing.

    This wraps each registered tool's function with OTel span creation.
    Call this after all tools are registered but before starting the server.
    """
    # FastMCP stores tools in server._tool_manager._tools
    # Each tool has a 'fn' attribute with the actual function
    try:
        tool_manager = getattr(server, "_tool_manager", None)
        if tool_manager is None:
            return

        tools = getattr(tool_manager, "_tools", {})
        for tool_name, tool in tools.items():
            original_fn = tool.fn
            if original_fn is None:
                continue

            # Wrap the function with tracing
            wrapped = traced_tool(tool_name)(original_fn)
            tool.fn = wrapped

    except Exception as e:
        # Don't fail if instrumentation doesn't work
        import logging

        logging.getLogger(__name__).warning(f"Failed to instrument server: {e}")
