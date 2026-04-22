from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

import tools.llm as llm_module
from tools.llm import (
    AnthropicProvider,
    GeminiProvider,
    LLMError,
    LLMResponse,
    OpenAIProvider,
    get_active_llm,
    get_llm,
    init_llm,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_cfg(provider: str, model: str = "test-model") -> MagicMock:
    cfg = MagicMock()
    cfg.llm.provider = provider
    cfg.llm.model = model
    return cfg


def _make_anthropic_response(text: str = "Hello") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text

    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage.input_tokens = 10
    resp.usage.output_tokens = 20
    resp.model = "claude-sonnet-4-6"
    return resp


def _rate_limit_error() -> Exception:
    import anthropic
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return anthropic.RateLimitError("Rate limited", response=response, body=None)


# ── factory ───────────────────────────────────────────────────────────────────

def test_get_llm_returns_anthropic_for_anthropic_config():
    assert isinstance(get_llm(_make_cfg("anthropic")), AnthropicProvider)


def test_get_llm_returns_gemini_for_gemini_config():
    assert isinstance(get_llm(_make_cfg("gemini")), GeminiProvider)


def test_get_llm_returns_openai_for_openai_config():
    assert isinstance(get_llm(_make_cfg("openai")), OpenAIProvider)


def test_get_llm_raises_for_unknown_provider():
    with pytest.raises(LLMError, match="Unknown provider"):
        get_llm(_make_cfg("cohere"))


# ── AnthropicProvider ─────────────────────────────────────────────────────────

def test_anthropic_provider_complete_returns_llm_response():
    provider = AnthropicProvider(_make_cfg("anthropic"))

    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _make_anthropic_response("Hi there")
        result = provider.complete(
            [{"role": "user", "content": "Hello"}],
            system_prompt="You are helpful.",
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "Hi there"
    assert result.stop_reason == "end_turn"
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert result.model == "claude-sonnet-4-6"


def test_anthropic_provider_retries_on_429():
    provider = AnthropicProvider(_make_cfg("anthropic"))
    error = _rate_limit_error()

    with patch("anthropic.Anthropic") as mock_cls, \
         patch("tools.llm.time.sleep") as mock_sleep:
        mock_create = mock_cls.return_value.messages.create
        mock_create.side_effect = [error, error, _make_anthropic_response()]

        result = provider.complete([{"role": "user", "content": "Hi"}], "System")

    assert mock_create.call_count == 3
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0].args[0] == 1  # first delay
    assert mock_sleep.call_args_list[1].args[0] == 2  # second delay
    assert isinstance(result, LLMResponse)


def test_anthropic_provider_raises_llm_error_after_max_retries():
    provider = AnthropicProvider(_make_cfg("anthropic"))
    error = _rate_limit_error()

    with patch("anthropic.Anthropic") as mock_cls, \
         patch("tools.llm.time.sleep"):
        mock_cls.return_value.messages.create.side_effect = [error, error, error]

        with pytest.raises(LLMError):
            provider.complete([{"role": "user", "content": "Hi"}], "System")


# ── GeminiProvider ────────────────────────────────────────────────────────────

def _make_gemini_mocks() -> tuple[MagicMock, MagicMock]:
    """Returns (fake_genai_module, fake_model_instance)."""
    fake_model = MagicMock()
    fake_response = MagicMock()
    fake_response.text = "Gemini answer"
    fake_response.usage_metadata.prompt_token_count = 8
    fake_response.usage_metadata.candidates_token_count = 16
    fake_model.generate_content.return_value = fake_response

    fake_genai = MagicMock()
    fake_genai.GenerativeModel.return_value = fake_model

    return fake_genai, fake_model


def test_gemini_provider_maps_messages_correctly():
    provider = GeminiProvider(_make_cfg("gemini", "gemini-1.5-pro"))
    fake_genai, fake_model = _make_gemini_mocks()

    with patch.dict("sys.modules", {"google.generativeai": fake_genai}), \
         patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        provider.complete(
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "Tell me more"},
            ],
            system_prompt="Be concise.",
        )

    contents = fake_model.generate_content.call_args.args[0]
    assert contents[0] == {"role": "user", "parts": ["Hello"]}
    assert contents[1] == {"role": "model", "parts": ["Hi there"]}  # assistant -> model
    assert contents[2] == {"role": "user", "parts": ["Tell me more"]}

    fake_genai.GenerativeModel.assert_called_once_with(
        model_name="gemini-1.5-pro",
        system_instruction="Be concise.",
    )


