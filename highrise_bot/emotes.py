from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ALLOWED_RARITIES = frozenset(
    {"common", "none_", "unknown", "uncommon", "rare", "epic"}
)


@dataclass(frozen=True, slots=True)
class Emote:
    """One exact Highrise emote definition from the room owner's manifest."""

    name: str
    emote_id: str
    rarity: str
    duration_seconds: float


class EmoteCatalog:
    def __init__(self, emotes: Iterable[Emote]) -> None:
        self._emotes = tuple(emotes)
        self._by_number = {index: emote for index, emote in enumerate(self._emotes, 1)}

    def __len__(self) -> int:
        return len(self._emotes)

    def known_ids(self) -> frozenset[str]:
        """All configured emote_id values, for fast 'is this new?' checks."""
        return frozenset(emote.emote_id for emote in self._emotes)

    def without_id(self, emote_id: str) -> tuple["EmoteCatalog", bool]:
        """Return a catalog without one id and whether anything was removed."""
        remaining = tuple(
            emote for emote in self._emotes if emote.emote_id != emote_id
        )
        if len(remaining) == len(self._emotes):
            return self, False
        return EmoteCatalog(remaining), True

    def get_by_number(self, number: int) -> Emote | None:
        return self._by_number.get(number)

    def filter(self, rarity: str | None = None, query: str | None = None) -> list[tuple[int, Emote]]:
        """Return numbered entries matching an optional rarity/name/id query."""
        rarity = rarity.casefold() if rarity else None
        query = query.casefold().strip() if query else None
        return [
            (index, emote)
            for index, emote in enumerate(self._emotes, 1)
            if (rarity is None or emote.rarity == rarity)
            and (
                query is None
                or query in emote.name.casefold()
                or query in emote.emote_id.casefold()
            )
        ]

    def random(self, rarity: str | None = None) -> tuple[int, Emote] | None:
        matches = self.filter(rarity=rarity)
        return random.choice(matches) if matches else None

    def pages(
        self,
        page_size: int = 20,
        rarity: str | None = None,
        query: str | None = None,
    ) -> list[str]:
        matches = self.filter(rarity=rarity, query=query)
        if not matches:
            return [
                "No matching emotes. Use !emotelist, !emotelist common, or "
                "!findemote <name>."
            ]

        rows = [f"{index}. {emote.name} [{emote.rarity}]" for index, emote in matches]
        return [
            "\n".join(rows[start : start + page_size])
            for start in range(0, len(rows), page_size)
        ]


def _required_string(raw: dict[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"emote #{index}: {key!r} must be a non-empty string")
    return value.strip()


def _parse_emote(raw: Any, index: int) -> Emote:
    if not isinstance(raw, dict):
        raise ValueError(f"emote #{index}: each entry must be an object")

    name = _required_string(raw, "name", index)
    emote_id = _required_string(raw, "id", index)
    rarity = _required_string(raw, "rarity", index).lower()
    duration = raw.get("duration_seconds")

    if rarity not in ALLOWED_RARITIES:
        allowed = ", ".join(sorted(ALLOWED_RARITIES))
        raise ValueError(
            f"emote #{index} ({name}): rarity must be one of {allowed}; "
            "legendary emotes are intentionally excluded"
        )
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError(
            f"emote #{index} ({name}): duration_seconds must be a number"
        )
    if not math.isfinite(float(duration)) or float(duration) <= 0:
        raise ValueError(
            f"emote #{index} ({name}): duration_seconds must be greater than zero"
        )

    return Emote(
        name=name,
        emote_id=emote_id,
        rarity=rarity,
        duration_seconds=float(duration),
    )


def load_catalog(path: Path) -> EmoteCatalog:
    if not path.exists():
        raise FileNotFoundError(f"Emote catalog does not exist: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, list):
        raise ValueError("Emote catalog must be a JSON array")

    emotes = [_parse_emote(item, index) for index, item in enumerate(raw, 1)]
    ids = [emote.emote_id for emote in emotes]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate emote IDs are not allowed: {duplicate_ids}")

    return EmoteCatalog(emotes)