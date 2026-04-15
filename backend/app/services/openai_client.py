import json
from functools import cached_property
from typing import Any

from openai import OpenAI, OpenAIError

from app.core.config import get_settings


class OpenAIService:
    @cached_property
    def client(self) -> OpenAI | None:
        settings = get_settings()
        if not settings.openai_api_key:
            return None
        return OpenAI(api_key=settings.openai_api_key)

    def complete_json(self, instructions: str, user_input: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        settings = get_settings()
        try:
            if hasattr(self.client, "responses"):
                response = self.client.responses.create(
                    model=settings.openai_model,
                    instructions=instructions,
                    input=user_input,
                    text={"format": {"type": "json_object"}},
                    temperature=0,
                )
                raw_text = response.output_text
            else:
                response = self.client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": user_input},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                raw_text = response.choices[0].message.content or "{}"
            return json.loads(raw_text)
        except (OpenAIError, Exception):
            return None

    def complete_text(self, instructions: str, user_input: str) -> str | None:
        if not self.client:
            return None
        settings = get_settings()
        try:
            if hasattr(self.client, "responses"):
                response = self.client.responses.create(
                    model=settings.openai_model,
                    instructions=instructions,
                    input=user_input,
                    temperature=0.2,
                )
                return response.output_text
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input},
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content
        except OpenAIError:
            return None

    def embed(self, text: str) -> list[float] | None:
        if not self.client:
            return None
        settings = get_settings()
        try:
            response = self.client.embeddings.create(input=text, model=settings.openai_embedding_model)
            return response.data[0].embedding
        except OpenAIError:
            return None


openai_service = OpenAIService()
