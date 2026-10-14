---
name: Highrise emote audit
description: Evidence and boundary for interpreting Highrise emote rejection responses.
---

The catalog must not remove an emote solely because Highrise returns “Emote is not free or owned by target user” when the request targets a player. A live audit of all 342 non-legendary IDs with no target user accepted every ID, so that response is target-specific or transient rather than proof that the animation is globally unreleased.

**Why:** The same catalog entry can pass direct and repeated checks, fail intermittently through the production loop when targeting a player, and pass when the bot performs it itself. The public items endpoint currently returns no emote-category records, so it cannot independently validate the list.

**How to apply:** Keep the catalog unchanged unless an emote fails consistently in a bot-self audit or there is independent release evidence. Treat player-target failures as a command-target/Highrise entitlement issue and preserve the exact target user ID and error in diagnostics.