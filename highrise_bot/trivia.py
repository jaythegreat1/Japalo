from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True, slots=True)
class TriviaQuestion:
    prompt: str
    choices: tuple[str, ...]
    answer: str
    explanation: str
    category: str
    difficulty: str


QUESTIONS: tuple[TriviaQuestion, ...] = (
    TriviaQuestion(
        prompt="Which planet is known as the Red Planet?",
        choices=("A) Venus", "B) Mars", "C) Jupiter", "D) Mercury"),
        answer="b",
        explanation="Mars looks red because of iron minerals on its surface.",
        category="science",
        difficulty="easy",
    ),
    TriviaQuestion(
        prompt="How many sides does a hexagon have?",
        choices=("A) Five", "B) Six", "C) Seven", "D) Eight"),
        answer="b",
        explanation="A hexagon has six sides.",
        category="math",
        difficulty="easy",
    ),
    TriviaQuestion(
        prompt="What is the largest ocean on Earth?",
        choices=("A) Atlantic", "B) Indian", "C) Pacific", "D) Arctic"),
        answer="c",
        explanation="The Pacific Ocean is the largest.",
        category="geography",
        difficulty="easy",
    ),
    TriviaQuestion(
        prompt="Which animal is famous for changing its color?",
        choices=("A) Chameleon", "B) Penguin", "C) Dolphin", "D) Giraffe"),
        answer="a",
        explanation="Chameleons are known for changing their skin color.",
        category="nature",
        difficulty="easy",
    ),
    TriviaQuestion(
        "Who painted the Mona Lisa?",
        ("A) Michelangelo", "B) Leonardo da Vinci", "C) Van Gogh", "D) Monet"),
        "b", "Leonardo da Vinci painted the Mona Lisa.", "history", "easy",
    ),
    TriviaQuestion(
        "What gas do plants absorb from the atmosphere?",
        ("A) Oxygen", "B) Nitrogen", "C) Carbon dioxide", "D) Helium"),
        "c", "Plants use carbon dioxide during photosynthesis.", "science", "easy",
    ),
    TriviaQuestion(
        "Which country is home to the city of Kyoto?",
        ("A) China", "B) Japan", "C) Thailand", "D) Korea"),
        "b", "Kyoto is a historic city in Japan.", "geography", "easy",
    ),
    TriviaQuestion(
        "In which sport would you perform a slam dunk?",
        ("A) Tennis", "B) Basketball", "C) Volleyball", "D) Baseball"),
        "b", "A slam dunk is a basketball shot.", "sports", "easy",
    ),
    TriviaQuestion(
        "What is the chemical symbol for gold?",
        ("A) Ag", "B) Go", "C) Au", "D) Gd"),
        "c", "Gold's symbol is Au, from the Latin aurum.", "science", "medium",
    ),
    TriviaQuestion(
        "Which novel begins with the line 'Call me Ishmael'?",
        ("A) Moby-Dick", "B) Dracula", "C) The Odyssey", "D) Dune"),
        "a", "The line opens Herman Melville's Moby-Dick.", "literature", "medium",
    ),
    TriviaQuestion(
        "What is the smallest prime number?",
        ("A) 0", "B) 1", "C) 2", "D) 3"),
        "c", "Two is the first and only even prime number.", "math", "easy",
    ),
    TriviaQuestion(
        "Which ocean lies between Africa and Australia?",
        ("A) Atlantic", "B) Indian", "C) Pacific", "D) Southern"),
        "b", "The Indian Ocean lies between those continents.", "geography", "medium",
    ),
    TriviaQuestion(
        "What does CPU stand for?",
        ("A) Central Processing Unit", "B) Computer Power Utility",
         "C) Core Program User", "D) Central Program Upload"),
        "a", "CPU means Central Processing Unit.", "technology", "easy",
    ),
    TriviaQuestion(
        "Which instrument has 88 keys in its standard form?",
        ("A) Violin", "B) Flute", "C) Piano", "D) Harp"),
        "c", "A standard modern piano has 88 keys.", "music", "easy",
    ),
)


class TriviaGame:
    def __init__(self) -> None:
        self._questions = list(QUESTIONS)
        self._question_index = -1
        self.current: TriviaQuestion | None = None

    def start_next(self) -> TriviaQuestion:
        if self._question_index == -1 or self._question_index >= len(self._questions) - 1:
            random.shuffle(self._questions)
            self._question_index = -1
        self._question_index += 1
        self.current = self._questions[self._question_index]
        return self.current

    def answer_is_correct(self, choice: str) -> bool:
        return self.current is not None and choice.strip().lower() == self.current.answer

    def clear(self) -> None:
        self.current = None