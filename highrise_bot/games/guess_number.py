from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(slots=True)
class GuessNumberRound:
    secret: int
    low: int
    high: int
    attempts: int = 0
    max_attempts: int = 12


class GuessNumberGame:
    def __init__(self, low: int = 1, high: int = 50) -> None:
        self._low = low
        self._high = high
        self.current: GuessNumberRound | None = None

    def start_next(self) -> GuessNumberRound:
        self.current = GuessNumberRound(
            secret=random.randint(self._low, self._high),
            low=self._low,
            high=self._high,
        )
        return self.current

    def guess(self, value: int) -> str:
        """Returns 'correct', 'higher', 'lower', 'out_of_range', or 'no_more_attempts'."""
        round_ = self.current
        if round_ is None:
            return "no_more_attempts"
        if value < round_.low or value > round_.high:
            return "out_of_range"
        round_.attempts += 1
        if value == round_.secret:
            return "correct"
        if round_.attempts >= round_.max_attempts:
            return "no_more_attempts"
        return "higher" if value < round_.secret else "lower"

    def clear(self) -> None:
        self.current = None
