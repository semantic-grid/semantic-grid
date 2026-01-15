"""Instrumentation utilities for tracing MCP requests via middleware.

This provides Logfire-like tracing for the local dbmeta console by using
FastMCP's middleware system to intercept all MCP protocol messages.
"""

import json
import logging
from typing import Any

from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("dbmeta.mcp")


def _safe_str(obj: Any, max_len: int = 2000) -> str:
    """Safely convert object to string representation."""
    try:
        if obj is None:
            return ""
        if isinstance(obj, str):
            s = obj
        elif isinstance(obj, dict):
            s = json.dumps(obj, default=str, indent=2)
        elif hasattr(obj, "model_dump"):
            s = json.dumps(obj.model_dump(), default=str, indent=2)
        else:
            s = str(obj)
    except (TypeError, ValueError):
        s = repr(obj)

    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _extract_key_args(tool_name: str, args: dict | None) -> dict[str, str]:
    """Extract key arguments worth displaying based on tool name."""
    if not args:
        return {}

    attrs = {}

    # SQL-related tools
    if tool_name in ("validate_sql", "run_sql", "export_results"):
        if "sql" in args:
            attrs["sql"] = _safe_str(args["sql"], 1000)
        if "query_id" in args:
            attrs["query_id"] = str(args["query_id"])
        if "confirmed" in args:
            attrs["confirmed"] = str(args["confirmed"])

    # Shell command
    elif tool_name == "shell":
        if "command" in args:
            attrs["command"] = _safe_str(args["command"], 500)

    # Database introspection
    elif tool_name in ("list_tables", "describe_table", "sample_table", "list_schemas"):
        for key in ("table_name", "schema", "catalog", "limit"):
            if key in args and args[key]:
                attrs[key] = str(args[key])

    # Natural language query
    elif tool_name == "get_data":
        if "intent" in args:
            attrs["intent"] = _safe_str(args["intent"], 500)
        if "tables_hint" in args:
            attrs["tables_hint"] = str(args["tables_hint"])

    # Query training
    elif tool_name in ("query_generate", "query_feedback"):
        if "question" in args:
            attrs["question"] = _safe_str(args["question"], 500)
        if "feedback" in args:
            attrs["feedback"] = _safe_str(args["feedback"], 500)

    # Import tools
    elif tool_name in ("import_examples", "import_instructions"):
        if "path" in args:
            attrs["path"] = str(args["path"])

    # Always include all args as fallback (truncated)
    if not attrs and args:
        attrs["args"] = _safe_str(args, 500)

    return attrs


def _extract_tool_info(context) -> tuple[str | None, dict | None]:
    """Extract tool name and arguments from a tools/call context.

    For on_call_tool, context.message is CallToolRequestParams which has:
    - name: str (tool name)
    - arguments: dict | None (tool arguments)
    """
    tool_name = None
    tool_args = None

    try:
        msg = getattr(context, "message", None)
        if msg is None:
            return None, None

        # For on_call_tool, message IS the params (CallToolRequestParams)
        # It has 'name' and 'arguments' directly
        if hasattr(msg, "name"):
            tool_name = msg.name
        if hasattr(msg, "arguments"):
            tool_args = msg.arguments

    except Exception as e:
        logger.debug(f"Failed to extract tool info: {e}")

    return tool_name, tool_args


