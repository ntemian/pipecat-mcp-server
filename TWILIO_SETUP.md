# Pythia → Twilio inbound-phone setup

PICASSO STEAL from Google for Developers (2026-04-27). Adds PSTN telephony so anyone can call Pythia. One-pager: `~/LOSC/data/picasso/one-pagers/2026-04-28-googledevs-gemini-live-telephony.md`.

## Architecture

```
Caller's phone → PSTN → Twilio number → Twilio Media Streams (WSS)
    → https://ntemiss-mbp.tailddb317.ts.net:10000  (existing Tailscale funnel)
    → Mac:7860  (pipecat-mcp-server -t twilio)
    → Whisper-MLX → Claude Sonnet 4.5 → 11Labs (or Kokoro for cost)
    → LOSC MCP (full ontology-aware tool surface)
```

No ngrok. No GCP. Everything stays on the Mac.

## Setup — the auth-wall click-path (Ntemis only)

### 1. Twilio account
- https://www.twilio.com/try-twilio → sign up
- Free trial: $15.50 credit (covers ~20 hours of inbound calling for testing)
- Verify your mobile during signup (so trial calls work)

### 2. Buy a number

For **L+A client intake** (production): buy a Greek number.
- Console → Phone Numbers → Buy a number → Country: Greece
- Greek mobile (+30 69x): ~€1.00/mo + €0.013/min inbound
- Greek geographic (+30 21x): ~€1.00/mo + €0.013/min inbound — **better for legal-firm credibility**

For **first test only**: a free US trial number works fine.

### 3. Grab credentials
- Console home → Account Info panel → copy:
  - `Account SID` (starts `AC...`)
  - `Auth Token` (click the eye to reveal)

### 4. Hand them back to me

Paste the SID + Auth Token here in chat (or save to `~/Projects/pipecat-mcp-server/.env` yourself with these two lines):

```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
```

## What I do after you've given me the credentials

1. Append `TWILIO_*` to `.env`.
2. Verify Tailscale funnel carries WebSockets to `:10000` (Twilio Media Streams use `wss://`).
3. Start a *second* pipecat instance on a new port (e.g. 7861) for phone-only mode, leaving the browser/driving instance on 7860 untouched:
   ```bash
   cd ~/Projects/pipecat-mcp-server
   nohup .venv/bin/pipecat-mcp-server \
     -t twilio \
     -x ntemiss-mbp.tailddb317.ts.net:10000 \
     --port 7861 > /tmp/pythia-phone.log 2>&1 &
   ```
   (Adjust if upstream uses a different flag; will verify on first run.)
4. Add a second Tailscale funnel on a different external port pointing at 7861.
5. Twilio Console → your number → Voice config → "A CALL COMES IN" → Webhook → `https://ntemiss-mbp.tailddb317.ts.net:<funnel-port>/twilio/voice` (exact path TBD from pipecat docs).
6. Test call from your own mobile.
7. If the Greek line works: extend `/talk` slash command with a `/talk phone` mode that starts/stops the inbound instance.

## Cost expectations

- **Personal use** (Ntemis dialing in himself when phone-browser fails): negligible, <€5/mo.
- **L+A intake pilot** (real clients calling): €1/mo number + €0.013/min ≈ €15-30/mo for moderate inbound volume.
- **LLM cost** unchanged (still Sonnet 4.5 + LOSC MCP) — same as `/talk` driving sessions.

## Risk/blast-radius notes

- Twilio is a separate vendor account. No coupling to LOSC ontology. Easy to abandon if not useful.
- If you give a Greek number to L+A clients before the system is reliable, you create a new SLA. **Test exhaustively with your own mobile first.** Don't share the number with Apollo's intake list until 5+ successful test calls including multilingual handoff.
- Pipecat's `-t twilio` mode may not be perfectly stable across upgrades — log this dependency and watch upstream releases.

## What I will NOT do without explicit go

- Won't `/ping-apollo` about the L+A intake variant until the personal-use number works first (Auth Bootstrap rule + don't surprise Apollo with infrastructure he hasn't agreed to).
- Won't swap Pythia's brain to Gemini 3.1 Flash Live. Sonnet + prompt cache + LOSC MCP is the differentiator.
- Won't migrate hosting to GCP.
