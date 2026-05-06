from __future__ import annotations

import importlib
import logging
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


_MAX_ATTEMPTS = 3


def _backoff_seconds(attempt: int) -> int:
    """attempt 0 -> 2s, attempt 1 -> 4s, attempt 2 -> 8s."""
    return 2 ** (attempt + 1)


class _NoMatchError(Exception):
    """Sentinel used in `except` tuples when a provider SDK isn't installed."""


# Provider-specific retry exception classes are imported defensively so that
# tests can stub a provider's SDK via sys.modules without installing it.
try:
    from anthropic._exceptions import (
        OverloadedError as _AnthropicOverloaded,
        RateLimitError as _AnthropicRateLimit,
    )
    _ANTHROPIC_RETRY_ERRORS: tuple[type[BaseException], ...] = (
        _AnthropicOverloaded, _AnthropicRateLimit,
    )
except ImportError:
    _ANTHROPIC_RETRY_ERRORS = (_NoMatchError,)

try:
    from google.api_core.exceptions import (
        ResourceExhausted as _GeminiResourceExhausted,
        ServiceUnavailable as _GeminiServiceUnavailable,
    )
    _GEMINI_RETRY_ERRORS: tuple[type[BaseException], ...] = (
        _GeminiResourceExhausted, _GeminiServiceUnavailable,
    )
except ImportError:
    _GEMINI_RETRY_ERRORS = (_NoMatchError,)

try:
    from openai import (
        APIStatusError as _OpenAIAPIStatusError,
        RateLimitError as _OpenAIRateLimit,
    )
    _OPENAI_RETRY_ERRORS: tuple[type[BaseException], ...] = (
        _OpenAIRateLimit, _OpenAIAPIStatusError,
    )
except ImportError:
    _OPENAI_RETRY_ERRORS = (_NoMatchError,)


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

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = client.messages.create(**kwargs)
                text = next(
                    (b.text for b in response.content if b.type == "text"),
                    "",
                )
                return LLMResponse(
                    text=text,
                    stop_reason=response.stop_reason or "",
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    model=response.model,
                )
            except _ANTHROPIC_RETRY_ERRORS as e:
                last_error = e
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LLMError(
                        f"Anthropic API unavailable after "
                        f"{_MAX_ATTEMPTS} retries: {e}"
                    ) from e
                wait = _backoff_seconds(attempt)
                logging.warning(
                    f"Anthropic {type(e).__name__} on attempt "
                    f"{attempt + 1}/{_MAX_ATTEMPTS}, retrying in {wait}s"
                )
                time.sleep(wait)
            except Exception as e:
                raise LLMError(str(e)) from e

        raise LLMError(f"Unexpected retry exhaustion: {last_error}")


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

        contents = [
            {
                "role": "model" if msg["role"] == "assistant" else msg["role"],
                "parts": [msg["content"]],
            }
            for msg in messages
        ]

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                model = genai.GenerativeModel(
                    model_name=self._model,
                    system_instruction=system_prompt,
                )
                response = model.generate_content(contents)
                return LLMResponse(
                    text=response.text,
                    stop_reason="end_turn",
                    input_tokens=response.usage_metadata.prompt_token_count,
                    output_tokens=response.usage_metadata.candidates_token_count,
                    model=self._model,
                )
            except _GEMINI_RETRY_ERRORS as e:
                last_error = e
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LLMError(
                        f"Gemini API unavailable after "
                        f"{_MAX_ATTEMPTS} retries: {e}"
                    ) from e
                wait = _backoff_seconds(attempt)
                logging.warning(
                    f"Gemini {type(e).__name__} on attempt "
                    f"{attempt + 1}/{_MAX_ATTEMPTS}, retrying in {wait}s"
                )
                time.sleep(wait)
            except Exception as e:
                raise LLMError(str(e)) from e

        raise LLMError(f"Unexpected retry exhaustion: {last_error}")


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

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = client.chat.completions.create(
                    model=self._model,
                    messages=all_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                choice = response.choices[0]
                return LLMResponse(
                    text=choice.message.content or "",
                    stop_reason=choice.finish_reason or "",
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    model=response.model,
                )
            except _OPENAI_RETRY_ERRORS as e:
                # APIStatusError covers many statuses; only retry 429/529
                status_code = getattr(e, "status_code", None)
                is_rate_limit = isinstance(e, _OpenAIRateLimit) if (
                    _OPENAI_RETRY_ERRORS is not (_NoMatchError,)
                ) else False
                if not is_rate_limit and status_code not in (429, 529):
                    raise LLMError(str(e)) from e
                last_error = e
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LLMError(
                        f"OpenAI API unavailable after "
                        f"{_MAX_ATTEMPTS} retries: {e}"
                    ) from e
                wait = _backoff_seconds(attempt)
                logging.warning(
                    f"OpenAI {type(e).__name__} on attempt "
                    f"{attempt + 1}/{_MAX_ATTEMPTS}, retrying in {wait}s"
                )
                time.sleep(wait)
            except Exception as e:
                raise LLMError(str(e)) from e

        raise LLMError(f"Unexpected retry exhaustion: {last_error}")


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