def create_tracing_middleware():
    """Create a FastMCP middleware that traces all MCP requests.

    Returns a middleware class that can be added to a FastMCP server
    to trace all MCP protocol messages with OpenTelemetry spans.
    """
    from fastmcp.server.middleware import Middleware

    class TracingMiddleware(Middleware):
        """Middleware that creates OTel spans for all MCP requests."""

        async def on_call_tool(self, context, call_next):
            """Trace tool calls with detailed info."""
            tool_name, tool_args = _extract_tool_info(context)
            span_name = tool_name or "unknown_tool"

            # Extract key arguments for this tool type
            key_attrs = _extract_key_args(tool_name or "", tool_args)

            # Build span attributes
            span_attrs = {"tool.name": tool_name or "unknown"}
            span_attrs.update(key_attrs)

            # Create the MCP request span
            with tracer.start_as_current_span(
                f"tools/call: {span_name}",
                attributes={
                    "mcp.method": "tools/call",
                    "mcp.type": "request",
                    "tool.name": tool_name or "unknown",
                },
            ) as mcp_span:
                # Create nested span for the actual tool with detailed args
                with tracer.start_as_current_span(
                    span_name,
                    attributes=span_attrs,
                ) as tool_span:
                    try:
                        result = await call_next(context)

                        tool_span.set_attribute("tool.success", True)

                        # Extract result preview
                        if result is not None and hasattr(result, "content"):
                            content = result.content
                            if isinstance(content, list) and content:
                                first = content[0]
                                if hasattr(first, "text"):
                                    text = first.text
                                    # Try to extract key info from result
                                    preview = _safe_str(text, 500)
                                    tool_span.set_attribute("result.preview", preview)

                                    # For SQL tools, try to extract row count
                                    if "rows_returned" in text:
                                        tool_span.set_attribute(
                                            "result.info", "see result.preview"
                                        )

                        return result

                    except Exception as e:
                        tool_span.set_status(
                            trace.Status(trace.StatusCode.ERROR, str(e))
                        )
                        tool_span.set_attribute("tool.success", False)
                        tool_span.set_attribute("tool.error", str(e))
                        mcp_span.set_status(
                            trace.Status(trace.StatusCode.ERROR, str(e))
                        )
                        raise

        async def on_list_tools(self, context, call_next):
            """Trace tools/list requests."""
            with tracer.start_as_current_span(
                "MCP server handle request: tools/list",
                attributes={
                    "mcp.method": "tools/list",
                    "mcp.type": "request",
                },
            ) as span:
                result = await call_next(context)
                if result and hasattr(result, "tools"):
                    span.set_attribute("tools.count", len(result.tools))
                return result

        async def on_list_resources(self, context, call_next):
            """Trace resources/list requests."""
            with tracer.start_as_current_span(
                "MCP server handle request: resources/list",
                attributes={
                    "mcp.method": "resources/list",
                    "mcp.type": "request",
                },
            ):
                return await call_next(context)

        async def on_list_prompts(self, context, call_next):
            """Trace prompts/list requests."""
            with tracer.start_as_current_span(
                "MCP server handle request: prompts/list",
                attributes={
                    "mcp.method": "prompts/list",
                    "mcp.type": "request",
                },
            ):
                return await call_next(context)

        async def on_read_resource(self, context, call_next):
            """Trace resource reads."""
            uri = None
            try:
                msg = getattr(context, "message", None)
                if msg:
                    params = getattr(msg, "params", None)
                    if params:
                        uri = str(getattr(params, "uri", None) or "")
            except Exception:
                pass

            with tracer.start_as_current_span(
                "MCP server handle request: resources/read",
                attributes={
                    "mcp.method": "resources/read",
                    "mcp.type": "request",
                    "resource.uri": uri or "unknown",
                },
            ):
                return await call_next(context)

        async def on_initialize(self, context, call_next):
            """Trace initialize requests."""
            with tracer.start_as_current_span(
                "MCP server handle request: initialize",
                attributes={
                    "mcp.method": "initialize",
                    "mcp.type": "request",
                },
            ):
                return await call_next(context)

    return TracingMiddleware()


def instrument_server(server) -> None:
    """Instrument a FastMCP server with OTel tracing middleware.

    This adds middleware that traces all MCP protocol messages,
    providing Logfire-like visibility in the local dbmeta console.

    Args:
        server: FastMCP server instance
    """
    try:
        middleware = create_tracing_middleware()
        server.add_middleware(middleware)
        logger.info("MCP tracing middleware installed")
    except Exception as e:
        logger.warning(f"Failed to install tracing middleware: {e}")
