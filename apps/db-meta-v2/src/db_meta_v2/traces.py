"""JSONL trace exporter for dbmeta.

Captures OpenTelemetry spans and writes them to JSONL files for
agent analysis and team knowledge sharing.

Structure:
    connections/{name}/traces/{user_hash}/YYYY-MM-DD.jsonl

Each line is a JSON object with span data:
    {"ts": ..., "name": ..., "trace_id": ..., "duration_ms": ..., "status": ..., "attrs": {...}}
"""

import json
import logging
import secrets
from datetime import datetime
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


def generate_user_id() -> str:
    """Generate a random stable user ID."""
    return secrets.token_hex(4)  # 8 character hex string


def get_user_id_from_config() -> str | None:
    """Get user_id from global config."""
    from db_meta_v2.cli import CONFIG_FILE, load_config

    if not CONFIG_FILE.exists():
        return None
    config = load_config()
    return config.get("user_id")


def set_user_id_in_config(user_id: str) -> None:
    """Set user_id in global config."""
    from db_meta_v2.cli import load_config, save_config

    config = load_config()
    config["user_id"] = user_id
    save_config(config)


def is_traces_enabled() -> bool:
    """Check if traces are enabled in config."""
    from db_meta_v2.cli import CONFIG_FILE, load_config

    if not CONFIG_FILE.exists():
        return False
    config = load_config()
    return config.get("traces_enabled", False)


def get_traces_dir(connection_path: Path, user_id: str) -> Path:
    """Get the traces directory for a connection and user."""
    return connection_path / "traces" / user_id


class JSONLSpanExporter(SpanExporter):
    """Export spans to JSONL files for agent analysis."""

    def __init__(self, connection_path: Path, user_id: str):
        """Initialize the exporter.

        Args:
            connection_path: Path to the connection directory
            user_id: User identifier for trace subdirectory
        """
        self.connection_path = connection_path
        self.user_id = user_id
        self.traces_dir = get_traces_dir(connection_path, user_id)
        self._current_file: Path | None = None
        self._current_date: str | None = None

    def _get_trace_file(self) -> Path:
        """Get the current trace file, rotating daily."""
        today = datetime.now().strftime("%Y-%m-%d")

        if self._current_date != today:
            self.traces_dir.mkdir(parents=True, exist_ok=True)
            self._current_file = self.traces_dir / f"{today}.jsonl"
            self._current_date = today

        return self._current_file

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        """Export spans to JSONL file."""
        if not spans:
            return SpanExportResult.SUCCESS

        try:
            trace_file = self._get_trace_file()

            with open(trace_file, "a") as f:
                for span in spans:
                    record = {
                        "ts": span.start_time,
                        "name": span.name,
                        "trace_id": format(span.context.trace_id, "032x"),
                        "span_id": format(span.context.span_id, "016x"),
                        "parent_id": (
                            format(span.parent.span_id, "016x") if span.parent else None
                        ),
                        "duration_ms": (span.end_time - span.start_time) / 1_000_000,
                        "status": span.status.status_code.name,
                        "attrs": dict(span.attributes) if span.attributes else {},
                    }

                    # Add events if any
                    if span.events:
                        record["events"] = [
                            {
                                "name": e.name,
                                "ts": e.timestamp,
                                "attrs": dict(e.attributes) if e.attributes else {},
                            }
                            for e in span.events
                        ]

                    f.write(json.dumps(record, default=str) + "\n")

            return SpanExportResult.SUCCESS

        except Exception as e:
            logger.error(f"Failed to export spans: {e}")
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any buffered spans."""
        return True


def setup_trace_exporter(connection_path: Path) -> JSONLSpanExporter | None:
    """Set up the JSONL trace exporter if traces are enabled.

    Args:
        connection_path: Path to the connection directory

    Returns:
        Configured exporter or None if traces disabled
    """
    if not is_traces_enabled():
        logger.debug("Traces disabled, skipping exporter setup")
        return None

    user_id = get_user_id_from_config()
    if not user_id:
        logger.warning("Traces enabled but no user_id configured")
        return None

    logger.info(f"Setting up trace exporter: {connection_path}/traces/{user_id}/")

    return JSONLSpanExporter(connection_path, user_id)
