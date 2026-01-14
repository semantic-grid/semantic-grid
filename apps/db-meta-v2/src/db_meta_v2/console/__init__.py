"""Local OTel console for dbmeta.

Provides a simple web UI to view traces from the MCP server.
"""

from db_meta_v2.console.collector import SpanCollector
from db_meta_v2.console.server import start_console

__all__ = ["start_console", "SpanCollector"]
