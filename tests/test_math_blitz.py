import unittest

from highrise_bot.games.math_blitz import MathBlitzGame


class MathBlitzGameTests(unittest.TestCase):
    def test_round_prompt_evaluates_to_the_stored_answer(self) -> None:
        game = MathBlitzGame()

        for _ in range(200):  # exercise +, -, * across many random rounds
            round_ = game.start_next()
            a_str, op, b_str = round_.prompt.split(" ")
            a, b = int(a_str), int(b_str)
            expected = {"+": a + b, "-": a - b, "*": a * b}[op]

            self.assertEqual(round_.answer, expected)
            self.assertGreaterEqual(a, 0)
            self.assertGreaterEqual(b, 0)

    def test_check_accepts_correct_answer_with_surrounding_whitespace(self) -> None:
        game = MathBlitzGame()
        round_ = game.start_next()

        self.assertTrue(game.check(f"  {round_.answer}  "))
        self.assertFalse(game.check(str(round_.answer + 1)))
        self.assertFalse(game.check("not-a-number"))

    def test_check_without_active_round_is_false(self) -> None:
        game = MathBlitzGame()
        self.assertFalse(game.check("5"))

    def test_subtraction_never_goes_negative(self) -> None:
        game = MathBlitzGame()
        for _ in range(200):
            round_ = game.start_next()
            if " - " in round_.prompt:
                self.assertGreaterEqual(round_.answer, 0)


if __name__ == "__main__":
    unittest.main()
