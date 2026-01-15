"""OpenTelemetry span exporter for the local console."""

from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from db_meta_v2.console.collector import Span, get_collector


class ConsoleSpanExporter(SpanExporter):
    """Exports spans to the in-memory console collector."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to the collector."""
        collector = get_collector()

        for otel_span in spans:
            # Convert OTel span to our Span
            span = Span(
                trace_id=format(otel_span.context.trace_id, "032x"),
                span_id=format(otel_span.context.span_id, "016x"),
                parent_span_id=(
                    format(otel_span.parent.span_id, "016x") if otel_span.parent else None
                ),
                name=otel_span.name,
                start_time=otel_span.start_time / 1e9,  # Convert ns to seconds
                end_time=(otel_span.end_time / 1e9 if otel_span.end_time else None),
                status="error" if otel_span.status.is_ok is False else "ok",
                attributes=dict(otel_span.attributes) if otel_span.attributes else {},
                events=[
                    {
                        "name": e.name,
                        "timestamp": e.timestamp / 1e9,
                        "attributes": dict(e.attributes) if e.attributes else {},
                    }
                    for e in otel_span.events
                ],
            )
            collector.add_span(span)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any pending spans."""
        return True


def setup_console_tracing():
    """Set up OpenTelemetry to export to the console.

    Call this before starting the MCP server to enable tracing.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Create provider with our exporter
    provider = TracerProvider()
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

    # Set as global provider
    trace.set_tracer_provider(provider)

    return provider
