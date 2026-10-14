# Japalo Highrise Bot

Japalo is a single-room Highrise bot with looping emotes, moderation,
minigames, tips, favorites, persistence, and an evidence-based emote catalog.

## Run & Operate

- Run `python main.py` to start the bot supervisor and keep-alive server.
- Run `python -m unittest discover -s tests -v` for the offline test suite.
- Run `python tools/emote_catalog/fetch_catalog.py` to refresh official
  candidates without logging into Highrise.
- Run `python tools/emote_catalog/catalog_audit.py` or staff can use
  `!catalog audit` for observed source/runtime/release counts.
- For unattended checks, run `tools/emote_catalog/reconcile_daemon.py` with a
  separate bot token and private verification room; it is deliberately gated
  and never uses the production room.
- Run `python tools/emote_catalog/verify_emotes.py` through the Highrise SDK
  launcher in a private/test room, then run
  `python tools/emote_catalog/merge_catalog.py`.
- Required secrets: `HIGHRISE_ROOM_ID`, `HIGHRISE_BOT_TOKEN`.

## Stack

- Python 3.11
- Official `highrise-bot-sdk==25.1.0`
- Flask keep-alive endpoint
- SQLite persistence through `aiosqlite`
- Requests for the public Highrise catalog API

## Where things live

- `main.py` — supervised bot entrypoint and restart backoff
- `highrise_bot/` — room behavior, commands, games, moderation, and storage
- `config/emotes.json` — only merged, verified emotes used by the bot
- `tools/emote_catalog/` — fetch, live-verify, and merge pipeline
- `tests/` — offline unit tests
- `data/bot.db` — generated local persistence file

## Architecture decisions

- Public catalog records are candidates, never runtime emotes, until Highrise
  accepts the ID through the live verifier.
- Item-detail lookups are a preservation fallback because the bulk emote
  filter can return zero rows.
- Purchase-locked items are tracked separately from invalid/unreleased IDs.
- Durations are never guessed; a candidate must be timed before merging.

## Product

- Players can browse, search, loop, randomize, and favorite exact emotes.
- Staff can moderate the room and run games.
- The bot persists settings, scores, warnings, tips, visits, and favorites.

## User preferences

- Keep Highrise names and IDs authoritative; do not fabricate missing entries.

## Gotchas

- Run catalog verification in a private or empty test room.
- `!emote` numbers are file-order positions and can shift after a merge.
- Auto-buy is disabled by default and must never be enabled casually because it
  spends the bot wallet.
- Production deployment uses an always-running VM target because Highrise is a
  persistent event-driven bot, not a request-scaled web application.

## Pointers

- See `tools/emote_catalog/README.md` for the full catalog workflow.
