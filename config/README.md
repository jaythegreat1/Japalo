# Exact emote catalog

`emotes.json` contains the verified emotes currently exposed by the official
Highrise catalog. The names and rarity values come from the catalog, while the
Highrise `emote_id` strings and loop durations were cross-checked against a
public Highrise bot mapping. Only entries with both checks are included; this is
deliberately safer than padding the list with guessed IDs.

```json
{
  "name": "Exact display name",
  "id": "exact-highrise-emote-id",
  "rarity": "common",
  "duration_seconds": 2.5
}
```

Allowed rarities are the exact Highrise values `common`, `none_`, `uncommon`,
`rare`, and `epic`. Live-verified animation IDs without an official catalog
rarity use the explicit `unknown` marker; it is not a guessed rarity.
Legendary emotes are rejected on purpose. The `id` is sent directly to Highrise and
`duration_seconds` controls the repeat interval, so neither value should be
guessed or copied from a different emote.

Sources used for the current manifest:

- Official catalog: <https://highrise.game/catalog?clothing=emote&page=1&type=clothing>
- Public mapping cross-check: <https://github.com/iWolfyy/HighRise-Bot/blob/main/emote_manager.py>
- Current npm mapping cross-check: <https://www.npmjs.com/package/highrise.bot>

The catalog can change over time. If Highrise changes an emote ID or animation,
update the entry only after re-checking both the official catalog and a current
mapping or measured duration.

Entries are numbered in file order. `!emotelist` whispers the full list,
`!emotelist common` filters by rarity, and `!findemote wave` searches by name or
animation ID. A user can start an emote targeted at themselves with its number,
then type `stop` to cancel their own loop.