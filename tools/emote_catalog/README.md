# Emote catalog pipeline

Replaces the old 75-entry, hand-maintained `config/emotes.json` build
process with a repeatable pipeline you can re-run whenever Highrise adds
new emotes. Four stages, each a separate script so you can stop and
resume anywhere.

## Why four stages, not one script

There is no single API call that gives you (verified animation id +
correct rarity + real loop duration) at once:

- The public catalog (`webapi.highrise.game`) gives you name + rarity, and
  a candidate id - but that id is **not guaranteed** to be the animation
  id `send_emote()` actually needs.
- The only way to confirm an id really works is to try it against a live
  bot connection and see whether Highrise accepts it.
- The API has no "animation finished" event, so loop duration can't be
  measured automatically. It can be timed by a person watching one loop or
  cross-checked against a current public Highrise bot mapping.

So: discover candidates cheaply (Stage 1), verify + time them against a
real bot (Stage 2, you run this), merge the trusted results (Stage 3),
then keep catching new ones organically as they get used in your room
going forward (Stage 4, already wired into the bot).

## Stage 1 - `fetch_catalog.py`

No bot login needed. Hits the public REST endpoint, pages through every
`category=emote` item, preserves Highrise's exact rarity values
(`common` / `none_` / `uncommon` / `rare` / `epic`), and records legendary
and non-playable source records as excluded audit states rather than treating
them as runtime candidates.
Writes `data/candidates.json` - nothing here is trusted yet, nothing here
touches `config/emotes.json`.

```
pip install requests
python fetch_catalog.py
```

