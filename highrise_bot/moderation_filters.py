from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SPAM_WINDOW_SECONDS = 6.0
DEFAULT_SPAM_MESSAGE_THRESHOLD = 5
DEFAULT_WARNING_MUTE_THRESHOLD = 3
DEFAULT_AUTO_MUTE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class WordFilter:
    """Case-insensitive, whole-word/phrase matcher against a configured list."""

    blocked_phrases: tuple[str, ...]

    def matches(self, text: str) -> str | None:
        lowered = text.casefold()
        for phrase in self.blocked_phrases:
            pattern = r"\b" + re.escape(phrase.casefold()) + r"\b"
            if re.search(pattern, lowered):
                return phrase
        return None


def load_word_filter(path: Path) -> WordFilter:
    """Loads config/moderation_words.json. Missing file = filter disabled."""
    if not path.exists():
        return WordFilter(blocked_phrases=())

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    phrases = raw.get("blocked_phrases", [])
    if not isinstance(phrases, list) or not all(isinstance(item, str) for item in phrases):
        raise ValueError(
            "config/moderation_words.json: 'blocked_phrases' must be a list of strings"
        )
    return WordFilter(blocked_phrases=tuple(phrases))


class SpamTracker:
    """Flags a user who sends too many messages within a short window."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_SPAM_WINDOW_SECONDS,
        threshold: int = DEFAULT_SPAM_MESSAGE_THRESHOLD,
    ) -> None:
        self._window = window_seconds
        self._threshold = threshold
        self._history: dict[str, deque[float]] = {}

    def record(
        self,
        user_id: str,
        now: float | None = None,
        window_seconds: float | None = None,
        threshold: int | None = None,
    ) -> bool:
        """Records one message; returns True if this trips the spam threshold.

        window_seconds/threshold override the instance defaults for this
        call only, so live !config changes take effect immediately without
        losing each user's in-progress message history.
        """
        now = time.monotonic() if now is None else now
        window = self._window if window_seconds is None else window_seconds
        limit = self._threshold if threshold is None else threshold
        history = self._history.setdefault(user_id, deque())
        history.append(now)
        while history and now - history[0] > window:
            history.popleft()
        if len(history) >= limit:
            # Reset so the very next message doesn't immediately re-trigger.
            history.clear()
            return True
        return False


def should_auto_mute(count: int, mute_threshold: int = DEFAULT_WARNING_MUTE_THRESHOLD) -> bool:
    """True if this warning count should trigger an auto-mute.

    Fires at every multiple of the threshold (3rd, 6th, 9th... warning)
    rather than only the first time, so repeat offenders keep getting
    muted rather than becoming exempt after their first auto-mute.

    Stateless on purpose: warning counts are persisted in Storage (SQLite)
    now, as of Phase 0, so this only needs to judge a count someone else
    is tracking — no in-memory counter to keep in sync with the database.
    """
    return count > 0 and count % mute_threshold == 0
