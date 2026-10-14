import unittest
from unittest.mock import patch

from highrise_bot.messages import (
    JOIN_MESSAGES,
    LEAVE_MESSAGES,
    plain_join_message,
    plain_leave_message,
    random_join_message,
    random_leave_message,
)


class WelcomeMessageTests(unittest.TestCase):
    def test_there_are_plenty_of_join_and_leave_messages(self) -> None:
        # Personality expansion: a big, blended-tone pool rather than one
        # narrow joke repeated. Exact count is allowed to grow further.
        self.assertGreaterEqual(len(JOIN_MESSAGES), 15)
        self.assertGreaterEqual(len(LEAVE_MESSAGES), 10)

    def test_messages_include_the_username_and_use_random_choice(self) -> None:
        with patch(
            "highrise_bot.messages.random.choice",
            side_effect=[JOIN_MESSAGES[0], LEAVE_MESSAGES[0]],
        ) as choice:
            self.assertIn("Player", random_join_message("Player"))
            self.assertIn("Player", random_leave_message("Player"))

        self.assertEqual(choice.call_count, 2)

    def test_all_join_and_leave_messages_format_cleanly(self) -> None:
        for template in JOIN_MESSAGES:
            template.format(username="Player", bot="Japalo")
        for template in LEAVE_MESSAGES:
            template.format(username="Player", bot="Japalo")

    def test_plain_fallbacks_are_stable_and_unflavored(self) -> None:
        self.assertEqual(plain_join_message("Player"), "Welcome, Player!")
        self.assertEqual(plain_leave_message("Player"), "Player has left the room.")


if __name__ == "__main__":
    unittest.main()
