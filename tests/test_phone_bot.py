"""Offline guard tests for phone_bot — Pythia over Twilio PSTN.

These are deterministic and require no network, models, or Twilio creds. They lock
in the two things that have bitten this STEAL before:
  1. The module imports against the installed pipecat (catches API drift like the
     removed `llm.create_context` → `OpenAILLMContext` regression on pipecat 0.0.103).
  2. `bot()` refuses a non-WebSocket runner (Twilio transport invariant).
"""
import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("ELEVENLABS_API_KEY", "dummy")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_dummy")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "dummy")


def test_phone_bot_imports():
    import pipecat_mcp_server.phone_bot as pb

    assert hasattr(pb, "bot"), "runner entry point bot() missing"
    assert hasattr(pb, "run_via_runner"), "CLI wrapper run_via_runner() missing"


def test_uses_supported_context_api():
    """Regression guard: phone_bot must NOT call the removed llm.create_context().

    pipecat 0.0.103 dropped AnthropicLLMService.create_context; the correct path is
    constructing an OpenAILLMContext and passing it to create_context_aggregator.
    """
    import inspect

    import pipecat_mcp_server.phone_bot as pb

    src = inspect.getsource(pb)
    assert "llm.create_context(" not in src, "regressed to removed llm.create_context() API"
    assert "OpenAILLMContext(" in src, "must build OpenAILLMContext explicitly"


def test_context_build_path_works():
    """The exact context-build path bot() uses must construct without error."""
    from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
    from pipecat.services.anthropic.llm import AnthropicLLMService

    llm = AnthropicLLMService(api_key="dummy", model="claude-sonnet-4-5-20250929")
    context = OpenAILLMContext(messages=[{"role": "system", "content": "x"}], tools=[])
    agg = llm.create_context_aggregator(context)
    assert agg.user() is not None
    assert agg.assistant() is not None


@pytest.mark.asyncio
async def test_bot_rejects_non_websocket_runner():
    """Twilio transport invariant: bot() must reject anything but WebSocket args."""
    import pipecat_mcp_server.phone_bot as pb

    class NotWebSocketArgs:
        pass

    with pytest.raises(TypeError):
        await pb.bot(NotWebSocketArgs())
