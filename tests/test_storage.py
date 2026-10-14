import tempfile
import unittest
from pathlib import Path

from highrise_bot.storage import Storage


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmpdir.name) / "test.db")
        await self.storage.connect()

    async def asyncTearDown(self) -> None:
        await self.storage.close()
        self._tmpdir.cleanup()

    async def test_warnings_start_at_zero_and_increment(self) -> None:
        self.assertEqual(await self.storage.get_warning_count("u1"), 0)

        self.assertEqual(await self.storage.increment_warning("u1"), 1)
        self.assertEqual(await self.storage.increment_warning("u1"), 2)
        self.assertEqual(await self.storage.get_warning_count("u1"), 2)

    async def test_reset_warnings_clears_to_zero(self) -> None:
        await self.storage.increment_warning("u1")
        await self.storage.increment_warning("u1")

        await self.storage.reset_warnings("u1")

        self.assertEqual(await self.storage.get_warning_count("u1"), 0)

    async def test_warnings_are_tracked_per_user(self) -> None:
        await self.storage.increment_warning("u1")
        await self.storage.increment_warning("u2")
        await self.storage.increment_warning("u2")

        self.assertEqual(await self.storage.get_warning_count("u1"), 1)
        self.assertEqual(await self.storage.get_warning_count("u2"), 2)

    async def test_scores_accumulate_and_report_top_scores(self) -> None:
        for _ in range(3):
            await self.storage.add_point("alice")
        for _ in range(5):
            await self.storage.add_point("bob")
        await self.storage.add_point("carol")

        self.assertEqual(await self.storage.get_score("bob"), 5)
        top = await self.storage.top_scores(limit=2)
        self.assertEqual(top, [("bob", 5), ("alice", 3)])

    async def test_settings_round_trip(self) -> None:
        self.assertIsNone(await self.storage.get_setting("warning_mute_threshold"))

        await self.storage.set_setting("warning_mute_threshold", "5")
        self.assertEqual(await self.storage.get_setting("warning_mute_threshold"), "5")

        await self.storage.set_setting("warning_mute_threshold", "7")
        self.assertEqual(await self.storage.get_setting("warning_mute_threshold"), "7")

        all_settings = await self.storage.all_settings()
        self.assertEqual(all_settings, {"warning_mute_threshold": "7"})

    async def test_username_cache_round_trip(self) -> None:
        self.assertIsNone(await self.storage.get_username("u1"))

        await self.storage.remember_username("u1", "Alice")
        self.assertEqual(await self.storage.get_username("u1"), "Alice")

        await self.storage.remember_username("u1", "AliceRenamed")
        self.assertEqual(await self.storage.get_username("u1"), "AliceRenamed")

    async def test_data_survives_reconnecting_to_the_same_file(self) -> None:
        await self.storage.increment_warning("u1")
        await self.storage.add_point("u1")
        await self.storage.set_setting("k", "v")
        await self.storage.close()

        reopened = Storage(self.storage._path)
        await reopened.connect()
        try:
            self.assertEqual(await reopened.get_warning_count("u1"), 1)
            self.assertEqual(await reopened.get_score("u1"), 1)
            self.assertEqual(await reopened.get_setting("k"), "v")
        finally:
            await reopened.close()
            # Prevent asyncTearDown from closing the already-closed original.
            self.storage._conn = None

    async def test_warning_audit_tips_favorites_and_profile_data_persist(self) -> None:
        self.assertEqual(
            await self.storage.record_warning("u1", "spam", source="manual", actor_id="mod"),
            1,
        )
        self.assertEqual(await self.storage.record_join("u1"), 1)
        await self.storage.add_xp("u1", 20)
        await self.storage.add_tip("u1", 100)
        await self.storage.set_favorite("u1", 1, 7)

        self.assertEqual(await self.storage.get_tip_total("u1"), 100)
        self.assertEqual(await self.storage.get_xp("u1"), 25)
        self.assertEqual(await self.storage.list_favorites("u1"), [(1, 7)])
        self.assertEqual(await self.storage.top_tippers(), [("u1", 100)])


if __name__ == "__main__":
    unittest.main()
