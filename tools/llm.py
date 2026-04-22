from __future__ import annotations

import importlib
import os
import time
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class LLMError(Exception):
    ...


class LLMResponse(BaseModel):
    text: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        ...


_RETRY_DELAYS = [1, 2, 4]
_MAX_ATTEMPTS = 3


class AnthropicProvider(LLMProvider):
    def __init__(self, config) -> None:
        self._model = config.llm.model

    def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        import anthropic
        from anthropic import APIStatusError

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY not set in environment")
        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = client.messages.create(**kwargs)
                break
            except APIStatusError as e:
                if e.status_code in (429, 529) and attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise LLMError(str(e)) from e

        text = next(
            (block.text for block in response.content if block.type == "text"),
            "",
        )
        return LLMResponse(
            text=text,
            stop_reason=response.stop_reason or "",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )


class GeminiProvider(LLMProvider):
    def __init__(self, config) -> None:
        self._model = config.llm.model

    def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        genai = importlib.import_module("google.generativeai")

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY not set in environment")

        genai.configure(api_key=api_key)

        # Gemini uses "model" role where Anthropic uses "assistant"
        contents = [
            {
                "role": "model" if msg["role"] == "assistant" else msg["role"],
                "parts": [msg["content"]],
            }
            for msg in messages
        ]

        try:
            model = genai.GenerativeModel(
                model_name=self._model,
                system_instruction=system_prompt,
            )
            response = model.generate_content(contents)
        except Exception as e:
            raise LLMError(str(e)) from e

        return LLMResponse(
            text=response.text,
            stop_reason="end_turn",
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model=self._model,
        )


class OpenAIProvider(LLMProvider):
    def __init__(self, config) -> None:
        self._model = config.llm.model

    def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY not set in environment")

        client = openai.OpenAI(api_key=api_key)
        all_messages = [{"role": "system", "content": system_prompt}, *messages]

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LLMError(str(e)) from e

        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            stop_reason=choice.finish_reason or "",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=response.model,
        )


def get_llm(config) -> LLMProvider:
    match config.llm.provider:
        case "anthropic":
            return AnthropicProvider(config)
        case "gemini":
            return GeminiProvider(config)
        case "openai":
            return OpenAIProvider(config)
        case _:
            raise LLMError(f"Unknown provider: {config.llm.provider}")


_llm: LLMProvider | None = None


def init_llm(config) -> None:
    global _llm
    _llm = get_llm(config)


def get_active_llm() -> LLMProvider:
    if _llm is None:
        raise RuntimeError("LLM not initialised. Call init_llm(config) first.")
    return _llm
