import unittest

from highrise_bot.trivia import TriviaGame


class TriviaGameTests(unittest.TestCase):
    def test_round_lifecycle_and_answer_matching(self) -> None:
        game = TriviaGame()

        question = game.start_next()

        self.assertIs(game.current, question)
        self.assertTrue(game.answer_is_correct(question.answer.upper()))
        self.assertFalse(game.answer_is_correct("not-an-answer"))

        game.clear()

        self.assertIsNone(game.current)
        self.assertFalse(game.answer_is_correct(question.answer))

    def test_questions_rotate_instead_of_repeating_immediately(self) -> None:
        game = TriviaGame()

        first = game.start_next()
        game.clear()
        second = game.start_next()

        self.assertNotEqual(first.prompt, second.prompt)


if __name__ == "__main__":
    unittest.main()