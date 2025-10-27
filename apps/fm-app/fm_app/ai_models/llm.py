import json
import re
from typing import Optional

import vertexai
from anthropic import Anthropic
from google.oauth2 import service_account
from openai import OpenAI
from vertexai.generative_models import Content, GenerationConfig, GenerativeModel, Part

from fm_app.ai_models.model import AIModel, ChatMessage, InvestigationStep, schema
from fm_app.api.model import IntentAnalysis, QueryMetadata


def normalize_schema(sch):
    if isinstance(sch, dict):
        if "type" in sch and isinstance(sch["type"], list):
            sch["type"] = next((t for t in sch["type"] if t != "null"), sch["type"][0])
        for k, v in sch.items():
            sch[k] = normalize_schema(v)
    elif isinstance(sch, list):
        return [normalize_schema(i) for i in sch]
    return sch


def fix_nulls(d):
    return {k: (None if v == "null" else v) for k, v in d.items()}


def fix_nulls_and_convert_rows(d):
    def stringify_rows(rows):
        if isinstance(rows, list):
            return [[str(cell) for cell in row] for row in rows]
        return rows

    fixed = {k: (None if v == "null" else v) for k, v in d.items()}

    if "rows" in fixed and fixed["rows"] is not None:
        fixed["rows"] = stringify_rows(fixed["rows"])

    return fixed


def fix_multiline_strings(json_text: str) -> str:
    # Match inside quotes but spanning multiple lines, and replace newlines with \n
    def replacer(match):
        text = match.group(0)
        text_fixed = text.replace("\n", "\\n")
        return text_fixed

    # Replace newlines inside quoted strings
    json_text = re.sub(
        r'"([^"\\]*(?:\\.[^"\\]*)*)"', replacer, json_text, flags=re.DOTALL
    )
    return json_text


def clean(text):
    return "".join(c for c in text if (c == "\n" or c == "\r" or 32 <= ord(c) <= 126))


def openai_to_gemini(messages: list[ChatMessage]):
    formatted_input = []

    role_map = {"system": "System:", "user": "User:", "assistant": "Assistant:"}

    for msg in messages:
        role = role_map.get(msg["role"], "User")  # Default to "User" if unknown role
        formatted_input.append(f"{role} {msg['content']}")

    return "\n".join(formatted_input)


class OpenAIModel(AIModel):
    _client: OpenAI = None  # Static client

    model_config = {"arbitrary_types_allowed": True}

    @staticmethod
    def init(settings):
        """Initializes and returns the OpenAI client (singleton)."""
        # if OpenAIModel._client is None:
        OpenAIModel._client = OpenAI(api_key=settings.openai_api_key)
        OpenAIModel.llm_name = settings.openai_llm_name
        return OpenAIModel._client

    @staticmethod
    def get_name() -> str:
        return "open-ai"

    @staticmethod
    def get_response(messages) -> str:
        """Generates a response from OpenAI."""
        if OpenAIModel._client is None:
            raise ValueError(
                "Client not initialized. Call `get_client(settings)` first."
            )
        resp = OpenAIModel._client.chat.completions.create(
            temperature=0, model=OpenAIModel.llm_name, messages=messages
        )
        return resp.choices[0].message.content

    @staticmethod
    def get_structured(
        messages: list[ChatMessage],
        step: type[InvestigationStep | QueryMetadata | IntentAnalysis],
        model_override: Optional[str] = None,
    ) -> InvestigationStep | QueryMetadata | IntentAnalysis:
        """Generates a structured response."""
        if OpenAIModel._client is None:
            raise ValueError(
                "Client not initialized. Call `get_client(settings)` first."
            )

        model_name = model_override or OpenAIModel.llm_name
        temperature = 1 if model_name.startswith("gpt-5") else 0
        resp = OpenAIModel._client.chat.completions.create(
            temperature=temperature,
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            extra_headers={
                "OpenAI-Beta": "prompt-caching"
            }
        )
        data = json.loads(
            resp.choices[0].message.content, object_hook=fix_nulls_and_convert_rows
        )
        print("LLM OUT", model_name, temperature, data)
        return step(**data)


class DeepSeekModel(AIModel):
    _client = None  # Static client

    @staticmethod
    def init(settings):
        """Initializes the static client once."""
        # if DeepSeekModel._client is None:  # Ensure it's only initialized once
        DeepSeekModel.llm_name = settings.deepseek_llm_name
        DeepSeekModel._client = OpenAI(
            base_url=settings.deepseek_ai_api_url, api_key=settings.deepseek_ai_api_key
        )

    @staticmethod
    def get_name() -> str:
        return "deep-seek"

    @staticmethod
    def get_response(messages) -> str:
        resp = DeepSeekModel._client.chat.completions.create(
            temperature=0, model=DeepSeekModel.llm_name, messages=messages
        )
        return resp.choices[0].message.content

    @staticmethod
    def get_structured(
        messages: list[ChatMessage],
        step: type[InvestigationStep],
        model_override: Optional[str] = None,
    ) -> InvestigationStep:
        # resp = DeepSeekModel._client.beta.chat.completions.parse(
        model_name = model_override or DeepSeekModel.llm_name
        resp = DeepSeekModel._client.chat.completions.create(
            temperature=0,
            # model="deepseek-reasoner",
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            # response_format=step
        )
        data = json.loads(
            resp.choices[0].message.content, object_hook=fix_nulls_and_convert_rows
        )
        return InvestigationStep(**data)


