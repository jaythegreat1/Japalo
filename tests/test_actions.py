"""Room actions: Japalo-prefix only, number emotes, follow/stop, AI action plans."""

import asyncio
import json

import pytest
from aiohttp import web
from highrise import User
from highrise.models import AnchorPosition, Position

from bot import intents
from bot.config import Config
from bot.emotes import EmoteBook
from bot.main import JapaloBot, parse_plan

AMY, BOSS, ZED = User("u1", "amy"), User("u9", "Boss"), User("u3", "zed")


class FakeHighrise:
    def __init__(self):
        self.chats, self.whispers, self.emotes, self.walks, self.reacts = [], [], [], [], []

    async def chat(self, m):
        self.chats.append(m)

    async def send_whisper(self, uid, m):
        self.whispers.append((uid, m))

    async def send_emote(self, emote_id, target=None):
        self.emotes.append((emote_id, target))

    async def walk_to(self, dest):
        self.walks.append((dest.x, dest.y, dest.z))

    async def react(self, reaction, uid):
        self.reacts.append((reaction, uid))

    async def get_room_users(self):
        class R:
            content = [(AMY, Position(1, 0, 1)), (BOSS, Position(5, 0, 5)), (ZED, AnchorPosition("chair", 0))]
        return R()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    real = asyncio.sleep

    async def fast(seconds, *a, **kw):
        await real(0)

    monkeypatch.setattr(asyncio, "sleep", fast)


