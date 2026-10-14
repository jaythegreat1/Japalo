# Japalo — Highrise Room Bot

A Python bot for a single Highrise room, with a personality: numbered,
precisely-timed looping emotes, room moderation, five minigames, and a big
pool of blended-tone (witty / hype / chill) responses instead of one flat
canned line per event. Built on the official
[Highrise Python Bot SDK](https://pypi.org/project/highrise-bot-sdk/)
(`highrise-bot-sdk==25.1.0`).

This build includes the moderation, tip economy, emote UX, engagement, and
persistence work requested for the room. It uses only the official Highrise
Python SDK methods that exist in `25.1.0`; where Highrise does not expose a
native operation, the command says so instead of pretending.

## 1. Set up secrets

In your Replit project, open the **Secrets** tab (padlock icon in the left
sidebar) and add:

| Key | Value |
|---|---|
| `HIGHRISE_ROOM_ID` | Your room's ID (Share this room → copy the ID) |
| `HIGHRISE_BOT_TOKEN` | Your bot's API token (Highrise → Account Settings → create a bot) |
| `ALERT_WEBHOOK_URL` | *Optional.* A Discord or Slack incoming-webhook URL. If set, you get pinged when the bot fails to stay up. |

Never put these in a committed file. `.env.example` is a template only —
it has no real values in it.

## 2. Install dependencies

Replit installs from `pyproject.toml` / `requirements.txt` automatically the
first time you hit **Run**. If it doesn't, run in the Shell:

```
pip install -r requirements.txt
```

## 3. Run it

Hit the green **Run** button. That executes `main.py`, which:

1. Starts a tiny keep-alive web server (`keep_alive.py`) on port 8080.
2. Launches the Highrise bot as a subprocess and restarts it automatically
   with backoff (5s, 15s, 30s, 60s) if the SDK process ever exits. The SDK
   itself already reconnects on server-closed websockets — this is a second
   layer of protection for the rarer case where the whole process exits.

## 4. Keep it online 24/7 on a free Repl

A free Repl goes to sleep without inbound traffic. To stop that:

1. Click **Run** once so the Repl is live and note the webview URL shown at
   the top of the preview pane (looks like `https://<repl-name>.<you>.repl.co`).
2. Create a free account at [UptimeRobot](https://uptimerobot.com).
3. Add a new **HTTP(s)** monitor pointed at that URL, interval **5 minutes**.

UptimeRobot's pings hit `keep_alive.py`'s `/` route, which keeps the Repl
awake. This only keeps the *process* alive — it's independent of the
Highrise bot's own websocket reconnect logic, which is already handled.

If you're instead on a paid Reserved-VM or Autoscale Replit deployment, you
don't need step 4 — deployments stay on without an uptime monitor.

## Talk to Japalo (AI)

Any chat message that **starts with "Japalo"** goes to the AI; everything
else in the room is left alone. Whispers to the bot go to the AI too, and
are answered privately.

- `Japalo <anything>` — chat with the AI. It can also act in the room:
  `Japalo come dance with me` makes the bot and you dance, `Japalo wave at
  me and come over here` sends a wave and walks over.
- `Japalo emote 65`, `Japalo i want to do the emote number 65`,
  `Japalo emote moonwalk` — loop that emote (same numbers as `!emotelist`;
  `stop` ends it).
- `Japalo follow me` — the bot walks after you until `Japalo stop` (or plain
  `stop`), or until you leave the room.
- `Japalo come here`, `Japalo send heart to @name`.
- `Japalo status / reset / facts`; staff: `Japalo learn <fact>`,
  `Japalo forget <n>`, `Japalo model <name>`, `Japalo follow @name`,
  `Japalo emote 65 on @name`.

The common requests above are understood instantly without the AI. Anything
else goes to the AI, which answers with a small JSON plan of actions; every
planned action goes through the same checks as the typed commands
(emoting others needs staff or 100g VIP, moving to or following others
needs staff). `!config set ai off` turns off AI chat but keeps the typed
actions. Code: `highrise_bot/ai/` and `highrise_bot/commands/ai_commands.py`.

### AI setup (OmniRoute)

The AI's brain is [OmniRoute](https://github.com/diegosouzapw/OmniRoute), a
free AI gateway with one OpenAI-style endpoint for many providers. Run it on
the same machine as the bot (Node **22.22.2+** or 24; on older Node, npm
silently installs an outdated 3.8.48 whose free providers are gone):

```
npm install -g omniroute
omniroute          # dashboard + API on http://localhost:20128
```

Optional secrets (all have defaults):

| Key | Default | What it does |
|---|---|---|
| `OMNIROUTE_URL` | `http://localhost:20128/v1` | Where OmniRoute listens |
| `OMNIROUTE_API_KEY` | *(empty)* | OmniRoute key, if you turned on required API keys |
| `OMNIROUTE_MODEL` | `auto` | Main model |
| `OMNIROUTE_FALLBACK_MODELS` | *(empty)* | Models tried in order when the main one fails, e.g. `ddgw/gpt-5.4-mini,ddgw/gpt-5.6-luna,ddgw/gpt-5-mini` for free keyless DuckDuckGo |
| `OMNIROUTE_MIN_INTERVAL` | `4` | Seconds between AI requests (free providers rate-limit bursts) |
| `OMNIROUTE_RATE_LIMIT_WAIT` | `15` | Seconds to wait after a rate limit before retrying |
| `BOT_NAME` | `Japalo` | The word a message must start with |

Zero-key `auto` cannot answer today (its only keyless target, OpenCode Free,
blocks third-party apps), so set fallback models or connect a provider with
your own free key (Groq, Google AI Studio, OpenRouter) in the OmniRoute
dashboard. If OmniRoute is down, the bot keeps running and replies that its
brain is taking a nap; everything else works as before.

## Persistence, settings, and alerts (Phase 0)

**Data survives restarts now.** Warnings, minigame scores, room settings,
and a username cache all live in `data/bot.db`, along with warning/moderation
audit events, score events, joins/XP, tip totals, and personal emote
favorites. It is a single local SQLite file and is created automatically on
first run.

**`!config`** (room dev only) — view or change tunable settings without
touching code:

```
!config
!config set warning_mute_threshold 5
!config set enabled_games trivia,math,guessnumber
```

| Setting | Default | What it does |
|---|---|---|
| `warning_mute_threshold` | `3` | Warnings before an auto-mute fires |
| `auto_mute_seconds` | `300` | How long that auto-mute lasts |
| `spam_window_seconds` | `6.0` | Spam detection window |
| `spam_message_threshold` | `5` | Messages inside that window to count as spam |
| `command_cooldown_seconds` | `1.0` | Minimum time between commands per user |
| `raid_join_threshold` | `8` | Joins inside the raid window that trigger protection |
| `raid_window_seconds` | `30.0` | Raid join detection window |
| `raid_kick_enabled` | `true` | Kick the join that trips basic raid protection |
| `game_reward_gold` | `0` | Optional gold-bar reward per minigame win |
| `game_reward_gold_cap` | `100` | Hard cap on an automatic minigame reward |
| `auto_room_boost` | `false` | Reinvest wallet gold in one room boost after tips |
| `auto_voice_time` | `false` | Reinvest wallet gold in voice time after tips |
| `auto_spend_min_gold` | `100` | Minimum wallet gold before auto-spending |
| `enabled_games` | all five | Comma list of which minigames `!games` will start |
| `personality` | `on` | `on` = Japalo's full voice everywhere (joins, tips, warnings, wins, ...). `off` = plain, purely-informational text, same tone as before Japalo had a personality. |

Changes apply immediately and persist across restarts.

## Personality (Japalo's voice)

Japalo has a name and an opinion now. Instead of one fixed sentence per
event, most player-facing chat lines (joins, leaves, milestone visits, tip
thanks, VIP unlocks, warnings and their escalation, mod actions, game wins
and timeouts, `!help`'s intro, `!config` confirmations, and more) are drawn
at random from a large pool that deliberately blends dry/witty, hype/gamer,
and warm/chill tones — see `highrise_bot/personality.py`.

This is additive, never load-bearing: every wrapped message also has a
plain fallback with the exact same information (usernames, durations,
point totals, etc.), used automatically whenever a room dev sets
`!config set personality off`. Usage strings, permission errors, and other
strictly-functional whispers are deliberately left plain either way, so
"no, you can't do that" is never buried in a joke.

To add more lines to any pool, just add a string to the matching tuple in
`personality.py` — no other code changes needed, since every call site
already picks randomly from whatever is in the pool.

**Logging.** Every meaningful event (bot start, moderation actions,
auto-mutes, config changes, errors) goes through Python's `logging`
module with timestamps instead of bare `print()` — readable in the
Replit console, and easy to search when something goes wrong.

**Outage alert.** If the bot process fails to stay up for at least 2
minutes across `ALERT_AFTER_CONSECUTIVE_FAILURES` (4) consecutive
restarts, `main.py` posts one alert to `ALERT_WEBHOOK_URL` (a Discord or
Slack incoming webhook both work — same JSON shape) and keeps retrying at
the longest backoff. If you don't set that secret, it just logs the same
warning locally instead of failing silently. Note this is deliberately a
**webhook**, not a bot whisper: if the bot can't reconnect, it isn't
connected to whisper anyone, so only something outside the bot's own
connection can reliably alert you.

## Minigames (Phase 3)

Only one game runs room-wide at a time; starting a new one while another is
active tells you to finish it, wait it out, or ask staff for `!endgame`.

| Command | Game | How to answer | Timeout |
|---|---|---|---|
| `!trivia` | Trivia | `!answer A`/`B`/`C`/`D` | 30s |
| `!scramble` | Word Scramble | `!answer <word>` | 45s |
| `!math` | Math Blitz | `!answer <number>` | 20s |
| `!riddle` | Emoji Riddle | `!answer <text>` | 45s |
| `!guessnumber` | Guess the Number | plain number typed in chat | 60s (12 guesses) |

`!games` lists them all in-room. `!score` shows your own point total,
`!leaderboard [daily|weekly|all]` shows the top 5 for that period. Trivia is
shuffled from a larger bank with category and difficulty metadata. Wins add XP,
joins add five XP, and `!profile` reports level (`1 + XP // 100`) plus room
activity. Milestone visits are announced at 10, 25, 50, and 100.

## Commands

**Everyone:**
- `!emotelist [common|uncommon|rare|epic]` — whispered, optionally filtered list
- `!findemote <name or ID fragment>` — search the exact configured catalog
- `<number>` — loop that emote on yourself until you type `stop` (or, if a
  Guess the Number round is active, submit that number as a guess instead)
- `!emote <number>` — same as typing the number directly
- `!surprise [rarity]` — choose and perform a random emote
- `!fav`, `!fav <slot>`, `!fav <slot> <number>` — list, play, or save favorites
- `stop` — stop your own emote loop
- `!games` — list the minigames and how to answer each
- `!answer <text>` — answer whichever game is currently active
- `!score` / `!leaderboard [daily|weekly|all]`
- `!profile` — XP, level, visits, points, tips, and VIP status
- `!tipleaderboard` / `!tips`
- `!help` — categorized command overview; `!help <category>` (emotes, games,
  economy, mod, admin) for the full detail on that group — staff-only
  categories only show up for staff

**Room dev or moderators only:**
- `!warn @name <reason>` / `!warnings [@name]`
- `!kick @name`
- `!ban @name`
- `!unban @name`
- `!mute @name <seconds>` — duration is **required** (see note below)
- `!endgame` — force-clear a stuck or unwanted minigame round
- `!freeze @name` / `!unfreeze @name` — soft-freeze approximation using
  continuous teleport-back
- `!testemote <number>` — perform one emote without starting a loop

**Room dev (owner) only:**
- `!setmod @name` — grant moderator
- `!delmod @name` — revoke moderator
- `!config` / `!config set <key> <value>` — view/change tunable settings (see Phase 0 section above)

**Staff and VIP:**
- `!emote @name <number>` — make another room user perform an emote. Staff can
  use it immediately; a user becomes VIP after tipping the bot 100g.

### Why `!mute` needs a duration, and there's no `!unmute`

The live Highrise SDK only accepts `kick`, `ban`, `unban`, `mute` as
moderation actions — there is no `unmute` action to call. Rather than offer
a command that silently fails, the bot requires every mute to include a
duration so it always expires on its own. `!freeze` is a documented
approximation, not a real server-side freeze: `on_user_move` teleports a
frozen user back to their captured floor position. It cannot guarantee
immobilization and does not work for anchor-only positions.

## Automatic moderation (Phase 2)

Two things run automatically for every non-staff message, before the bot
even looks at what command it is:

- **Spam detection** — 5+ messages within 6 seconds trips a warning.
- **Word filter** — `config/moderation_words.json` is a whole-word,
  case-insensitive blocklist. It ships with a small, generic example set
  (`idiot`, `stupid`, `shut up`, `dumbass`, `loser`, `moron`) — edit that
  file to match your room's actual rules. Deliberately excludes anything
  self-harm/crisis-related: an automated "stop spamming" warning is the
  wrong response to someone in genuine distress, and this bot has no way
  to handle that appropriately.

Both share one persisted warning counter per user and call the same `!warn`
implementation. The 3rd warning auto-mutes for the configured duration; the
5th warning kicks and resets the active counter. Manual staff actions are
stored in an audit table, and the SDK's `on_moderate` hook records native UI
actions too. Staff are exempt from automatic filters.

## Tips, VIP, and wallet reinvestment

When the bot receives a gold tip, it thanks the tipper in public and persists
their total. `!tipleaderboard` shows the top supporters. At 100g total, the
tipper is treated as VIP and can use `!emote @name <number>`.

Gold rewards are off by default. Set `game_reward_gold` to a value from 1 to
`game_reward_gold_cap` to tip a winner with the nearest supported Highrise
gold bar. Wallet reinvestment is also opt-in: enabling `auto_room_boost`
and/or `auto_voice_time` calls the real
`buy_room_boost("bot_wallet_only", 1)` and
`buy_voice_time("bot_wallet_only")` methods after the wallet reaches
`auto_spend_min_gold`. A one-minute guard prevents a tip burst from making
repeated purchases.

## Emote catalog

`config/emotes.json` currently has **265 entries**. The catalog is intentionally
not padded to a target count: names and rarity come from the official Highrise
catalog, and entries are added only after the bot accepts the exact ID in a
live verification run and a real loop duration is recorded. Legendary and
unreleased items stay out.

Run `python tools/emote_catalog/fetch_catalog.py` to refresh the candidate
inventory. If Highrise reports more Rare or Epic emotes than the current 128,
the candidates file will show that increase. Then run the verifier in a private
or empty test room and merge everything marked `verified`. As of this build,
`verify_emotes.py` marks a Highrise-confirmed id `verified` right away with a
placeholder loop duration by default (see `tools/emote_catalog/README.md`),
so growing the catalog no longer requires timing every animation by hand —
timing can be refined per-entry later. `reconcile_daemon.py` can also be set
to run that merge step itself each cycle with `EMOTE_RECONCILE_AUTO_MERGE=true`.

## Project layout

```
highrise_bot/
  bot.py                 Core: SDK event hooks + command-table dispatch (see below)
  constants.py           Shared paths, game metadata, the !config schema
  personality.py         Japalo's voice: every response pool, blended-tone
  messages.py            Join/leave wrappers around personality.py + plain fallback
  commands/
    emote_commands.py       !emotelist/!emote/!surprise/!fav/!testemote/capture/catalog
    game_commands.py        The 5 minigames, scoring, leaderboards, rewards
    economy_commands.py     Tips, VIP, !profile, wallet reinvestment
    moderation_commands.py  Warnings + escalation, kick/ban/mute, freeze, mod grants
    admin_commands.py       !config get/set, cooldown gate
    help_commands.py        !help
  emotes.py              Validated emote catalog loader
  emote_loop.py          Per-user precise-timing loop manager
  trivia.py              Trivia question bank + round state
  moderation_filters.py  Spam detection + configurable word filter
  storage.py             SQLite persistence (warnings, scores, settings, usernames)
  logging_config.py      Structured logging setup
  games/
    scramble.py          Word Scramble
    math_blitz.py         Math Blitz
    guess_number.py        Guess the Number (higher/lower)
    emoji_riddle.py         Emoji Riddle
config/
  emotes.json           The verified emote catalog
  emotes.schema.json
  moderation_words.json  Customizable blocked-phrase list
data/
  bot.db                 Created automatically on first run (gitignored)
keep_alive.py     Flask keep-alive server for free-tier Replit hosting
main.py           Entry point: keep-alive, process supervision, outage alert
tests/            Unit tests (no live Highrise connection needed)
.agents/memory/   Working notes on emote-ID verification, reconnect behavior,
                  and each session's fixes/design decisions
```

`bot.py` used to be one ~1200-line file holding every command handler
inline behind a 50-branch if/elif chain. It's now a thin core: the
`HighriseRoomBot` class mixes in the six `commands/` modules above, and
`on_chat` routes through small lookup tables (`COMMAND_TABLE`,
`GAME_START_COMMANDS`, `ACTION_COMMANDS`, `MOD_CHANGE_COMMANDS`) instead of
a long chain — adding a command means adding one table row, and finding a
handler means opening the one file that owns that concern.

## Running the tests

```
pip install highrise-bot-sdk==25.1.0 flask aiosqlite
python3 -m unittest discover -s tests -v
```

All 44 unit tests pass as of this delivery, including persistence coverage for
warning audits, tips, favorites, XP, and profile data. The bot modules also
compile cleanly with Python 3.10+; live Highrise behavior still requires
running the bot in a room with valid secrets.