class GeminiModel(AIModel):
    _client: GenerativeModel = None  # Static client
    model_config = {"arbitrary_types_allowed": True}

    @staticmethod
    def init(settings):
        """Initializes the static client once."""
        # if cls._client is None:  # Ensure it's only initialized once
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        cred_file = settings.google_cred_file
        project_id = settings.google_project_id
        credentials = service_account.Credentials.from_service_account_file(
            cred_file, scopes=scopes
        )
        vertexai.init(project=project_id, credentials=credentials)
        GeminiModel.llm_name = settings.google_llm_name
        model = GenerativeModel(
            model_name=GeminiModel.llm_name, generation_config={"temperature": 0}
        )
        GeminiModel._client = model

    @staticmethod
    def get_name() -> str:
        return "gemini"

    @staticmethod
    def get_response(messages) -> str:
        chat = GeminiModel._client.start_chat()
        resp = chat.send_message(messages)
        return resp.text

    @staticmethod
    def get_structured(
        messages: list[ChatMessage],
        step: type[InvestigationStep],
        model_override: Optional[str] = None,
    ) -> InvestigationStep:
        contents = []
        system_instruction = "\n".join(
            m["content"] for m in messages if m["role"] == "system"
        )
        for msg in messages:
            if msg["role"] == "system":
                continue
            contents.append(
                Content(role=msg["role"], parts=[Part.from_text(msg["content"])])
            )

        GeminiModel._client._system_instruction = system_instruction
        resp = GeminiModel._client.generate_content(
            contents=contents,
            generation_config=GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=normalize_schema(schema),
            ),
            stream=False,
        )
        data = json.loads(
            resp.candidates[0].content.parts[0].text,
            object_hook=fix_nulls_and_convert_rows,
        )
        return InvestigationStep(**data)


class AnthropicModel(AIModel):
    _client: Anthropic = None

    model_config = {"arbitrary_types_allowed": True}

    @staticmethod
    def init(settings):
        """Initializes and returns the Anthropic client (singleton)."""
        AnthropicModel._client = Anthropic(api_key=settings.anthropic_api_key)
        AnthropicModel.llm_name = settings.anthropic_llm_name
        return AnthropicModel._client

    @staticmethod
    def get_name() -> str:
        return "anthropic"

    @staticmethod
    def get_response(messages) -> str:
        """Generates a response from Anthropic."""
        if AnthropicModel._client is None:
            raise ValueError("Client not initialized. Call `init(settings)` first.")

        # Anthropic uses a single prompt string
        # prompt = AnthropicModel._build_prompt(messages)
        filtered_messages = []
        system_instruction = ""
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = f"{system_instruction}{msg['content']}"
            else:
                filtered_messages.append(msg)

        response = AnthropicModel._client.messages.create(
            model=AnthropicModel.llm_name,
            max_tokens=8192,  # max for Anthropic
            temperature=0,
            system=system_instruction,
            messages=filtered_messages,
        )
        return response.content[0].text

    @staticmethod
    def get_structured(
        messages: list[ChatMessage],
        step: type[InvestigationStep],
        model_override: Optional[str] = None,
    ) -> InvestigationStep:
        """Generates a structured (JSON) response from Anthropic."""
        if AnthropicModel._client is None:
            raise ValueError("Client not initialized. Call `init(settings)` first.")

        filtered_messages = []
        system_instruction = (
            f"Return only a valid JSON object matching the expected schema:\n{schema}\n"
        )
        for msg in messages:
            if msg["role"] == "system":
                system_instruction += msg["content"]
            else:
                filtered_messages.append(msg)

        print("system_instruction", len(system_instruction))
        print("messages", len(filtered_messages))
        content = ""
        model_name = model_override or AnthropicModel.llm_name

        try:  # Anthropic uses a single prompt string
            with AnthropicModel._client.messages.stream(
                model=model_name,
                max_tokens=8192,  # max for Anthropic
                temperature=0,
                system=system_instruction,
                messages=filtered_messages,
            ) as stream:
                for event in stream.text_stream:
                    try:
                        delta = clean(event)
                        content += delta
                    except Exception as e:
                        print("Error in streaming:", e)

            content = fix_multiline_strings(content)
            if content == "":
                print("Empty response from Anthropic")
                return InvestigationStep()
            data = json.loads(content, object_hook=fix_nulls_and_convert_rows)
            return InvestigationStep(**data)

        except Exception as e:
            print("Error in get_structured:", e)
            return InvestigationStep()

    @staticmethod
    def _build_prompt(messages: list[dict]) -> str:
        """Builds a Claude-compatible prompt from a list of role-based messages."""
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                parts.append(f"\n\nHuman: {content}")
            elif role == "assistant":
                parts.append(f"\n\nAssistant: {content}")
            elif role == "system":
                continue
            else:
                raise ValueError(f"Unsupported role: {role}")
        parts.append("\n\nAssistant:")
        return "".join(parts)
