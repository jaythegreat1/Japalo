"""AI layer: "Japalo ..." addressing, typed actions, AI action plans, follow/stop.

Drives the real HighriseRoomBot through on_chat with a fake Highrise
connection, a temporary database and a scripted fake AI brain.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from highrise import User
from highrise.models import AnchorPosition, Position

from highrise_bot.ai import intents
from highrise_bot.ai.brain import BrainError
from highrise_bot.ai.config import AIConfig
from highrise_bot.ai.plan import parse_plan
from highrise_bot.bot import HighriseRoomBot
from highrise_bot.storage import Storage

AMY, OWNER, ZED = User("u1", "amy"), User("owner", "Boss"), User("u3", "zed")


class FakeHighrise:
    my_id = "bot"

    def __init__(self) -> None:
        self.chats: list[str] = []
        self.whispers: list[tuple[str, str]] = []
        self.emotes: list[tuple[str, str | None]] = []
        self.walks: list[tuple[float, float, float]] = []
        self.reacts: list[tuple[str, str]] = []

    async def chat(self, message):
        self.chats.append(message)

    async def send_whisper(self, user_id, message):
        self.whispers.append((user_id, message))

    async def send_emote(self, emote_id, target=None):
        self.emotes.append((emote_id, target))

    async def walk_to(self, destination):
        self.walks.append((destination.x, destination.y, destination.z))

    async def react(self, reaction, user_id):
        self.reacts.append((reaction, user_id))

    async def get_room_users(self):
        return SimpleNamespace(content=[
            (AMY, Position(1, 0, 1)),
            (OWNER, Position(5, 0, 5)),
            (ZED, AnchorPosition("chair", 0)),
        ])

    async def get_room_privilege(self, user_id):
        return SimpleNamespace(moderator=False)


class FakeBrain:
    def __init__(self) -> None:
        self.reply = ""
        self.fail = False
        self.asked: list[tuple[str, str]] = []
        self.model = "auto"
        self.memory = None
        self.stats = {"ok": 0, "failed": 0, "last_model": ""}

    async def ask(self, user_id, username, text, extra_system=""):
        self.asked.append((text, extra_system))
        if self.fail:
            raise BrainError("down")
        return self.reply

    def reset(self, user_id):
        pass

    def skipped_models(self):
        return []


class AITests(unittest.TestCase):
    def run_bot(self, scenario):
        async def wrapper():
            with tempfile.TemporaryDirectory() as tmp:
                bot = HighriseRoomBot()
                bot.storage = Storage(Path(tmp) / "test.db")
                await bot.storage.connect()
                bot.highrise = FakeHighrise()
                bot.room_owner_id = OWNER.id
                bot.brain = FakeBrain()
                bot.ai_config = AIConfig(user_cooldown=0)
                await bot._ai_on_start(None)
                try:
                    await scenario(bot, bot.highrise, bot.brain)
                finally:
                    for user in (AMY, OWNER, ZED):
                        await bot.emote_loops.stop(user.id)
                    bot._ai_stop_following()
                    await bot.storage.close()

        asyncio.run(wrapper())

    def test_only_messages_starting_with_name_reach_the_ai(self):
        async def scenario(bot, hr, brain):
            brain.reply = "hi!"
            for text in ("hey japalo follow me", "i like Japalo", "Japaloo hi", "!help"):
                await bot.on_chat(AMY, text)
            self.assertEqual(brain.asked, [])
            self.assertEqual(hr.walks, [])
            await bot.on_chat(AMY, "Japalo what's up?")     # apostrophe must not hit shlex
            self.assertEqual(brain.asked[0][0], "what's up?")
            self.assertEqual(hr.chats[-1], "@amy hi!")

        self.run_bot(scenario)

    def test_emote_sentence_uses_the_bots_emote_loop(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo i want to do the emote number 65")
            await asyncio.sleep(0.05)
            self.assertIn((bot.catalog.get_by_number(65).emote_id, "u1"), hr.emotes)
            self.assertTrue(bot.emote_loops.is_running("u1"))
            self.assertIn("Pouty Face", hr.whispers[-1][1])
            await bot.on_chat(AMY, "stop")                  # the bot's existing stop command
            self.assertFalse(bot.emote_loops.is_running("u1"))

        self.run_bot(scenario)

    def test_emote_by_name(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo emote lets go shopping")
            await asyncio.sleep(0.05)
            self.assertIn(("dance-shoppingcart", "u1"), hr.emotes)

        self.run_bot(scenario)

    def test_emoting_others_needs_staff_or_vip(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo make zed do 7")
            self.assertEqual(hr.emotes, [])
            self.assertIn("staff or 100g VIP", hr.chats[-1])
            await bot.on_chat(OWNER, "Japalo make zed do 7")
            await asyncio.sleep(0.05)
            self.assertIn((bot.catalog.get_by_number(7).emote_id, "u3"), hr.emotes)

        self.run_bot(scenario)

    def test_follow_moves_and_stop(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo follow me")
            self.assertEqual(hr.walks, [(2, 0, 1)])
            self.assertIn("Following amy", hr.chats[-1])
            await bot.on_user_move(AMY, Position(3, 0, 3))
            await bot.on_user_move(AMY, Position(8, 0, 2))  # only the last spot counts
            await asyncio.sleep(0.8)
            self.assertEqual(hr.walks, [(2, 0, 1), (9, 0, 2)])
            await bot.on_chat(ZED, "Japalo stop")           # not followed, not staff
            self.assertEqual(bot._ai_following, "u1")
            await bot.on_chat(AMY, "Japalo stop")
            self.assertIsNone(bot._ai_following)
            await bot.on_user_move(AMY, Position(1, 1, 1))
            await asyncio.sleep(0.8)
            self.assertEqual(len(hr.walks), 2)

        self.run_bot(scenario)

    def test_plain_stop_and_leaving_also_end_following(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo follow me")
            await bot.on_chat(AMY, "stop")
            self.assertIsNone(bot._ai_following)
            await bot.on_chat(AMY, "Japalo follow me")
            await bot.on_user_leave(AMY)
            self.assertIsNone(bot._ai_following)

        self.run_bot(scenario)

    def test_following_others_is_staff_only(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo follow boss")
            self.assertIsNone(bot._ai_following)
            await bot.on_chat(OWNER, "Japalo follow amy")
            self.assertEqual(bot._ai_following, "u1")
            await bot.on_chat(OWNER, "Japalo walk to zed")  # sitting: no floor spot
            self.assertIn("can't see a floor spot next to zed", hr.chats[-1])

        self.run_bot(scenario)

    def test_ai_plan_runs_checked_actions(self):
        async def scenario(bot, hr, brain):
            brain.reply = json.dumps({"say": "Let's dance!", "actions": [
                {"type": "emote", "emote": "Ring on It", "target": "bot"},
                {"type": "emote", "emote": 100, "target": "me"},
                {"type": "emote", "emote": 1, "target": "zed"},  # amy can't: refused
            ]})
            await bot.on_chat(AMY, "Japalo come dance with me")
            await asyncio.sleep(0.05)
            self.assertIn(("dance-singleladies", None), hr.emotes)
            self.assertIn(("dance-singleladies", "u1"), hr.emotes)
            self.assertNotIn((bot.catalog.get_by_number(1).emote_id, "u3"), hr.emotes)
            self.assertTrue(hr.chats[-1].startswith("@amy Let's dance!"))
            self.assertIn("staff or 100g VIP", hr.chats[-1])
            prompt = brain.asked[-1][1]
            self.assertIn("100:Ring on It", prompt)
            self.assertIn("amy", prompt)

        self.run_bot(scenario)

    def test_ai_down_and_ai_switched_off(self):
        async def scenario(bot, hr, brain):
            brain.fail = True
            await bot.on_chat(AMY, "Japalo tell me a joke")
            self.assertIn("taking a nap", hr.chats[-1])
            bot._settings["ai"] = "off"
            brain.fail = False
            await bot.on_chat(AMY, "Japalo tell me a joke")
            self.assertIn("switched off", hr.chats[-1])
            await bot.on_chat(AMY, "Japalo follow me")      # typed actions still work
            self.assertEqual(bot._ai_following, "u1")

        self.run_bot(scenario)

    def test_whisper_reaches_ai_privately(self):
        async def scenario(bot, hr, brain):
            brain.reply = "psst"
            await bot.on_whisper(AMY, "how are you")
            self.assertEqual(hr.whispers[-1], ("u1", "psst"))
            self.assertEqual(hr.chats, [])

        self.run_bot(scenario)

    def test_staff_only_subcommands(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo model gpt-x")
            self.assertEqual(brain.model, "auto")
            self.assertIn("Only room staff", hr.whispers[-1][1])
            await bot.on_chat(OWNER, "Japalo model gpt-x")
            self.assertEqual(brain.model, "gpt-x")

        self.run_bot(scenario)


class IntentTests(unittest.TestCase):
    def test_parse(self):
        cases = {
            "i want to do the emote number 65": {"type": "emote", "emote": "65", "target": "me"},
            "emote 65": {"type": "emote", "emote": "65", "target": "me"},
            "make zed do 7": {"type": "emote", "emote": "7", "target": "zed"},
            "emote let's go shopping on @zed": {"type": "emote", "emote": "let's go shopping", "target": "zed"},
            "follow me": {"type": "follow", "target": "me"},
            "stop following me": {"type": "stop"},
            "stop dancing": {"type": "stop"},
            "come here": {"type": "walk", "target": "me"},
            "send heart to zed": {"type": "react", "reaction": "heart", "target": "zed"},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(intents.parse(text), [expected])
        self.assertIsNone(intents.parse("what is the best dance?"))

    def test_parse_plan(self):
        self.assertEqual(parse_plan('{"say": "hi", "actions": [{"type": "stop"}]}'), ("hi", [{"type": "stop"}]))
        self.assertEqual(parse_plan('```json\n{"say": "ok", "actions": []}\n```')[0], "ok")
        self.assertEqual(parse_plan("just words"), ("just words", []))


if __name__ == "__main__":
    unittest.main()