@pytest.fixture
async def ai(aiohttp_server):
    """Fake OmniRoute whose next answer the test sets."""
    state = {"reply": "", "requests": []}

    async def chat(request):
        body = await request.json()
        state["requests"].append(body)
        return web.json_response({"choices": [{"message": {"content": state["reply"]}}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    state["url"] = str(server.make_url("/v1"))
    return state


async def make_bot(tmp_path, url="http://127.0.0.1:9/v1"):
    cfg = Config(room_id="r", api_token="t", omniroute_url=url, owners={"boss"}, user_cooldown=0,
                 data_dir=tmp_path, fallback_models=[], min_interval=0)
    bot = JapaloBot(cfg)
    bot.highrise = FakeHighrise()
    bot.bot_user_id = bot.actor.bot_user_id = "bot"
    await bot.actor.load_room()
    return bot


def test_emote_book_lookup():
    book = EmoteBook.load()
    assert book.find(19).id == "dance-macarena"
    assert book.find("macarena").number == 19
    assert book.find("#19") == book.find("dance-macarena")
    assert book.find(0) is None and book.find(9999) is None


@pytest.mark.parametrize("text,expected", [
    ("i want to do the emote number 65", {"type": "emote", "emote": "65", "target": "me"}),
    ("emote 65", {"type": "emote", "emote": "65", "target": "me"}),
    ("do 12 on @zed", {"type": "emote", "emote": "12", "target": "zed"}),
    ("make zed do 7", {"type": "emote", "emote": "7", "target": "zed"}),
    ("emote macarena", {"type": "emote", "emote": "macarena", "target": "me"}),
    ("follow me", {"type": "follow", "target": "me"}),
    ("Follow @Amy!", {"type": "follow", "target": "amy"}),
    ("stop", {"type": "stop"}),
    ("stop following me", {"type": "stop"}),
    ("come here", {"type": "walk", "target": "me"}),
    ("go to boss", {"type": "walk", "target": "boss"}),
    ("send heart to zed", {"type": "react", "reaction": "heart", "target": "zed"}),
])
def test_intents(text, expected):
    assert intents.parse(text) == [expected]


def test_questions_go_to_the_ai():
    assert intents.parse("what is the best dance?") is None
    assert intents.parse("tell me a joke") is None


def test_parse_plan():
    assert parse_plan('{"say": "hi", "actions": [{"type": "emote", "emote": 6}]}') == (
        "hi", [{"type": "emote", "emote": 6}])
    assert parse_plan('Sure! ```json\n{"say": "ok", "actions": []}\n```')[0] == "ok"
    assert parse_plan("just words") == ("just words", [])
    many = json.dumps({"say": "x", "actions": [{"type": "stop"}] * 10})
    assert len(parse_plan(many)[1]) == 3


async def test_only_replies_when_message_starts_with_name(tmp_path):
    bot = await make_bot(tmp_path)
    hr = bot.highrise
    await bot.on_chat(AMY, "hey japalo follow me")      # name not first: ignored
    await bot.on_chat(AMY, "i like Japalo")
    await bot.on_chat(AMY, "Japaloo follow me")          # different word
    assert hr.chats == [] and hr.walks == []
    await bot.on_chat(AMY, "Japalo, follow me")
    assert hr.walks == [(2, 0, 1)] and "Following amy" in hr.chats[-1]
    await bot.brain.close()


async def test_number_message_emotes_the_speaker(tmp_path):
    bot = await make_bot(tmp_path)
    await bot.on_chat(AMY, "65")
    assert bot.highrise.emotes == [(bot.actor.emotes.find(65).id, "u1")]
    assert bot.highrise.chats == []                      # silent, like classic emote bots
    await bot.on_chat(AMY, "999")
    assert "don't know emote 999" in bot.highrise.chats[-1]
    await bot.brain.close()


async def test_japalo_emote_sentence(tmp_path):
    bot = await make_bot(tmp_path)
    await bot.on_chat(AMY, "Japalo i want to do the emote number 65")
    assert bot.highrise.emotes == [(bot.actor.emotes.find(65).id, "u1")]
    await bot.brain.close()


async def test_follow_moves_and_stop(tmp_path):
    bot = await make_bot(tmp_path)
    hr = bot.highrise
    await bot.on_chat(AMY, "Japalo follow me")
    bot.actor.moved(AMY, Position(3, 0, 3))
    bot.actor.moved(AMY, Position(8, 0, 2))              # quick second move: only the last counts
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert hr.walks == [(2, 0, 1), (9, 0, 2)]
    bot.actor.moved(BOSS, Position(0, 0, 0))             # other players don't drag the bot
    await bot.on_chat(ZED, "Japalo stop")                # not the followed player, not owner
    assert "Only the person I'm following" in hr.chats[-1]
    await bot.on_chat(AMY, "Japalo stop")
    assert bot.actor.following is None
    bot.actor.moved(AMY, Position(1, 1, 1))
    await asyncio.sleep(0)
    assert len(hr.walks) == 2
    await bot.brain.close()


async def test_follow_stops_when_player_leaves(tmp_path):
    bot = await make_bot(tmp_path)
    await bot.on_chat(AMY, "Japalo follow me")
    await bot.on_user_leave(AMY)
    assert bot.actor.following is None
    await bot.brain.close()


async def test_permissions(tmp_path):
    bot = await make_bot(tmp_path)
    hr = bot.highrise
    await bot.on_chat(AMY, "Japalo make zed do 7")
    assert hr.emotes == [] and "only do that for you or me" in hr.chats[-1]
    await bot.on_chat(BOSS, "Japalo make zed do 7")
    assert hr.emotes == [(bot.actor.emotes.find(7).id, "u3")]
    await bot.on_chat(BOSS, "Japalo follow amy")
    assert bot.actor.following == "u1"
    await bot.on_chat(BOSS, "Japalo stop")               # owners can always stop
    assert bot.actor.following is None
    await bot.on_chat(BOSS, "Japalo walk to zed")         # zed is sitting: no floor spot
    assert "can't see where zed" in hr.chats[-1]
    await bot.brain.close()


async def test_ai_plan_runs_actions(tmp_path, ai):
    bot = await make_bot(tmp_path, ai["url"])
    hr = bot.highrise
    ai["reply"] = json.dumps({"say": "Let's dance!", "actions": [
        {"type": "emote", "emote": "macarena", "target": "bot"},
        {"type": "emote", "emote": 19, "target": "me"},
        {"type": "emote", "emote": 1, "target": "zed"},   # not allowed for amy: refused
    ]})
    await bot.on_chat(AMY, "Japalo come dance with me")
    assert hr.emotes == [("dance-macarena", None), ("dance-macarena", "u1")]
    assert hr.chats[-1].startswith("@amy Let's dance!") and "only do that for you or me" in hr.chats[-1]
    system = ai["requests"][-1]["messages"][0]["content"]
    assert "19:macarena" in system and "amy" in system
    await bot.brain.close()


async def test_ai_plain_text_still_works(tmp_path, ai):
    bot = await make_bot(tmp_path, ai["url"])
    ai["reply"] = "Paris is the capital of France."
    await bot.on_chat(AMY, "Japalo what is the capital of France?")
    assert bot.highrise.chats == ["@amy Paris is the capital of France."]
    assert bot.highrise.emotes == []
    await bot.brain.close()


async def test_chat_commands_without_prefix(tmp_path):
    bot = await make_bot(tmp_path)
    await bot.on_chat(AMY, "Japalo emotes")
    assert bot.highrise.chats[-1].startswith("1.kiss 2.no")
    await bot.on_chat(AMY, "Japalo ping")
    assert bot.highrise.chats[-1] == "pong"
    await bot.brain.close()
