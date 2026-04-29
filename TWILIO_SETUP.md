# Pythia → Twilio inbound-phone setup

PICASSO STEAL from Google for Developers (2026-04-27). Adds PSTN telephony so anyone can call Pythia. One-pager: `~/LOSC/data/picasso/one-pagers/2026-04-28-googledevs-gemini-live-telephony.md`.

> **Status 2026-04-29**: scope corrected. This is **NOT** a 30-minute config job. The original runbook treated `pipecat-mcp-server -t twilio` as a built-in mode — it isn't. Adding inbound phone requires authoring a separate bot module (`phone_bot.py`) against the upstream `pipecat.runner.run`. Realistic effort: 2-4 hours of authoring, not config.

---

## Architecture (target)

```
Caller's phone → PSTN → Twilio number → Twilio Media Streams (WSS)
    → https://ntemiss-macbook-pro-1.tailddb317.ts.net:10000  (NEW Tailscale funnel)
    → Mac:7861  (python -m pipecat.runner.run -t twilio  driving phone_bot.py)
    → Whisper-MLX → Claude Sonnet 4.5 → 11Labs/Kokoro
    → LOSC MCP (full ontology-aware tool surface)
```

**Coexists with**:
- Browser Pythia: `voice-loop` on `:7860`, funnel `:8443` (UNTOUCHED).

**Why two instances, not one**: voice-loop is browser-WebRTC only. Twilio Media Streams use WebSocket; the runner-based phone bot speaks that protocol natively. Different transports = different processes.

---

## Repo binaries (canonical, verified 2026-04-29)

| Binary | Module | Port | Transport | Status |
|---|---|---|---|---|
| `voice-loop` | `pipecat_mcp_server.voice_loop:main` | 7860 | WebRTC (browser) | 🟢 live (PID 2072 today) |
| `pipecat-mcp-server` | `pipecat_mcp_server.server:main` | 9090 | MCP tool-server | 🟢 (separate concern, not telephony) |
| `python -m pipecat.runner.run -t twilio --port 7861 phone_bot:bot` | `pipecat.runner.run:main` | 7861 | Twilio Media Streams (WSS) | ❌ phone_bot.py not yet authored |

`pipecat-mcp-server` is **NOT** polymorphic via `-t twilio`. It is the MCP tool-server entry point. Different package responsibility. See `~/.claude/projects/-Users-ntemis/memory/feedback_picasso_pipecat_distinction.md` for the canonical clarification.

---

## Tailscale Funnel state (verified 2026-04-29)

```
# Funnel on:
#     - https://ntemiss-macbook-pro-1.tailddb317.ts.net:8443   (→ 127.0.0.1:7860, browser Pythia)
```

Tailscale Funnel allows **only ports 443, 8443, 10000** for HTTPS. `:8443` taken by browser Pythia. Phone instance must claim **`:443` or `:10000`** externally — `:10000` recommended (`:443` collides with web HTTP convention).

The earlier-doc hostname `ntemiss-mbp.tailddb317.ts.net` is **stale** — actual is `ntemiss-macbook-pro-1.tailddb317.ts.net`.

---

## What's already in place

✅ `~/Projects/pipecat-mcp-server/.env` provisioned with:
- `TWILIO_ACCOUNT_SID` (34 chars, AC… prefix)
- `TWILIO_AUTH_TOKEN` (32 chars)
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `ELEVENLABS_*`, `KOKORO_VOICE_ID`

✅ `pipecat-ai` library installed in venv (incl. `pipecat/serializers/twilio.py` + `pipecat/runner/run.py`)

✅ Browser-mode `voice_loop.py` exists and is running — ~80% liftable as the basis for `phone_bot.py`

❌ `phone_bot.py` not yet authored
❌ New Tailscale Funnel `:10000` → `:7861` not added
❌ Twilio Console webhook not wired
❌ Greek-mobile dial test not performed

---

