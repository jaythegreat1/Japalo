from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MathRound:
    prompt: str
    answer: int


def _generate() -> MathRound:
    operation = random.choice(("+", "-", "*"))
    if operation == "+":
        a, b = random.randint(2, 50), random.randint(2, 50)
        answer = a + b
    elif operation == "-":
        a, b = random.randint(2, 50), random.randint(2, 50)
        if b > a:
            a, b = b, a
        answer = a - b
    else:  # "*"
        a, b = random.randint(2, 12), random.randint(2, 12)
        answer = a * b
    return MathRound(prompt=f"{a} {operation} {b}", answer=answer)


class MathBlitzGame:
    def __init__(self) -> None:
        self.current: MathRound | None = None

    def start_next(self) -> MathRound:
        self.current = _generate()
        return self.current

    def check(self, guess: str) -> bool:
        if self.current is None:
            return False
        try:
            value = int(guess.strip())
        except ValueError:
            return False
        return value == self.current.answer

    def clear(self) -> None:
        self.current = None
