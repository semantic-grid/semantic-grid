"""HTTP span exporter - sends spans to the console server."""

import json
import logging
import urllib.error
import urllib.request
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


class HttpSpanExporter(SpanExporter):
    """Exports spans to the console server via HTTP."""

    def __init__(self, endpoint: str = "http://localhost:8384/api/spans"):
        self.endpoint = endpoint
        self._connected = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to the console server."""
        if not spans:
            return SpanExportResult.SUCCESS

        # Convert spans to JSON
        span_data = []
        for otel_span in spans:
            span_data.append(
                {
                    "trace_id": format(otel_span.context.trace_id, "032x"),
                    "span_id": format(otel_span.context.span_id, "016x"),
                    "parent_span_id": (
                        format(otel_span.parent.span_id, "016x") if otel_span.parent else None
                    ),
                    "name": otel_span.name,
                    "start_time": otel_span.start_time / 1e9,
                    "end_time": otel_span.end_time / 1e9 if otel_span.end_time else None,
                    "status": "error" if otel_span.status.is_ok is False else "ok",
                    "attributes": dict(otel_span.attributes) if otel_span.attributes else {},
                }
            )

        # Send to console server
        try:
            data = json.dumps({"spans": span_data}).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    if not self._connected:
                        logger.info("Connected to dbmeta console")
                        self._connected = True
                    return SpanExportResult.SUCCESS
        except urllib.error.URLError:
            # Console not running - silently ignore
            self._connected = False
        except Exception as e:
            logger.debug(f"Failed to export spans: {e}")
            self._connected = False

        return SpanExportResult.SUCCESS  # Don't fail the app if console is down

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any pending spans."""
        return True


def setup_http_tracing(console_port: int = 8384):
    """Set up OpenTelemetry to export spans via HTTP to console.

    Call this in the MCP server to enable tracing to the console.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = f"http://localhost:{console_port}/api/spans"

    provider = TracerProvider()
    processor = BatchSpanProcessor(
        HttpSpanExporter(endpoint=endpoint),
        max_export_batch_size=32,
        schedule_delay_millis=500,  # Export every 500ms
    )
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    return provider
