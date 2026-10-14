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
- **Stays up:** retries with backoff, tells the room when the AI is down instead of crashing, checks OmniRoute
  every 2 minutes and announces when it is back. Per-user cooldown stops spam; long answers are split into bubbles.

| Command | Who | |
| --- | --- | --- |
| `!help` `!ping` `!status` `!reset` `!facts` | everyone | `!status` shows model, answer count, failures, latency |
| `!model [name]` `!models` | owners | show or switch the OmniRoute model live |
| `!learn <fact>` `!forget <n>` | owners | teach or remove a fact |

## Setup

1. **Start OmniRoute** (Node 22.22.2+ or 24+), on the same machine as the bot:
   ```bash
   npm install -g omniroute
   omniroute            # dashboard: http://localhost:20128
   ```
   In the dashboard, connect at least one provider (Providers page). A free API key from Groq, Google AI Studio
   (Gemini) or OpenRouter works. Copy your OmniRoute key from **Endpoints** if you turned on required API keys.
2. **Install the bot** (Python 3.11 or 3.12; the Highrise SDK does not build on 3.13):
   ```bash
   python3.11 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in HIGHRISE_ROOM_ID, HIGHRISE_API_TOKEN, BOT_OWNERS
   ```
3. **Check the brain** without joining Highrise: `python check_omniroute.py "hello"`
4. **Run:** `python run.py`

## Tests

Offline tests use a fake OmniRoute server:

```bash
pip install -r requirements-dev.txt
python -m pytest
```
