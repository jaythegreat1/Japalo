"""Numbered emote list, loaded from emotes.json so it can match any bot's numbering.

emotes.json is the verified 265-emote catalog from the main Japalo Highrise bot
(config/emotes.json there): number = position in the list, starting at 1, the
same numbering that bot uses, so "65" is the same emote in both.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("emotes.json")


@dataclass(frozen=True)
class Emote:
    number: int
    name: str
    id: str
    rarity: str = ""
    duration_seconds: float = 0.0


def _key(text: str) -> str:
    """'Let's Go Shopping' -> 'letsgoshopping', so names match however they're typed."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


class EmoteBook:
    def __init__(self, emotes: list[Emote]):
        self.emotes = emotes
        self._by_name = {_key(e.name): e for e in emotes}
        self._by_id = {e.id.lower(): e for e in emotes}

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "EmoteBook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data["emotes"] if isinstance(data, dict) else data
        return cls([
            Emote(i, str(e["name"]), str(e["id"]), str(e.get("rarity", "")), float(e.get("duration_seconds", 0)))
            for i, e in enumerate(items, 1)
        ])

    def find(self, ref: str | int) -> Emote | None:
        """Look up by number ("65"), name ("macarena") or Highrise id ("dance-macarena")."""
        text = str(ref).strip().lower().lstrip("#")
        if text.isdigit():
            n = int(text)
            return self.emotes[n - 1] if 1 <= n <= len(self.emotes) else None
        found = self._by_id.get(text) or self._by_name.get(_key(text))
        if found or len(_key(text)) < 3:
            return found
        partial = [e for e in self.emotes if _key(text) in _key(e.name)]
        return partial[0] if len(partial) == 1 else None

    def catalog(self) -> str:
        """Compact 'number:name' list for the AI prompt."""
        return " ".join(f"{e.number}:{e.name}" for e in self.emotes)
