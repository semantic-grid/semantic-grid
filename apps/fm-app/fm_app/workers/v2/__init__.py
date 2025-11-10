"""
V2 Workers - Agentic message-based processing.

Uses Anthropic Agents SDK with MCP tools for flexible, non-deterministic workflows.
"""

from fm_app.workers.v2.model import (
    FlowTypeV2,
    MessageProcessingStrategy,
    WorkerMessageRequest,
    WorkerMessageResponse,
)
from fm_app.workers.v2.worker_v2 import V2AgentWorker

__all__ = [
    "FlowTypeV2",
    "MessageProcessingStrategy",
    "WorkerMessageRequest",
    "WorkerMessageResponse",
    "V2AgentWorker",
]
