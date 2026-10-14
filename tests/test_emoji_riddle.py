import unittest

from highrise_bot.games.emoji_riddle import RIDDLES, EmojiRiddleGame


class EmojiRiddleGameTests(unittest.TestCase):
    def test_round_checks_answer_case_insensitively(self) -> None:
        game = EmojiRiddleGame()

        round_ = game.start_next()

        self.assertTrue(game.check(round_.answer.upper()))
        self.assertTrue(game.check(f"  {round_.answer}  "))
        self.assertFalse(game.check("definitely not it"))

    def test_riddles_rotate_instead_of_repeating_immediately(self) -> None:
        game = EmojiRiddleGame()

        first = game.start_next()
        game.clear()
        second = game.start_next()

        self.assertNotEqual(first.answer, second.answer)

    def test_riddle_bank_has_no_duplicate_answers(self) -> None:
        answers = [answer for _clue, answer, _hint in RIDDLES]
        self.assertEqual(len(answers), len(set(answers)))


if __name__ == "__main__":
    unittest.main()
