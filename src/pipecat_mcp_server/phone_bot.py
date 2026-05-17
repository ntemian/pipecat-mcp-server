"""Phone bot — Pythia over Twilio PSTN.

Lifts voice_loop.py's pipeline (Whisper-MLX → Claude Sonnet 4.5 → 11Labs/Kokoro
→ LOSC MCP) onto Twilio Media Streams transport. Run:

    .venv/bin/phone-bot -t twilio --port 7861

Or directly via pipecat.runner.run:

    .venv/bin/python -m pipecat.runner.run -t twilio --port 7861 \\
        pipecat_mcp_server.phone_bot:bot

See ~/Projects/pipecat-mcp-server/TWILIO_SETUP.md for the full Phase 1-5 runbook.
"""

import os
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from mcp import StdioServerParameters
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.types import RunnerArguments, WebSocketRunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.mcp_service import MCPClient
from pipecat.services.whisper.stt import WhisperSTTServiceMLX
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

load_dotenv(override=True)


SYSTEM_PROMPT = """You are Pythia, Ntemis's voice agent. The caller is on a phone line — they may be a stranger.

CRITICAL voice-mode rules:
- Be CONCISE: 1-3 sentences per reply unless they ask for detail.
- No markdown, no bullets, no asterisks. Speak naturally.
- Numbers/dates/times: write as you would speak them.
- Match the caller's language: Greek or English.

IDENTITY VERIFICATION (phone-only — stricter than browser Pythia):
- Greet, ask who is calling and what they need.
- If the caller is NOT Ntemis or someone on his approved-callers list, do NOT execute outbound
  actions (no losc_send, no losc_gmail_send, no losc_calendar_invite). Take a message and end the call.
- Approved callers: Ntemis himself, Apollo Latsoudis, Γιώργος Λατσούδης (father), Έφη Γιοβάνου.
- If unsure, take a message and end the call.

You have LOSC tools (Ntemis's life operating system):
- Capture: losc_thought, losc_journal, losc_capture
- Query: losc_search, losc_calendar_upcoming, losc_what_do_i_know, losc_today
- Comms (gated by identity check above): losc_send (SMS), losc_gmail_send (email), losc_calendar_add

OUTBOUND SAFETY RAIL (when identity-verified):
- ALWAYS draft first, read it back, ask for explicit "send" confirmation.
- Anything other than "send" or "yes send" = treat as edit, not approval.
- Never auto-fire outbound tools.

Context: Athens timezone. Ntemis Latsoudis, lawyer at L+A.
"""


async def bot(runner_args: RunnerArguments):
    """Pipecat runner entry point — invoked by `pipecat.runner.run -t twilio`."""
    if not isinstance(runner_args, WebSocketRunnerArguments):
        raise TypeError(
            f"phone_bot.bot expects WebSocketRunnerArguments (Twilio transport), "
            f"got {type(runner_args).__name__}"
        )

    websocket = runner_args.websocket

    # Parse Twilio's "connected" + "start" frames to extract stream/call SIDs.
    transport_type, call_data = await parse_telephony_websocket(websocket)
    logger.info(f"telephony transport={transport_type} call_data={call_data}")

    stream_sid = call_data["stream_id"]
    call_sid = call_data.get("call_id")

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.environ["TWILIO_ACCOUNT_SID"],
        auth_token=os.environ["TWILIO_AUTH_TOKEN"],
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
            serializer=serializer,
        ),
    )

    stt = WhisperSTTServiceMLX(model="mlx-community/whisper-large-v3-turbo")

    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
    )

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        model=os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5"),
    )

    losc_mcp = MCPClient(
        server_params=StdioServerParameters(
            command="node",
            args=["/Users/ntemis/LOSC/mcp/dist/index.js"],
        ),
    )
    tools_schema = await losc_mcp.register_tools(llm)
    logger.info("LOSC MCP tools registered (phone bot)")

    context = llm.create_context(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=tools_schema,
    )
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    @transport.event_handler("on_client_connected")
    async def on_connected(transport: Any, client: Any):
        logger.info(f"phone call connected stream_sid={stream_sid} call_sid={call_sid}")
        # Twilio answers fast — prime an empty user turn so the LLM greets first.
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport: Any, client: Any):
        logger.info(f"phone call ended stream_sid={stream_sid} call_sid={call_sid}")
        await task.cancel()

    runner = PipelineRunner(handle_sigterm=True)
    await runner.run(task)


def run_via_runner():
    """CLI entry — delegates to pipecat.runner.run with this module as the bot target.

    Defaults to `-t twilio --port 7861` per TWILIO_SETUP.md Phase 2.
    """
    # Pipecat's runner discovers bot() via sys.modules["__main__"]. When invoked
    # through the `phone-bot` console script, __main__ is the auto-generated
    # wrapper — without this, the runner would fall back to scanning cwd for a
    # bot.py shim and pick up the wrong bot.
    sys.modules["__main__"] = sys.modules[__name__]

    defaults = {
        "--transport": "twilio",
        "--host": "0.0.0.0",
        "--port": os.getenv("PHONE_BOT_PORT", "7861"),
    }
    for flag, value in defaults.items():
        if flag not in sys.argv:
            sys.argv.extend([flag, value])

    from pipecat.runner.run import main as pipecat_main
    pipecat_main()


if __name__ == "__main__":
    run_via_runner()