**If this comes back with zero candidates:** Highrise's own API-update docs
list `emote` as a valid `category` value, so an empty result there points
at the server-side filter itself misbehaving, not a wrong parameter on our
end. The script already falls back automatically to fetching everything
unfiltered and picking out emotes by inspecting each item's own category
field. If *that* also finds nothing - confirmed to actually happen: a real
run against 59,207 total catalog items found zero labeled `category="emote"`
anywhere - it falls back once more: it scans that same unfiltered dump for
items whose own `item_id` starts with a namespace already proven real in
your verified catalog (`emoji-`, `dance-`, `emote-`, `idle-`, matching either
a `-` or `_` separator, since Highrise isn't consistent about that either).
This never invents or guesses an id - it only recognizes ids Highrise's API
already returned in that response, using namespaces from ids you've already
confirmed work; every result still goes through Stage 2's live `send_emote`
probe before it's trusted. Only if even that finds nothing does it print the
live category distribution and leave the existing candidates file untouched -
silently replacing a known catalog with an empty result is unsafe. To query
the configured IDs through the slower item-detail preservation path as well,
set `HIGHRISE_CATALOG_PRESERVE_KNOWN_ON_EMPTY=true`. For a raw sample, run:

```
python fetch_catalog.py --diagnose
```

This dumps the raw shape of a few unfiltered items with no interpretation
- share that output so the field-matching logic can be pointed at whatever
the API is actually calling the category now.

## Stage 2 - `verify_emotes.py` (you run this one)

A separate, standalone bot process - **not** the production
`HighriseRoomBot`. Run it with your own token, ideally in a **private or
empty test room**: it will visibly perform every pending candidate one at
a time, and Highrise's own SDK tells you (via a raised error) whether the
id is real. Explicit invalid-ID responses become `id_invalid`; ambiguous
failures become `needs_review` and are never pruned automatically.

By default, an id Highrise accepts is immediately marked `verified` with a
placeholder `duration_seconds` (`EMOTE_VERIFY_DEFAULT_DURATION`, 4.0s
unless you change it) - the id being real is what actually matters for the
emote to work; the duration only controls how tightly `emote_loop.py`
times the repeat, and can be refined later. Set
`EMOTE_VERIFY_MEASURE_DURATION=true` if you'd rather watch and press Enter
per emote for a precisely-timed loop from the start, or
`EMOTE_VERIFY_REQUIRE_MEASURED_DURATION=true` to go back to the old, strict
behavior where an untimed id is never merged. A current public Highrise bot
mapping can also supply a cross-checked real duration after the live ID
check succeeds.

```

## Audit report

Run:

```
python tools/emote_catalog/catalog_audit.py
```

The report separates source verification, live runtime acceptance, release
state, purchase locks, invalid IDs, and needs-review records. It reports
observed numbers only; it never targets a Rare/Epic count. Staff can also run
`!catalog audit` in the room for a compact summary.
export HIGHRISE_ROOM_ID=...          # private/test room recommended
export HIGHRISE_BOT_TOKEN=...
export EMOTE_VERIFY_LIMIT=40                # optional, default 40
export EMOTE_VERIFY_MEASURE_DURATION=true   # optional, default false
export EMOTE_VERIFY_EXISTING=true           # also re-check current emotes
export EMOTE_VERIFY_PRUNE_INVALID=true      # remove explicit Highrise rejects
python -m highrise tools.emote_catalog.verify_emotes:EmoteVerifierBot "$HIGHRISE_ROOM_ID" "$HIGHRISE_BOT_TOKEN"
```

Progress saves after every single item, so Ctrl+C and re-run anytime -
already-processed candidates are skipped automatically.

When `EMOTE_VERIFY_EXISTING=true`, the verifier probes both newly discovered
official candidates and the current runtime catalog. It writes an audit file
to `data/emote_runtime_status.json`. With pruning enabled, only an explicit
invalid-ID rejection is removed from `config/emotes.json`; a purchase or
ownership lock is retained and reported separately because it is a real item,
not proof that the ID is invalid.

For the repeatable read-only refresh step, use:

```
python tools/emote_catalog/refresh_catalog.py
```

Run that command whenever Highrise publishes new emotes, then run the live
probe in a private/test room. The production room bot never silently fires
hundreds of new animations or spends its wallet.

For unattended periodic reconciliation, use a separate Highrise bot/token and
a dedicated private verification room:

```
export EMOTE_RECONCILE_ENABLED=true
export EMOTE_RECONCILE_CONFIRM=DEDICATED_TEST_ROOM
export EMOTE_RECONCILE_ROOM_ID=...
export EMOTE_RECONCILE_BOT_TOKEN=...
export EMOTE_RECONCILE_INTERVAL_SECONDS=86400
python tools/emote_catalog/reconcile_daemon.py
```

Every cycle the daemon refreshes source data, then probes the real SDK
interface against both the fresh candidates and the *entire existing runtime
catalog* - so an id Highrise quietly stopped accepting gets caught, not just
newly discovered ones. It writes the audit and removes only explicit
invalid-ID results from `config/emotes.json`.

It refuses to use the production room and never auto-buys. By default it
still never merges anything new into `config/emotes.json` (add
`EMOTE_RECONCILE_AUTO_MERGE=true` below to change that) - a newly accepted
id otherwise sits in the audit as `verified`/`id_confirmed`, cycle after
cycle, until a human runs Stage 3 (`merge_catalog.py`) by hand.

```
export EMOTE_RECONCILE_AUTO_MERGE=true
# optional: only auto-merge ids someone actually timed by eye, instead of
# accepting the placeholder duration verify_emotes.py assigns by default
export EMOTE_RECONCILE_REQUIRE_MEASURED_DURATION=false
```

With `EMOTE_RECONCILE_AUTO_MERGE=true`, a clean probe cycle (refresh
succeeded, live probe exited 0) is immediately followed by
`merge_catalog.py` run against that cycle's own candidates file, so newly
confirmed ids land in `config/emotes.json` - with the catalog's usual name
sync and dead-entry removal - without anyone touching a keyboard. A failed
probe is never followed by a merge. Every new entry gets a safe placeholder
`duration_seconds` unless you've turned on
`EMOTE_RECONCILE_REQUIRE_MEASURED_DURATION`; re-run `verify_emotes.py`
with `EMOTE_VERIFY_MEASURE_DURATION=true` whenever you want to replace a
placeholder with a real, eyeballed timing for a specific emote.

## Stage 3 - `merge_catalog.py`

Merges everything marked `"status": "verified"` (live-accepted id + a
cross-checked duration)
into `config/emotes.json`, skipping duplicates. Also applies the removal
of "Hero Entrance" (`emote-hero`) and "Headball" (`emote-headball`),
reported broken on 2026-09-23. Re-validates the result through
`highrise_bot.emotes.load_catalog()` so a bad merge is caught here, not at
bot startup.

```
python merge_catalog.py --dry-run   # see the report, write nothing
python merge_catalog.py             # actually write config/emotes.json
```

**Heads-up:** `!emote`/`!emotelist`/`!fav` numbers are just each entry's
position in the file, not a stored id. Removing entries shifts every later
number down - anyone's saved `!fav` slot above the removed positions will
point at a different emote after this runs. Worth a heads-up to your room
before you push an update that changes numbering.

## Stage 4 - organic capture, already in `highrise_bot/bot.py`

New staff commands:

- `!emotecapture on|off|status` - while on, any emote actually performed
  in the room whose id isn't in the current catalog gets logged (not
  guessed - it's a real id someone just triggered).
- `!capturedemotes` - lists what's been captured so far.

This is the ongoing version of Stages 1-3: instead of a big periodic
re-scrape, new emotes that show up in normal room use surface here for
review. Cross-check a captured id against a fresh `candidates.json` (or
the public catalog page) to fill in its name/rarity, time its duration by
hand, and add it to `config/emotes.json` directly.
