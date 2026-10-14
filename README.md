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

### Build new commands by describing them (staff)

Staff can describe a command in plain words and the AI builds it:

```
Japalo make a command where I hug someone and they blush
  -> the AI asks about anything unclear, suggests ideas, or whispers a draft:
     !hug @name: 1. you do Hug Yourself  2. wait 1s  3. they do Bashful  4. room sees "..."
Japalo call it hug, and add your first idea      (change anything in plain words)
Japalo test @amy     -> runs it for real; problems are reported
Japalo save          -> keeps it (only after a passing test); anyone can use !hug @name
```

Also `Japalo show` (current draft), `Japalo cancel`, `Japalo edit command !hug
<changes>`, `!customcommands` (list) and `!delcommand <name>` (staff).

Commands are **data, not code**: the AI can only combine fixed building blocks
(emotes for you / them / the bot, room messages, whispers, reactions, waits,
the bot walking over, random picks). The bot checks every draft against the
emote catalog and its limits (12 steps, 10s of waits, no reusing built-in or
existing names); when a draft fails a check, the AI is shown the exact errors
and fixes it itself (up to twice). Saved commands live in the database
(`custom_commands` table), so on Railway keep the `/app/data` volume.

### AI setup (Groq first, OmniRoute as fallback)

The AI tries its providers in order and moves to the next one when one fails
or is rate-limited:

1. **Groq** (when `GROQ_API_KEY` is set) — free key from
   [console.groq.com/keys](https://console.groq.com/keys). Default models
   `openai/gpt-oss-120b` then `openai/gpt-oss-20b` (Groq shut Llama 3.x off for
   free keys on 2026-08-16). Free limits are per model: 30 requests and 8K
   tokens a minute, 1K requests a day — roughly 4 AI answers a minute per
   model.
2. **OmniRoute** (when `OMNIROUTE_URL` is set, or when there's no Groq key) —
   [OmniRoute](https://github.com/diegosouzapw/OmniRoute) is a free AI gateway
   you run yourself (Node **22.22.2+**: `npm install -g omniroute`, then
   `omniroute`). Its free keyless DuckDuckGo models work as a fallback:
   `OMNIROUTE_MODEL=ddgw/gpt-5.4-mini`,
   `OMNIROUTE_FALLBACK_MODELS=ddgw/gpt-5.6-luna,ddgw/gpt-5-mini`. It's too big
   for Railway's free plan, so run it on a machine of your own if you want it.

| Variable | Default | What it does |
|---|---|---|
| `GROQ_API_KEY` | *(empty)* | Turns on Groq as the first provider |
| `GROQ_MODELS` | `openai/gpt-oss-120b,openai/gpt-oss-20b` | Groq models, in order |
| `GROQ_REASONING_EFFORT` | `low` | How long gpt-oss thinks before answering (fewer tokens = more answers per minute) |
| `GROQ_MIN_INTERVAL` | `2` | Seconds between Groq requests |
| `OMNIROUTE_URL` | *(off when Groq is set)* | OmniRoute fallback, e.g. `http://your-host:20128/v1` |
| `OMNIROUTE_API_KEY` | *(empty)* | OmniRoute key, if you turned on required API keys |
| `OMNIROUTE_MODEL` / `OMNIROUTE_FALLBACK_MODELS` | `auto` / *(empty)* | OmniRoute models, in order |
| `OMNIROUTE_MIN_INTERVAL` | `4` | Seconds between OmniRoute requests |
| `BOT_NAME` | `Japalo` | The word a message must start with |

A rate-limited model cools down for as long as the provider asks and the next
one answers right away; a model that fails permanently (bad key, model gone)
rests for 10 minutes. `Japalo status` shows the route order and anything
resting. If every provider is down the bot keeps running and replies that its
brain is taking a nap; everything else works as before.

## Run it 24/7 on Railway (free plan)

Railway's Free plan is $0 with $1 of usage credit a month (after a 30-day,
$5 trial). The bot runs as one small process (about 45-60 MB), which costs
roughly $0.50-0.80 a month in memory and CPU, so it should fit the credit;
check **Usage** in Railway after a few days. The repo's `Dockerfile` and
`railway.json` set everything up; Railway restarts the bot if it crashes.

1. Sign in at [railway.com](https://railway.com) with GitHub.
2. **New Project → Deploy from GitHub repo**, pick this repository, and in the
   service's **Settings → Source** choose the branch to deploy.
3. In the service's **Variables**, add `HIGHRISE_ROOM_ID`, `HIGHRISE_BOT_TOKEN`
   and `GROQ_API_KEY` (plus any optional variables above).
4. Keep points, warnings, favorites, settings and learned facts across
   redeploys: right-click the service → **Attach volume**, mount path
   `/app/data`. Without a volume they reset on every redeploy.
5. Deploy. The **Deploy Logs** show `Bot started in room owned by ...` once
   it's in the room.

`main.py` (keep-alive web server + restart loop) is still what Replit runs; on
Railway the Dockerfile runs the bot directly instead, because the keep-alive
server isn't needed there and would cost extra memory.

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
- `!emote <name>` — loop an emote by its `!emotelist` name, e.g. `!emote moonwalk`
  or `!emote lets go shopping` (case and punctuation don't matter; a unique part
  of a name works too, and an unclear one lists the matches); `stop` ends it
- `!surprise [rarity]` — choose and perform a random emote
- `!fav`, `!fav <slot>`, `!fav <slot> <number>` — list, play, or save favorites
- `stop` — stop your own emote loop
- `!punch @name` / `!slap @name` — you punch or slap, they play a random
  falling emote (Fall, Collapse, Faint Drop, Clumsy, Fail)
- `!explode @name` — they play Boo (you don't emote)
- `Japalo <anything>` — talk to the AI; see "Talk to Japalo (AI)" above
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
- `!emote @name <number or name>` — make another room user perform an emote. Staff can
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


