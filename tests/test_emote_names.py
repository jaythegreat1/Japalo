"""!emote <name> loops an emote by name, like typing its number."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from highrise_bot.bot import HighriseRoomBot
from highrise_bot.storage import Storage
from tests.test_ai import AMY, OWNER, ZED, FakeBrain, FakeHighrise


class EmoteNameTests(unittest.TestCase):
    def run_bot(self, scenario):
        async def wrapper():
            with tempfile.TemporaryDirectory() as tmp:
                bot = HighriseRoomBot()
                bot.storage = Storage(Path(tmp) / "test.db")
                await bot.storage.connect()
                bot.highrise = FakeHighrise()
                bot.room_owner_id = OWNER.id
                bot.brain = FakeBrain()

                async def say(user, text):
                    bot._command_cooldowns.clear()  # skip the 1s !command cooldown
                    await bot.on_chat(user, text)
                    await asyncio.sleep(0.05)

                try:
                    await scenario(bot, bot.highrise, say)
                finally:
                    for user in (AMY, OWNER, ZED):
                        await bot.emote_loops.stop(user.id)
                    await bot.storage.close()

        asyncio.run(wrapper())

    def last_whisper(self, hr, user):
        return [text for uid, text in hr.whispers if uid == user.id][-1]

    def test_name_loops_like_a_number_and_stop_ends_it(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote moonwalk")
            self.assertIn(("emote-gordonshuffle", AMY.id), hr.emotes)
            self.assertTrue(bot.emote_loops.is_running(AMY.id))
            self.assertIn("Moonwalk", self.last_whisper(hr, AMY))
            await say(AMY, "stop")
            self.assertFalse(bot.emote_loops.is_running(AMY.id))

        self.run_bot(scenario)

    def test_case_punctuation_and_apostrophes(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote Let's Go Shopping")  # apostrophe used to break the command reader
            await say(ZED, "!emote ROFL")
            await say(OWNER, "!emote pouty face")
            self.assertIn(("dance-shoppingcart", AMY.id), hr.emotes)
            self.assertIn(("emote-rofl", ZED.id), hr.emotes)
            self.assertIn(("idle-sad", OWNER.id), hr.emotes)

        self.run_bot(scenario)

    def test_unique_part_of_a_name(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote jetpack")
            self.assertIn(("emote-jetpack", AMY.id), hr.emotes)

        self.run_bot(scenario)

    def test_unclear_and_unknown_names(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote super")
            text = self.last_whisper(hr, AMY)
            self.assertIn("matches several emotes", text)
            self.assertIn("6. Super Punch", text)
            await say(AMY, "!emote flying spaghetti")
            self.assertIn("No emote called 'flying spaghetti'", self.last_whisper(hr, AMY))
            self.assertEqual(hr.emotes, [])

        self.run_bot(scenario)

    def test_numbers_still_work_the_same(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote 65")
            self.assertIn(("idle-sad", AMY.id), hr.emotes)
            await say(AMY, "!emote 999")
            self.assertIn("Emote number 999 is not in the configured list", self.last_whisper(hr, AMY))

        self.run_bot(scenario)

    def test_name_on_someone_else_needs_staff_or_vip(self):
        async def scenario(bot, hr, say):
            await say(AMY, "!emote @zed moonwalk")
            self.assertNotIn(("emote-gordonshuffle", ZED.id), hr.emotes)
            self.assertIn("staff or 100g VIP", self.last_whisper(hr, AMY))
            await say(OWNER, "!emote @zed moonwalk")
            self.assertIn(("emote-gordonshuffle", ZED.id), hr.emotes)

        self.run_bot(scenario)


if __name__ == "__main__":
    unittest.main()
