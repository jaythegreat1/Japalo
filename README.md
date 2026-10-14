# Japalo

A Highrise bot with an AI brain. The brain goes through [OmniRoute](https://github.com/diegosouzapw/OmniRoute),
a free AI gateway: one OpenAI-style endpoint that routes to many AI providers and falls back to another
when one fails or hits its limit, so the bot keeps talking.

```
Highrise room  <->  Japalo bot (Python)  <->  OmniRoute :20128/v1  <->  OpenAI / Gemini / Groq / ...
```

## What it does

- **Talks:** say its name in chat (`Japalo what's up?`) and it answers with `@you`; whisper it and it whispers back.
- **Remembers each person:** keeps the last few messages per user, so follow-up questions make sense (`!reset` clears it).
- **Learns:** owners teach it facts with `!learn`; they are saved in `data/memory.json` and used in every answer.
- **Stays up:** retries with backoff (but not on permanent errors like 401/403), falls back through
  `OMNIROUTE_FALLBACK_MODELS`, tells the room when the AI is down instead of crashing, checks OmniRoute
  every 2 minutes and announces when it is back. Per-user cooldown stops spam; long answers are split into bubbles.

| Command | Who | |
| --- | --- | --- |
| `!help` `!ping` `!status` `!reset` `!facts` | everyone | `!status` shows model, answer count, failures, latency |
| `!model [name]` `!models` | owners | show or switch the OmniRoute model live |
| `!learn <fact>` `!forget <n>` | owners | teach or remove a fact |

## Setup

1. **Start OmniRoute** on the same machine as the bot. Use **Node 22.22.2+ or Node 24**: on an older Node,
   `npm install -g omniroute` silently installs the old 3.8.48, whose free providers have since been shut down.
   ```bash
   node -v                     # must be >= 22.22.2
   npm install -g omniroute    # npm 11: add --allow-scripts=omniroute,keytar,@parcel/watcher,@swc/core,esbuild
   omniroute --version         # expect 3.8.51 or newer
   omniroute                   # dashboard: http://localhost:20128
   ```
   **Connect at least one provider with your own free key** (Providers page): Groq, Google AI Studio (Gemini)
   or OpenRouter all have free keys. Do not rely on `auto` with zero keys: in OmniRoute 3.8.51 the only keyless
   provider `auto` uses is OpenCode Free, and OpenCode now blocks every app except its own, so `auto` fails
   until a provider is connected. Copy your OmniRoute key from **Endpoints** if you turned on required API keys.
2. **Install the bot** (Python 3.11 or 3.12; the Highrise SDK does not build on 3.13):
   ```bash
   python3.11 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in HIGHRISE_ROOM_ID, HIGHRISE_API_TOKEN, BOT_OWNERS
   ```
3. Optional: set `OMNIROUTE_FALLBACK_MODELS` in `.env` to models the bot should try, in order, when the main
   one fails.
4. **Check the brain** without joining Highrise: `python check_omniroute.py "hello"`
5. **Run:** `python run.py`

## Tests

Offline tests use a fake OmniRoute server:

```bash
pip install -r requirements-dev.txt
python -m pytest
```
