from __future__ import annotations

from dataclasses import dataclass

# Each riddle names a well-known, generic phrase or thing via emoji — no
# quoted text or lyrics from any copyrighted work, just short factual names
# guessed from a picture clue (the same idea as any "guess the emoji" game).
RIDDLES: tuple[tuple[str, str, str], ...] = (
    ("🍯 🐻", "winnie the pooh", "a bear who loves honey"),
    ("🕷️ 🧑", "spiderman", "a superhero who swings on webs"),
    ("❄️ 👸", "frozen", "a movie about two royal sisters"),
    ("🦁 👑", "lion king", "a movie about a young lion prince"),
    ("🐟 🔍", "finding nemo", "a movie about a lost clownfish"),
    ("🏠 🎈", "up", "a movie where a house flies with balloons"),
    ("🤖 ❤️", "wall-e", "a movie about a trash-collecting robot"),
    ("🦖 🏝️", "jurassic park", "a movie about a dinosaur theme park"),
    ("🌧️ 🐱 🐶", "raining cats and dogs", "an idiom for heavy rain"),
    ("🍎 👨‍⚕️ ➡️ 🚫", "an apple a day keeps the doctor away", "a health saying"),
)


@dataclass(frozen=True, slots=True)
class RiddleRound:
    clue: str
    answer: str
    hint: str


class EmojiRiddleGame:
    def __init__(self) -> None:
        self._index = -1
        self.current: RiddleRound | None = None

    def start_next(self) -> RiddleRound:
        self._index = (self._index + 1) % len(RIDDLES)
        clue, answer, hint = RIDDLES[self._index]
        self.current = RiddleRound(clue=clue, answer=answer, hint=hint)
        return self.current

    def check(self, guess: str) -> bool:
        return self.current is not None and guess.strip().casefold() == self.current.answer.casefold()

    def clear(self) -> None:
        self.current = None
