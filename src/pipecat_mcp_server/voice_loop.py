"""Voice loop — Pipecat WebRTC + Whisper-MLX + Anthropic + 11Labs + LOSC MCP tools.

Run:
    .venv/bin/python -m pipecat_mcp_server.voice_loop
    # or:
    .venv/bin/python -m pipecat_mcp_server.voice_loop --port 7860 --host 0.0.0.0

Open http://localhost:7860/client in a browser to talk. For phone access,
expose port 7860 via Tailscale funnel.
"""

import os
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from mcp import StdioServerParameters
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.mcp_service import MCPClient
from pipecat.services.whisper.stt import WhisperSTTServiceMLX
from pipecat.transports.base_transport import TransportParams

load_dotenv(override=True)


SYSTEM_PROMPT = """You are Claude, Ntemis's voice copilot for the road. He speaks Greek or English — match him.

CRITICAL voice-mode rules:
- Be CONCISE: 1-3 sentences per reply unless he asks for detail. He's driving.
- No markdown, no bullets, no asterisks. Speak naturally.
- Numbers/dates/times: write as you'd speak them.

You have LOSC tools (his life operating system):
- Capture: losc_thought, losc_journal, losc_capture
- Query: losc_search, losc_calendar_upcoming, losc_what_do_i_know, losc_today
- Comms: losc_send (SMS), losc_gmail_send (email), losc_calendar_add

SAFETY RAIL — outbound communications (SMS/email/calendar):
- ALWAYS draft first, read it back, ask for explicit "send" confirmation.
- Anything other than "send" or "yes send" = treat as edit, not approval.
- Never auto-fire outbound tools. Ntemis's 5-step rule (draft → show → edits → FINAL → wait "send").

Context: Athens timezone. Ntemis Latsoudis, lawyer at L+A. Family: Ajax (son, always home), Clio (daughter, biweekly), brother Apollo. Major dates: 5 June 2026 criminal trial.
"""


async def bot(runner_args: RunnerArguments):
    """Pipecat runner entry point."""
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.4)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
    }
    transport = await create_transport(runner_args, transport_params)

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
    logger.info("LOSC MCP tools registered")

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
        logger.info("Client connected — sending greeting")
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport: Any, client: Any):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigterm=True)
    await runner.run(task)


def main():
    """CLI entry point."""
    defaults = {
        "--transport": "webrtc",
        "--host": "0.0.0.0",
        "--port": os.getenv("VOICE_LOOP_PORT", "7860"),
    }
    for flag, value in defaults.items():
        if flag not in sys.argv:
            sys.argv.extend([flag, value])

    from pipecat.runner.run import main as pipecat_main
    pipecat_main()


if __name__ == "__main__":
    main()
