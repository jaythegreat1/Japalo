"""AI command builder: validate, design conversation, test, save, run, reload."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from highrise_bot import custom_commands as cc
from highrise_bot.ai.designer import parse_design
from highrise_bot.bot import HighriseRoomBot
from highrise_bot.storage import Storage
from tests.test_ai import AMY, OWNER, ZED, FakeBrain, FakeHighrise

HUG = {
    "name": "hug",
    "description": "Hug someone",
    "needs_target": True,
    "cooldown_seconds": 0,
    "steps": [
        {"do": "emote", "who": "speaker", "emote": "Hug Yourself"},
        {"do": "wait", "seconds": 0.1},
        {"do": "emote", "who": "target", "emote": ["Bashful", 165]},
        {"do": "say", "text": "{speaker} hugged {target}! 💕"},
    ],
}


def ready(command, ideas=()):
    return json.dumps({"status": "ready", "command": command, "ideas": list(ideas)})


class ScriptedBrain(FakeBrain):
    """FakeBrain whose complete() returns queued designer replies."""

    def __init__(self, replies=()):
        super().__init__()
        self.replies = list(replies)
        self.completions = []

    async def complete(self, messages, model=None, overrides=None):
        self.completions.append(messages)
        return self.replies.pop(0)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.catalog = HighriseRoomBot().catalog
        self.reserved = HighriseRoomBot()._reserved_command_names()

    def test_good_command_resolves_emotes_to_ids(self):
        spec, errors = cc.validate(HUG, self.catalog, self.reserved)
        self.assertEqual(errors, [])
        self.assertEqual(spec["steps"][0]["emote"], ["emote-hugyourself"])
        self.assertEqual(len(spec["steps"][2]["emote"]), 2)
        self.assertIn("Hug Yourself", cc.describe(spec, self.catalog))

    def test_rejections(self):
        bad = {
            "name": "punch",  # built-in
            "needs_target": False,
            "steps": [
                {"do": "emote", "who": "target", "emote": "not a real emote"},
                {"do": "say", "text": "{target} {password}"},
                {"do": "wait", "seconds": 5}, {"do": "wait", "seconds": 5}, {"do": "wait", "seconds": 5},
                {"do": "explode_server"},
            ],
        }
        spec, errors = cc.validate(bad, self.catalog, self.reserved)
        self.assertIsNone(spec)
        text = "\n".join(errors)
        for expected in ("built-in", "needs_target is false", "no emote matches", "{password}",
                         "waits add up to 15s", "'do' must be one of"):
            self.assertIn(expected, text)

    def test_fill_only_replaces_known_placeholders(self):
        self.assertEqual(cc.fill("{speaker}->{target} {0} {__class__}", "amy", "zed", "Japalo"),
                         "amy->zed {0} {__class__}")

    def test_parse_design_handles_plain_text(self):
        self.assertEqual(parse_design("what emote?")["status"], "question")
        self.assertEqual(parse_design('```json\n{"status": "ready", "command": {}}\n```')["status"], "ready")
        bare = parse_design(json.dumps(HUG))
        self.assertEqual((bare["status"], bare["command"]["name"]), ("ready", "hug"))


class BuilderFlowTests(unittest.TestCase):
    def run_bot(self, scenario, replies=(), db_dir=None):
        async def wrapper():
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(db_dir or tmp)
                bot = HighriseRoomBot()
                bot.storage = Storage(folder / "test.db")
                await bot.storage.connect()
                await bot._load_custom_commands()
                bot.highrise = FakeHighrise()
                bot.room_owner_id = OWNER.id
                bot.brain = ScriptedBrain(replies)
                try:
                    await scenario(bot, bot.highrise, bot.brain)
                finally:
                    await bot.storage.close()

        asyncio.run(wrapper())

    def whispers(self, hr, user):
        return [text for uid, text in hr.whispers if uid == user.id]

    def test_questions_then_draft_then_test_then_save_then_use(self):
        question = json.dumps({"status": "question", "questions": ["Which emote should they do?"],
                               "ideas": ["Add a heart reaction"]})

        async def scenario(bot, hr, brain):
            await bot.on_chat(OWNER, "Japalo make a command !hug where I hug them and they blush")
            last = self.whispers(hr, OWNER)[-1]
            self.assertIn("Which emote should they do?", last)
            self.assertIn("Add a heart reaction", last)

            await bot.on_chat(OWNER, "Japalo they should do Bashful")
            draft = self.whispers(hr, OWNER)[-1]
            self.assertIn("!hug @name", draft)
            self.assertIn("Hug Yourself", draft)
            # the designer saw the whole conversation
            self.assertEqual([m["role"] for m in brain.completions[-1]], ["system", "user", "assistant", "user"])

            await bot.on_chat(OWNER, "Japalo save")
            self.assertIn("Test it first", self.whispers(hr, OWNER)[-1])
            self.assertNotIn("hug", bot.custom_commands)

            await bot.on_chat(OWNER, "Japalo test @zed")
            self.assertIn(("emote-hugyourself", OWNER.id), hr.emotes)
            self.assertEqual(hr.emotes[-1][1], ZED.id)
            self.assertIn("Test passed", self.whispers(hr, OWNER)[-1])

            await bot.on_chat(OWNER, "Japalo save")
            self.assertIn("hug", bot.custom_commands)
            self.assertIn("New command: !hug @name", hr.chats[-1])

            hr.emotes.clear()
            bot._command_cooldowns.clear()
            await bot.on_chat(AMY, "!hug @zed")  # anyone can use it
            self.assertEqual(hr.emotes[0], ("emote-hugyourself", AMY.id))
            self.assertEqual(hr.chats[-1], "amy hugged zed! 💕")

        self.run_bot(scenario, replies=[question, ready(HUG)])

    def test_ai_repairs_its_own_invalid_draft(self):
        broken = dict(HUG, steps=[{"do": "emote", "who": "speaker", "emote": "Mega Hug 3000"}])

        async def scenario(bot, hr, brain):
            await bot.on_chat(OWNER, "Japalo create a command !hug")
            self.assertEqual(len(brain.completions), 2)
            repair_request = brain.completions[1][-1]["content"]
            self.assertIn("no emote matches 'Mega Hug 3000'", repair_request)
            self.assertIn("Draft:", self.whispers(hr, OWNER)[-1])

        self.run_bot(scenario, replies=[ready(broken), ready(HUG)])

    def test_malformed_reply_is_sent_back_for_repair(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(OWNER, "Japalo make a command !hug")
            self.assertEqual(len(brain.completions), 2)
            self.assertIn("ONE JSON object", brain.completions[1][-1]["content"])
            self.assertIn("Draft:", self.whispers(hr, OWNER)[-1])

        self.run_bot(scenario, replies=['{"status": "updated", "note": "done"}', ready(HUG)])

    def test_gives_up_after_repairs_and_explains(self):
        broken = dict(HUG, name="punch")

        async def scenario(bot, hr, brain):
            await bot.on_chat(OWNER, "Japalo make a command")
            self.assertIn("couldn't build a valid command", self.whispers(hr, OWNER)[-1])
            self.assertIn("built-in", self.whispers(hr, OWNER)[-1])

        self.run_bot(scenario, replies=[ready(broken)] * 3)

    def test_only_staff_can_build(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(AMY, "Japalo make a command !hug")
            self.assertIn("Only room staff", self.whispers(hr, AMY)[-1])
            self.assertEqual(brain.completions, [])

        self.run_bot(scenario)

    def test_saved_commands_survive_restart_and_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            async def build(bot, hr, brain):
                await bot.on_chat(OWNER, "Japalo make a command !hug")
                await bot.on_chat(OWNER, "Japalo test @zed")
                await bot.on_chat(OWNER, "Japalo save")

            async def after_restart(bot, hr, brain):
                self.assertIn("hug", bot.custom_commands)
                await bot.on_chat(AMY, "!customcommands")
                self.assertIn("!hug @name — Hug someone", self.whispers(hr, AMY)[-1])
                bot._command_cooldowns.clear()
                await bot.on_chat(AMY, "!delcommand hug")
                self.assertIn("Only room staff", self.whispers(hr, AMY)[-1])
                await bot.on_chat(OWNER, "!delcommand hug")
                self.assertNotIn("hug", bot.custom_commands)
                self.assertEqual(await bot.storage.list_custom_commands(), [])

            self.run_bot(build, replies=[ready(HUG)], db_dir=folder)
            self.run_bot(after_restart, db_dir=folder)

    def test_new_command_cannot_take_an_existing_custom_name_but_edit_can(self):
        async def scenario(bot, hr, brain):
            await bot.on_chat(OWNER, "Japalo make a command !hug")
            await bot.on_chat(OWNER, "Japalo test")
            await bot.on_chat(OWNER, "Japalo save")
            await bot.on_chat(OWNER, "Japalo make another command !hug")  # clashes with saved !hug
            self.assertIn("couldn't build a valid command", self.whispers(hr, OWNER)[-1])
            await bot.on_chat(OWNER, "Japalo cancel")
            await bot.on_chat(OWNER, "Japalo edit command !hug so the bot waves too")
            self.assertIn("Current draft", brain.completions[-1][0]["content"])
            self.assertIn("Draft:", self.whispers(hr, OWNER)[-1])

        self.run_bot(scenario, replies=[ready(HUG), ready(HUG), ready(HUG), ready(HUG), ready(HUG)])


if __name__ == "__main__":
    unittest.main()
