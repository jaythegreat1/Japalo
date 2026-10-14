"""Two-player emote interactions: !punch, !slap, !explode.

config/interactions.json lists, per interaction:
  actor   emote ids the speaker performs, first one Highrise accepts wins
          (empty list = the speaker doesn't emote)
  target  emote ids the tagged player performs, tried in order; leave it out
          to use a random emote from the shared "falls" pool
  impact_delay_seconds  wait between the speaker's emote and the target's
All ids are exact Highrise emote ids from config/emotes.json:

  punch    speaker Punch (#35, fallback Super Punch #6), target falls
  slap     speaker Slap (#216), target falls
  explode  speaker nothing, target Boo (#73)
  falls    Fall #71, Collapse #24, Faint Drop #107, Clumsy #106, Fail #196
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Interaction:
    name: str
    actor_emote_ids: tuple[str, ...]  # empty: the speaker doesn't emote
    target_emote_ids: tuple[str, ...]  # empty: a random emote from the falls pool
    impact_delay_seconds: float


@dataclass(frozen=True, slots=True)
class InteractionBook:
    interactions: dict[str, Interaction]
    fall_emote_ids: tuple[str, ...]

    def get(self, name: str) -> Interaction | None:
        return self.interactions.get(name)

    def all_emote_ids(self) -> set[str]:
        ids = set(self.fall_emote_ids)
        for interaction in self.interactions.values():
            ids.update(interaction.actor_emote_ids)
            ids.update(interaction.target_emote_ids)
        return ids


def _id_list(raw: object, where: str, allow_empty: bool = False) -> tuple[str, ...]:
    if raw is None and allow_empty:
        return ()
    if (
        not isinstance(raw, list)
        or (not raw and not allow_empty)
        or not all(isinstance(x, str) and x.strip() for x in raw)
    ):
        raise ValueError(f"{where} must be a list of emote id strings")
    return tuple(x.strip() for x in raw)


def load_interactions(path: Path) -> InteractionBook:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    falls = _id_list(raw.get("falls"), "falls")
    interactions = {}
    for name, spec in (raw.get("interactions") or {}).items():
        delay = spec.get("impact_delay_seconds", 0.8)
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0 <= delay <= 5:
            raise ValueError(f"{name}: impact_delay_seconds must be a number from 0 to 5")
        interactions[name.casefold()] = Interaction(
            name=name.casefold(),
            actor_emote_ids=_id_list(spec.get("actor"), f"{name}.actor", allow_empty=True),
            target_emote_ids=_id_list(spec.get("target"), f"{name}.target", allow_empty=True),
            impact_delay_seconds=float(delay),
        )
    if not interactions:
        raise ValueError("interactions must define at least one interaction")
    return InteractionBook(interactions=interactions, fall_emote_ids=falls)
