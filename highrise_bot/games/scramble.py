from __future__ import annotations

import random
from dataclasses import dataclass

WORDS: tuple[tuple[str, str], ...] = (
    ("highrise", "the game we're all in right now"),
    ("avatar", "your in-game character"),
    ("emote", "a move you can trigger with a number"),
    ("trivia", "a quiz minigame"),
    ("penguin", "a flightless bird that waddles"),
    ("rainbow", "colorful arc after rain"),
    ("dolphin", "a smart sea mammal"),
    ("volcano", "a mountain that can erupt"),
    ("guitar", "a stringed instrument"),
    ("dragon", "a mythical fire-breathing creature"),
    ("planet", "Earth is one of these"),
    ("castle", "a fortress with towers"),
    ("mystery", "something unexplained"),
    ("jungle", "a dense tropical forest"),
    ("thunder", "the sound after lightning"),
)


@dataclass(frozen=True, slots=True)
class ScrambleRound:
    scrambled: str
    answer: str
    hint: str


def _scramble(word: str) -> str:
    letters = list(word)
    attempts = 0
    scrambled = word
    # Keep reshuffling until it differs from the original (or give up after
    # a reasonable number of attempts, which only matters for very short
    # words where a different order may not exist).
    while scrambled == word and attempts < 20:
        random.shuffle(letters)
        scrambled = "".join(letters)
        attempts += 1
    return scrambled


class ScrambleGame:
    def __init__(self) -> None:
        self._word_index = -1
        self.current: ScrambleRound | None = None

    def start_next(self) -> ScrambleRound:
        self._word_index = (self._word_index + 1) % len(WORDS)
        word, hint = WORDS[self._word_index]
        self.current = ScrambleRound(
            scrambled=_scramble(word).upper(), answer=word, hint=hint
        )
        return self.current

    def check(self, guess: str) -> bool:
        return self.current is not None and guess.strip().casefold() == self.current.answer.casefold()

    def clear(self) -> None:
        self.current = None
