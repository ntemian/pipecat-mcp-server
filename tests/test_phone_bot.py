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


# ── Hard caller gate ─────────────────────────────────────────────────────────

def test_allowlist_parses_env(monkeypatch):
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", " +306971234567 , +302101112222 ")
    assert pb._allowed_callers() == {"+306971234567", "+302101112222"}


def test_allowlist_empty_is_fail_closed(monkeypatch):
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "")
    assert pb._allowed_callers() == set()


@pytest.mark.asyncio
async def test_gate_denies_when_allowlist_empty(monkeypatch):
    """No allowlist configured → deny everyone, and never hit the network."""
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "")
    called = {"n": 0}
    monkeypatch.setattr(pb, "_fetch_twilio_caller", lambda sid: called.__setitem__("n", called["n"] + 1) or "+1555")
    allowed, caller = await pb._caller_is_allowed("CA_test")
    assert allowed is False
    assert called["n"] == 0  # short-circuits before any REST lookup


@pytest.mark.asyncio
async def test_gate_denies_missing_call_sid(monkeypatch):
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "+306971234567")
    allowed, _ = await pb._caller_is_allowed(None)
    assert allowed is False


@pytest.mark.asyncio
async def test_gate_allows_listed_caller(monkeypatch):
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "+306971234567")
    monkeypatch.setattr(pb, "_fetch_twilio_caller", lambda sid: "+306971234567")
    allowed, caller = await pb._caller_is_allowed("CA_test")
    assert allowed is True and caller == "+306971234567"


@pytest.mark.asyncio
async def test_gate_denies_unlisted_caller(monkeypatch):
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "+306971234567")
    monkeypatch.setattr(pb, "_fetch_twilio_caller", lambda sid: "+15558675309")
    allowed, caller = await pb._caller_is_allowed("CA_test")
    assert allowed is False


@pytest.mark.asyncio
async def test_gate_denies_on_lookup_failure(monkeypatch):
    """Twilio REST error → fail closed (deny), never raise into the caller path."""
    import pipecat_mcp_server.phone_bot as pb

    monkeypatch.setenv("PYTHIA_ALLOWED_CALLERS", "+306971234567")

    def boom(sid):
        raise RuntimeError("twilio down")

    monkeypatch.setattr(pb, "_fetch_twilio_caller", boom)
    allowed, _ = await pb._caller_is_allowed("CA_test")
    assert allowed is False
