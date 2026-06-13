"""Top-level bot.py shim — Pipecat 0.0.103+ runner discovery.

`pipecat.runner.run.main()` looks for a `bot()` function in:
  1. sys.modules["__main__"]
  2. `import bot` from cwd
  3. any .py file in cwd

The voice-loop wrapper is `__main__`, so (1) fails. The canonical bot
lives at `src/pipecat_mcp_server/bot.py`, so (2) and (3) also fail unless
this shim exists at the project root.
"""

from pipecat_mcp_server.bot import bot

__all__ = ["bot"]
