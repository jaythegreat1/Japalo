import unittest

from highrise_bot.games.scramble import WORDS, ScrambleGame


class ScrambleGameTests(unittest.TestCase):
    def test_round_scrambles_and_checks_answer_case_insensitively(self) -> None:
        game = ScrambleGame()

        round_ = game.start_next()

        self.assertEqual(sorted(round_.scrambled.casefold()), sorted(round_.answer))
        self.assertTrue(game.check(round_.answer.upper()))
        self.assertTrue(game.check(f"  {round_.answer}  "))
        self.assertFalse(game.check("not-the-answer"))

    def test_words_rotate_instead_of_repeating_immediately(self) -> None:
        game = ScrambleGame()

        first = game.start_next()
        game.clear()
        second = game.start_next()

        self.assertNotEqual(first.answer, second.answer)

    def test_clear_removes_current_round(self) -> None:
        game = ScrambleGame()
        game.start_next()

        game.clear()

        self.assertIsNone(game.current)
        self.assertFalse(game.check("anything"))

    def test_word_list_has_no_duplicates(self) -> None:
        words = [word for word, _hint in WORDS]
        self.assertEqual(len(words), len(set(words)))


if __name__ == "__main__":
    unittest.main()
