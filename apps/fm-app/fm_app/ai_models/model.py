from abc import ABC
from typing import Optional

from pydantic import BaseModel, Field

from fm_app.api.model import IntentAnalysis, QueryMetadata
from fm_app.config import Settings


class InvestigationStep(BaseModel):
    summary: Optional[str] = None
    user_intent: Optional[str] = None
    sql_request: Optional[str] = None
    response_to_user: Optional[str] = None
    user_friendly_assumptions: Optional[str] = None
    data_csv: Optional[str] = None
    intro: Optional[str] = None
    outro: Optional[str] = None
    labels: Optional[list[str]] = None
    rows: Optional[list[list[str]]] = None
    slot_schema: Optional[str] = None
    next_step_needed: bool = Field(default=True)
    self_check_passed: bool = Field(default=False)
    additional_data_request: Optional[str] = None


schema = {
    "type": "object",
    "properties": {
        "summary": {
            "type": ["string", "null"],
            "description": "A one-sentence succinct summary of the user's request",
        },
        "user_intent": {
            "type": ["string", "null"],
            "description": "User intent, as understood by the model",
        },
        "sql_request": {
            "type": ["string", "null"],
            "description": "SQL query to be executed, if applicable.",
        },
        "response_to_user": {
            "type": ["string", "null"],
            "description": "Message generated for the user",
        },
        "next_step_needed": {
            "type": ["boolean", "null"],
            "description": "Whether the next step is needed",
        },
        "user_friendly_assumptions": {
            "type": ["string", "null"],
            "description": "Assumptions made by the model to answer user's request",
        },
        "additional_data_request": {
            "type": ["string", "null"],
            "description": "Additional data request",
        },
        "self_check_passed": {
            "type": ["boolean", "null"],
            "description": "Is AI Assistant OK with the generated query",
        },
        "data_csv": {"type": ["string", "null"], "description": "Data in CSV format"},
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Labels for the data",
        },
        "rows": {
            "type": "array",
            "items": {"type": "array", "items": {"type": ["string", "null"]}},
            "description": "Rows of data",
        },
        "intro": {"type": ["string", "null"], "description": "Intro text"},
        "outro": {"type": ["string", "null"], "description": "Outro text"},
        "slot_schema": {
            "type": ["string", "null"],
            "description": "The closest Slot Schema for the request",
        },
    },
}


class ChatMessage(BaseModel):
    role: str
    content: str


# Define an abstract Pydantic model
class AIModel(BaseModel, ABC):
    llm_name: str = ""

    @staticmethod
    def init(settings: Settings):
        """Initializes the model client."""
        pass

    @staticmethod
    def get_name() -> str:
        """Must be implemented by subclasses."""
        return ""

    @staticmethod
    def get_specific_instructions() -> str:
        """Could be implemented by subclasses."""
        return ""

    @staticmethod
    def get_response(messages) -> str:
        """Must be implemented by subclasses."""
        pass

    @staticmethod
    def get_structured(
        messages: list[ChatMessage],
        step: type[InvestigationStep | QueryMetadata | IntentAnalysis],
        model_override: Optional[str] = None,
    ) -> InvestigationStep | QueryMetadata | IntentAnalysis:
        """Must be implemented by subclasses."""
        pass
