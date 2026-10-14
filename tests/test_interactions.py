"""!punch / !slap / !explode, driven through on_chat like a real room."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from highrise_bot.bot import HighriseRoomBot
from highrise_bot.constants import INTERACTIONS_PATH
from highrise_bot.interactions import load_interactions
from highrise_bot.storage import Storage
from tests.test_ai import AMY, OWNER, ZED, FakeBrain, FakeHighrise

FALLS = {"emote-fail1", "emote-death2", "emote-deathdrop", "emote-fail2", "emote-fail3"}


class RefusingHighrise(FakeHighrise):
    """Highrise refuses some emote ids, like an emote a player doesn't own."""

    def __init__(self, refused=()):
        super().__init__()
        self.refused = set(refused)

    async def send_emote(self, emote_id, target=None):
        if emote_id in self.refused:
            raise RuntimeError("emote is not free or owned by target user")
        await super().send_emote(emote_id, target)


class InteractionTests(unittest.TestCase):
    def run_bot(self, scenario, refused=()):
        async def wrapper():
            with tempfile.TemporaryDirectory() as tmp:
                bot = HighriseRoomBot()
                bot.storage = Storage(Path(tmp) / "test.db")
                await bot.storage.connect()
                bot.highrise = RefusingHighrise(refused)
                bot.room_owner_id = OWNER.id
                bot.brain = FakeBrain()
                try:
                    await scenario(bot, bot.highrise)
                finally:
                    await bot.storage.close()

        asyncio.run(wrapper())

    def test_punch_speaker_punches_target_falls(self):
        async def scenario(bot, hr):
            await bot.on_chat(AMY, "!punch @zed")
            self.assertEqual(hr.emotes[0], ("emoji-punch", "u1"))
            self.assertEqual(len(hr.emotes), 2)
            fall, target = hr.emotes[1]
            self.assertIn(fall, FALLS)
            self.assertEqual(target, "u3")
            self.assertIn("amy", hr.chats[-1])
            self.assertIn("zed", hr.chats[-1])

        self.run_bot(scenario)

    def test_slap(self):
        async def scenario(bot, hr):
            await bot.on_chat(AMY, "!slap zed")
            self.assertEqual(hr.emotes[0], ("emote-slap", "u1"))
            self.assertIn(hr.emotes[1][0], FALLS)
            self.assertEqual(hr.emotes[1][1], "u3")

        self.run_bot(scenario)

    def test_explode_only_target_does_boo(self):
        async def scenario(bot, hr):
            await bot.on_chat(AMY, "!explode @zed")
            self.assertEqual(hr.emotes, [("emote-boo", "u3")])  # speaker does nothing
            self.assertIn("zed", hr.chats[-1])

        self.run_bot(scenario)

    def test_refused_emote_falls_back_to_next(self):
        async def scenario(bot, hr):
            await bot.on_chat(AMY, "!punch @zed")
            self.assertEqual(hr.emotes[0], ("emote-superpunch", "u1"))
            self.assertIn(hr.emotes[1][0], FALLS)

        self.run_bot(scenario, refused={"emoji-punch"})

    def test_everything_refused_tells_the_speaker(self):
        async def scenario(bot, hr):
            await bot.on_chat(AMY, "!explode @zed")
            self.assertEqual(hr.emotes, [])
            self.assertEqual(hr.chats, [])
            self.assertIn("refused", hr.whispers[-1][1])

        self.run_bot(scenario, refused={"emote-boo"})

    def test_bad_targets_and_cooldown(self):
        async def scenario(bot, hr):
            async def say(text):
                bot._command_cooldowns.clear()  # skip the 1s !command cooldown only
                await bot.on_chat(AMY, text)

            await say("!punch")
            self.assertIn("Use !punch @PlayerName", hr.whispers[-1][1])
            await say("!punch @nobody")
            self.assertIn("not in the room", hr.whispers[-1][1])
            await say("!punch @amy")
            self.assertIn("can't punch yourself", hr.whispers[-1][1])
            self.assertEqual(hr.emotes, [])
            await say("!slap @zed")
            await say("!slap @zed")  # still inside the 8s interaction cooldown
            self.assertEqual(len(hr.emotes), 2)
            self.assertIn("wait a few seconds", hr.whispers[-1][1])

        self.run_bot(scenario)

    def test_config_ids_are_in_the_emote_catalog(self):
        bot = HighriseRoomBot()
        known = bot.catalog.known_ids()
        self.assertEqual(load_interactions(INTERACTIONS_PATH).all_emote_ids() - known, set())


if __name__ == "__main__":
    unittest.main()