def test_gemini_provider_returns_llm_response():
    provider = GeminiProvider(_make_cfg("gemini", "gemini-1.5-pro"))
    fake_genai, _ = _make_gemini_mocks()

    with patch.dict("sys.modules", {"google.generativeai": fake_genai}), \
         patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        result = provider.complete([{"role": "user", "content": "Hi"}], "System")

    assert isinstance(result, LLMResponse)
    assert result.text == "Gemini answer"
    assert result.input_tokens == 8
    assert result.output_tokens == 16


def test_gemini_provider_raises_if_no_api_key():
    provider = GeminiProvider(_make_cfg("gemini"))
    fake_genai = MagicMock()

    with patch.dict("sys.modules", {"google.generativeai": fake_genai}), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(LLMError, match="GEMINI_API_KEY"):
            provider.complete([{"role": "user", "content": "Hi"}], "System")


# ── OpenAIProvider ────────────────────────────────────────────────────────────

def _make_openai_mocks(text: str = "OpenAI answer") -> tuple[MagicMock, MagicMock]:
    """Returns (fake_openai_module, fake_client)."""
    fake_choice = MagicMock()
    fake_choice.message.content = text
    fake_choice.finish_reason = "stop"

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_response.usage.prompt_tokens = 5
    fake_response.usage.completion_tokens = 15
    fake_response.model = "gpt-4o"

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_openai = MagicMock()
    fake_openai.OpenAI.return_value = fake_client

    return fake_openai, fake_client


def test_openai_provider_prepends_system_message():
    provider = OpenAIProvider(_make_cfg("openai", "gpt-4o"))
    fake_openai, fake_client = _make_openai_mocks()

    with patch.dict("sys.modules", {"openai": fake_openai}), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        provider.complete(
            [{"role": "user", "content": "Hello"}],
            system_prompt="You are a job search assistant.",
        )

    messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "You are a job search assistant."}
    assert messages[1] == {"role": "user", "content": "Hello"}


def test_openai_provider_returns_llm_response():
    provider = OpenAIProvider(_make_cfg("openai", "gpt-4o"))
    fake_openai, _ = _make_openai_mocks()

    with patch.dict("sys.modules", {"openai": fake_openai}), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        result = provider.complete([{"role": "user", "content": "Hi"}], "System")

    assert isinstance(result, LLMResponse)
    assert result.text == "OpenAI answer"
    assert result.stop_reason == "stop"
    assert result.input_tokens == 5
    assert result.output_tokens == 15


def test_openai_provider_raises_if_no_api_key():
    provider = OpenAIProvider(_make_cfg("openai"))
    fake_openai = MagicMock()

    with patch.dict("sys.modules", {"openai": fake_openai}), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(LLMError, match="OPENAI_API_KEY"):
            provider.complete([{"role": "user", "content": "Hi"}], "System")


# ── singleton ─────────────────────────────────────────────────────────────────

def test_get_active_llm_raises_if_not_initialised(monkeypatch):
    monkeypatch.setattr(llm_module, "_llm", None)
    with pytest.raises(RuntimeError, match="Call init_llm"):
        get_active_llm()


def test_init_llm_sets_module_singleton(monkeypatch):
    monkeypatch.setattr(llm_module, "_llm", None)
    mock_provider = MagicMock(spec=AnthropicProvider)

    with patch("tools.llm.get_llm", return_value=mock_provider):
        init_llm(_make_cfg("anthropic"))

    assert llm_module._llm is mock_provider
    assert get_active_llm() is mock_provider