## What needs to happen (corrected scope)

### Phase 1 — author `phone_bot.py` (~2hr)

Create `~/Projects/pipecat-mcp-server/src/pipecat_mcp_server/phone_bot.py` with:

```python
async def bot(runner_args):
    # runner_args is a WebSocketRunnerArguments when -t twilio
    transport = setup_telephony_transport(runner_args)
    # Wire: Twilio WSS in → Whisper-MLX STT → Claude Sonnet 4.5 (LOSC MCP)
    # → 11Labs/Kokoro TTS → Twilio WSS out
    pipeline = build_pythia_pipeline(transport)  # crib from voice_loop.build_pipeline()
    await run_pipeline(pipeline)
```

Lift the system prompt + LOSC MCP tool registration from `voice_loop.py`. Add a phone-specific persona note ("Caller may be a stranger; verify identity before any outbound action").

Add to `pyproject.toml [project.scripts]`:
```toml
phone-bot = "pipecat_mcp_server.phone_bot:run_via_runner"
```

Where `run_via_runner` is a small wrapper that calls `pipecat.runner.run.main` with `phone_bot:bot` discovered.

### Phase 2 — start daemon + funnel (~5 min once Phase 1 ships)

```bash
cd ~/Projects/pipecat-mcp-server
nohup .venv/bin/phone-bot -t twilio --port 7861 > /tmp/pythia-phone.log 2>&1 &

tailscale funnel --bg --https=10000 7861
tailscale funnel status   # verify 10000 → 7861 mapping
```

### Phase 3 — Twilio Console webhook (~5 min, Ntemis only — auth wall)

Console → Phone Numbers → your number → Voice config → "A CALL COMES IN":
- Webhook: `https://ntemiss-macbook-pro-1.tailddb317.ts.net:10000/twilio/voice` (exact path TBD from `pipecat.runner.run` startup logs)
- HTTP method: POST

### Phase 4 — Greek-mobile dial test (~10 min)

- Dial number from your own Greek mobile
- Verify Pythia answers in Greek (Whisper-MLX language detection)
- Test 3 LOSC tool calls: `losc_thought`, `losc_search`, `losc_calendar_add`
- Verify call hangs up cleanly + audit log records the session

### Phase 5 — extend `/talk` skill

Add `/talk phone` mode that does Phase 2 (daemon + funnel) + a status sub-command. Skip Phase 3-4 in skill (those are auth-wall + manual).

---

## Cost expectations (unchanged)

- **Personal use**: <€5/mo
- **L+A intake pilot**: €1/mo number + €0.013/min ≈ €15-30/mo for moderate inbound volume
- **LLM cost**: same as `/talk` driving sessions

---

## Risk/blast-radius notes

- Twilio is a separate vendor. Easy to abandon.
- **Don't share the number with Apollo's intake list until 5+ successful test calls**, including multilingual handoff. New SLA created on first share.
- `pipecat.runner.run` upstream may change between releases — log this dependency, watch upstream releases.
- `phone_bot.py` is new code → needs `tests/test_phone_bot.py` per LOSC's test automation rules in `~/CLAUDE.md`.

---

## What I will NOT do without explicit go

- Won't `/ping-apollo` about the L+A intake variant until the personal-use number works first (Auth Bootstrap rule + don't surprise Apollo with infrastructure he hasn't agreed to).
- Won't swap Pythia's brain to Gemini 3.1 Flash Live. Sonnet + prompt cache + LOSC MCP is the differentiator.
- Won't migrate hosting to GCP.

---

## Lifecycle in the PICASSO queue

- 2026-04-28: scored STEAL (one-pager written)
- 2026-04-29: scope corrected — authoring task, not config. Status remains STEAL with `progress_note` reflecting Phase 1-5 above. `foundation_complete: true` for the Twilio creds + library install; `last_mile_pending` updated to "author `phone_bot.py` then complete Phases 2-4".
