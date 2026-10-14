---
name: Japalo Python runtime
description: Runtime setup needed to run the Highrise bot verifier after moving the uploaded bot into a Replit project.
---

Japalo must run on the project's pinned Python 3.11 runtime. After moving the bot into a durable project, the conversation sandbox's installed packages do not carry over; install the pinned dependencies again with the explicit `python3.11 -m pip` command before testing or live verification.

**Why:** The Highrise SDK's Pendulum/distutils compatibility requires Python 3.11, and a successful install in a prior sandbox does not guarantee the project environment has the package.

**How to apply:** Confirm `which python3.11 && python3.11 --version`, install against that interpreter, and confirm `python3.11 -c "import highrise; print('ok')"` before running tests or Highrise commands. Never print secret values while checking the environment.

Highrise's official item records can use the non-legendary rarity value `none_`. Preserve that exact value in the manifest rather than converting it to `common`; the catalog validator and rarity filters accept it.

**Why:** Converting `none_` loses official metadata and makes the manifest disagree with the source API.

**How to apply:** When refreshing metadata, use the official item record for name, item ID, and rarity. Exclude only `legendary`; do not infer or bucket another rarity.

Live-accepted animation IDs that have no official rarity record use `unknown` until Highrise publishes matching metadata.

**Why:** The bot can expose verified working IDs without falsely claiming a rarity, while keeping future metadata backfills explicit.

**How to apply:** Keep `unknown` entries out of rarity assumptions and replace them only after an exact official metadata match; do not silently map them to `common` or `none_`.

Highrise emote validation must cover both one-shot sends and repeated loop sends; an error message mentioning ownership is not sufficient evidence that an ID is permanently inaccessible.

**Why:** The reported entries were accepted in a live target audit and in two-send repeat tests, while the production loop had intermittent rejections. Removing those valid entries would have been the wrong fix.

**How to apply:** Keep valid catalog IDs, retry transient send failures briefly, and include the exact catalog number/name/ID in any final failure log or user notice.