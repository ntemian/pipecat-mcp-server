# Voice Loop — Hands-Free Claude + LOSC for Driving

WebRTC voice agent: phone browser ↔ Tailscale ↔ Mac (Whisper-MLX → Claude Sonnet 4.5 → 11Labs) with full LOSC tool access.

## One-time setup

```bash
cd ~/Projects/pipecat-mcp-server
cp .env.example .env
# Edit .env — paste ANTHROPIC_API_KEY and ELEVENLABS_API_KEY
```

## Start the agent (on the Mac, before driving)

```bash
cd ~/Projects/pipecat-mcp-server
.venv/bin/voice-loop
# → "🚀 Bot ready! → Open http://0.0.0.0:7860/client in your browser"
```

First run downloads Whisper-MLX model (~1.5GB). Subsequent starts: ~3sec.

## Expose to phone via Tailscale funnel

In a second terminal:

```bash
tailscale funnel --bg --https=10000 7860
```

Phone URL: `https://ntemiss-mbp.tailddb317.ts.net:10000/client`

(Port 10000 instead of 8443 because Ntemis's funnel 8443 is already proxying another local service on `127.0.0.1:8001`.)

(HTTPS is required because mobile browsers block `getUserMedia` on plain HTTP.)

## In the car

1. Connect phone to vehicle Bluetooth (audio routes there automatically).
2. Open the URL above in Chrome on the phone (Galaxy S24).
3. Tap "Connect" → grant mic permission.
4. Talk. Claude greets, you reply, the loop runs until you disconnect.

## Voice safety rail

Outbound comms (SMS/email/calendar) require explicit "send" confirmation. Anything else = edit. Built into the system prompt — never bypass while driving.

## Cost estimate (3hr drive)

| Component | Cost |
|-----------|------|
| Anthropic API (Sonnet 4.5, ~30k tokens out) | ~$5-10 |
| ElevenLabs TTS (~30k chars) | ~$10 |
| Whisper-MLX, Tailscale, WebRTC | $0 |
| **Total** | **~$15-20** |

Swap `CLAUDE_MODEL=claude-haiku-4-5-20251001` in `.env` to halve LLM cost (faster, less depth).

## Stopping

Ctrl-C the `voice-loop` process. Tailscale funnel:

```bash
tailscale funnel --https=10000 off
```

## Troubleshooting

- **Mic permission denied** → must use HTTPS URL, not HTTP. Chrome on Android blocks `getUserMedia` over plain HTTP. Tailscale funnel gives you HTTPS for free.
- **Long pause on first reply** → Whisper model still loading. Wait 30sec, try again.
- **Voice cuts off mid-sentence** → SileroVAD `stop_secs` too aggressive. Bump to 0.6 in `voice_loop.py`.
- **Greek transcription poor** → Whisper turbo handles Greek decently; if it fails, swap to `mlx-community/whisper-large-v3` (slower, more accurate).
