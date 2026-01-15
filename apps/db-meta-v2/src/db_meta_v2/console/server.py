"""Simple HTTP server for OTel console UI."""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from db_meta_v2.console.collector import get_collector
from db_meta_v2.console.ui import get_html


class ConsoleHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the console."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/traces":
            self._serve_traces()
        elif self.path == "/api/spans":
            self._serve_spans()
        elif self.path == "/api/health":
            self._serve_json({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/api/clear":
            get_collector().clear()
            self._serve_json({"status": "cleared"})
        elif self.path == "/api/spans":
            self._receive_spans()
        else:
            self.send_error(404)

    def _receive_spans(self):
        """Receive spans from the MCP server."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            collector = get_collector()
            for span_data in data.get("spans", []):
                from db_meta_v2.console.collector import Span

                span = Span(
                    trace_id=span_data["trace_id"],
                    span_id=span_data["span_id"],
                    parent_span_id=span_data.get("parent_span_id"),
                    name=span_data["name"],
                    start_time=span_data["start_time"],
                    end_time=span_data.get("end_time"),
                    status=span_data.get("status", "ok"),
                    attributes=span_data.get("attributes", {}),
                )
                collector.add_span(span)

            self._serve_json({"status": "ok", "count": len(data.get("spans", []))})
        except Exception as e:
            self.send_error(400, str(e))

    def _serve_html(self):
        """Serve the main HTML page."""
        html = get_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_traces(self):
        """Serve traces as JSON."""
        traces = get_collector().get_traces()
        self._serve_json({"traces": traces})

    def _serve_spans(self):
        """Serve spans as JSON."""
        spans = get_collector().get_spans()
        self._serve_json({"spans": spans})

    def _serve_json(self, data: dict):
        """Serve JSON response."""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def start_console(
    port: int = 8384,
    open_browser: bool = True,
    blocking: bool = True,
) -> HTTPServer | None:
    """Start the console HTTP server.

    Args:
        port: Port to listen on
        open_browser: Whether to open browser automatically
        blocking: Whether to block (True) or run in background thread (False)

    Returns:
        HTTPServer instance if non-blocking, None if blocking
    """
    server = HTTPServer(("127.0.0.1", port), ConsoleHandler)
    url = f"http://localhost:{port}"

    print(f"dbmeta console running at {url}")
    print("Press Ctrl+C to stop\n")

    if open_browser:
        webbrowser.open(url)

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down console...")
            server.shutdown()
        return None
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
