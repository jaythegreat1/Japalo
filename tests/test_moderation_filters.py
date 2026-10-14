import json
import tempfile
import unittest
from pathlib import Path

from highrise_bot.moderation_filters import (
    SpamTracker,
    load_word_filter,
    should_auto_mute,
)


class SpamTrackerTests(unittest.TestCase):
    def test_flags_after_threshold_messages_within_window(self) -> None:
        tracker = SpamTracker(window_seconds=5.0, threshold=3)

        self.assertFalse(tracker.record("user-1", now=0.0))
        self.assertFalse(tracker.record("user-1", now=0.5))
        self.assertTrue(tracker.record("user-1", now=1.0))

    def test_messages_outside_the_window_do_not_count(self) -> None:
        tracker = SpamTracker(window_seconds=5.0, threshold=3)

        self.assertFalse(tracker.record("user-1", now=0.0))
        self.assertFalse(tracker.record("user-1", now=10.0))
        self.assertFalse(tracker.record("user-1", now=10.5))

    def test_tracks_users_independently(self) -> None:
        tracker = SpamTracker(window_seconds=5.0, threshold=3)

        self.assertFalse(tracker.record("user-1", now=0.0))
        self.assertFalse(tracker.record("user-2", now=0.0))
        self.assertFalse(tracker.record("user-1", now=0.1))
        self.assertTrue(tracker.record("user-1", now=0.2))
        # user-2 only ever sent one message, so it should never trip.
        self.assertFalse(tracker.record("user-2", now=0.2))

    def test_per_call_overrides_take_effect_immediately(self) -> None:
        tracker = SpamTracker(window_seconds=5.0, threshold=10)  # very lax by default

        self.assertFalse(tracker.record("user-1", now=0.0))
        # A live !config change tightens the threshold for this call only.
        self.assertTrue(tracker.record("user-1", now=0.1, threshold=2))


class ShouldAutoMuteTests(unittest.TestCase):
    def test_fires_at_every_multiple_of_the_threshold(self) -> None:
        results = [should_auto_mute(count, mute_threshold=3) for count in range(1, 7)]
        self.assertEqual(results, [False, False, True, False, False, True])

    def test_zero_never_fires(self) -> None:
        self.assertFalse(should_auto_mute(0, mute_threshold=3))

    def test_uses_the_default_threshold_when_not_overridden(self) -> None:
        self.assertTrue(should_auto_mute(3))
        self.assertFalse(should_auto_mute(2))


class WordFilterTests(unittest.TestCase):
    def test_matches_whole_word_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moderation_words.json"
            path.write_text(
                json.dumps({"blocked_phrases": ["idiot", "shut up"]}), encoding="utf-8"
            )
            word_filter = load_word_filter(path)

        self.assertEqual(word_filter.matches("you are an idiot"), "idiot")
        self.assertEqual(word_filter.matches("just shut up already"), "shut up")
        self.assertIsNone(word_filter.matches("idiotic behavior is unrelated"))
        self.assertIsNone(word_filter.matches("a totally normal message"))

    def test_missing_config_file_disables_the_filter(self) -> None:
        word_filter = load_word_filter(Path("/nonexistent/moderation_words.json"))
        self.assertIsNone(word_filter.matches("literally anything at all idiot"))


if __name__ == "__main__":
    unittest.main()
