"""Numbered emote list, loaded from emotes.json so it can match any bot's numbering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("emotes.json")


@dataclass(frozen=True)
class Emote:
    number: int
    name: str
    id: str


class EmoteBook:
    def __init__(self, emotes: list[Emote]):
        self.emotes = emotes
        self._by_name = {e.name.lower(): e for e in emotes}
        self._by_id = {e.id.lower(): e for e in emotes}

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "EmoteBook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data["emotes"] if isinstance(data, dict) else data
        return cls([Emote(i, str(e["name"]), str(e["id"])) for i, e in enumerate(items, 1)])

    def find(self, ref: str | int) -> Emote | None:
        """Look up by number ("65"), name ("macarena") or Highrise id ("dance-macarena")."""
        text = str(ref).strip().lower().lstrip("#")
        if text.isdigit():
            n = int(text)
            return self.emotes[n - 1] if 1 <= n <= len(self.emotes) else None
        return self._by_name.get(text) or self._by_id.get(text)

    def catalog(self) -> str:
        """Compact 'number:name' list for the AI prompt."""
        return " ".join(f"{e.number}:{e.name}" for e in self.emotes)
