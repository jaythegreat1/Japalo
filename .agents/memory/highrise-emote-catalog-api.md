---
name: Highrise emote catalog API
description: The current Highrise catalog endpoint behavior and the safe source for emote names.
---

Highrise's `/items?category=emote` collection filter can return zero rows even while the catalog is populated. The unfiltered collection can also label no records as `emote`. For known IDs, `/items/<item_id>` is the reliable source of current existence, category, rarity, and the exact in-game `item_name`.

**Why:** A bulk refresh using only the documented collection filter produced an empty result, while item-detail requests returned valid emote records and names. Treating the empty collection as proof that all emotes disappeared would destroy the catalog.

**How to apply:** Prefer item-detail lookups for the configured IDs when synchronizing names or checking current records. Keep the runtime removal path for IDs Highrise rejects when targeting the actual user.