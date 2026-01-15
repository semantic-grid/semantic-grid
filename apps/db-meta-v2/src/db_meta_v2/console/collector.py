"""In-memory span collector for local OTel console."""

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    """A single trace span."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_time: float  # Unix timestamp in seconds
    end_time: float | None = None
    status: str = "ok"  # ok, error
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        """Duration in milliseconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class SpanCollector:
    """Collects and stores spans in memory.

    Thread-safe collector with a maximum capacity.
    """

    def __init__(self, max_spans: int = 1000):
        self.max_spans = max_spans
        self._spans: deque[Span] = deque(maxlen=max_spans)
        self._traces: dict[str, list[Span]] = {}
        self._lock = threading.Lock()

    def add_span(self, span: Span) -> None:
        """Add a span to the collector."""
        with self._lock:
            self._spans.append(span)

            # Group by trace
            if span.trace_id not in self._traces:
                self._traces[span.trace_id] = []
            self._traces[span.trace_id].append(span)

            # Cleanup old traces if we have too many
            if len(self._traces) > 100:
                # Remove oldest traces
                trace_ids = list(self._traces.keys())
                for trace_id in trace_ids[:50]:
                    del self._traces[trace_id]

    def get_spans(self, limit: int = 100) -> list[dict]:
        """Get recent spans as dicts."""
        with self._lock:
            spans = list(self._spans)[-limit:]
            return [s.to_dict() for s in reversed(spans)]

    def get_traces(self, limit: int = 20) -> list[dict]:
        """Get recent traces with their spans."""
        with self._lock:
            # Get most recent traces by looking at latest span time
            trace_times = []
            for trace_id, spans in self._traces.items():
                latest = max(s.start_time for s in spans)
                trace_times.append((trace_id, latest, spans))

            # Sort by latest time, descending
            trace_times.sort(key=lambda x: x[1], reverse=True)

            result = []
            for trace_id, _, spans in trace_times[:limit]:
                # Sort spans within trace by start time
                sorted_spans = sorted(spans, key=lambda s: s.start_time)

                # Calculate trace duration
                start = min(s.start_time for s in spans)
                end = max(s.end_time or s.start_time for s in spans)

                result.append(
                    {
                        "trace_id": trace_id,
                        "start_time": start,
                        "end_time": end,
                        "duration_ms": (end - start) * 1000,
                        "span_count": len(spans),
                        "root_span": sorted_spans[0].name if sorted_spans else None,
                        "spans": [s.to_dict() for s in sorted_spans],
                    }
                )

            return result

    def clear(self) -> None:
        """Clear all collected spans."""
        with self._lock:
            self._spans.clear()
            self._traces.clear()


# Global collector instance
_collector: SpanCollector | None = None


def get_collector() -> SpanCollector:
    """Get or create the global span collector."""
    global _collector
    if _collector is None:
        _collector = SpanCollector()
    return _collector
