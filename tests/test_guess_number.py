import unittest

from highrise_bot.games.guess_number import GuessNumberGame


class GuessNumberGameTests(unittest.TestCase):
    def test_correct_guess_returns_correct(self) -> None:
        game = GuessNumberGame(low=1, high=50)
        round_ = game.start_next()

        self.assertEqual(game.guess(round_.secret), "correct")

    def test_out_of_range_guess_is_rejected_without_using_an_attempt(self) -> None:
        game = GuessNumberGame(low=1, high=50)
        round_ = game.start_next()

        self.assertEqual(game.guess(999), "out_of_range")
        self.assertEqual(round_.attempts, 0)

    def test_higher_and_lower_feedback(self) -> None:
        game = GuessNumberGame(low=1, high=50)
        round_ = game.start_next()

        too_low = max(round_.low, round_.secret - 1) if round_.secret > round_.low else None
        too_high = min(round_.high, round_.secret + 1) if round_.secret < round_.high else None

        if too_low is not None and too_low != round_.secret:
            self.assertEqual(game.guess(too_low), "higher")
        if too_high is not None and too_high != round_.secret:
            self.assertEqual(game.guess(too_high), "lower")

    def test_runs_out_of_attempts(self) -> None:
        game = GuessNumberGame(low=1, high=50)
        round_ = game.start_next()
        wrong_guess = round_.low if round_.secret != round_.low else round_.high

        for _ in range(round_.max_attempts - 1):
            result = game.guess(wrong_guess)
            self.assertIn(result, {"higher", "lower"})

        self.assertEqual(game.guess(wrong_guess), "no_more_attempts")

    def test_clear_removes_current_round(self) -> None:
        game = GuessNumberGame()
        game.start_next()

        game.clear()

        self.assertIsNone(game.current)
        self.assertEqual(game.guess(10), "no_more_attempts")


if __name__ == "__main__":
    unittest.main()
