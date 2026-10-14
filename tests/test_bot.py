"""Offline tests: a fake OmniRoute server stands in for the real one."""

import asyncio
import json

import pytest
from aiohttp import web
from highrise import User

from bot.brain import Brain, BrainError, Memory
from bot.config import Config
from bot.main import JapaloBot, chunk_text


class FakeHighrise:
    def __init__(self):
        self.chats, self.whispers = [], []

    async def chat(self, message):
        self.chats.append(message)

    async def send_whisper(self, user_id, message):
        self.whispers.append((user_id, message))


@pytest.fixture
async def omniroute(aiohttp_server):
    state = {"requests": [], "fail": 0}

    async def chat(request):
        body = await request.json()
        state["requests"].append(body)
        if state["fail"] > 0:
            state["fail"] -= 1
            return web.Response(status=503, text="upstream down")
        last = body["messages"][-1]["content"]
        return web.json_response({"choices": [{"message": {"content": f"echo: {last}"}}]})

    async def models(request):
        return web.json_response({"data": [{"id": "auto"}, {"id": "gpt-x"}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_get("/v1/models", models)
    server = await aiohttp_server(app)
    state["url"] = str(server.make_url("/v1"))
    return state


def make_bot(tmp_path, url):
    cfg = Config(room_id="r", api_token="t", omniroute_url=url, owners={"boss"},
                 user_cooldown=0, data_dir=tmp_path)
    bot = JapaloBot(cfg)
    bot.brain.retries = 1
    bot.highrise = FakeHighrise()
    bot.bot_user_id = "bot"
    return bot


async def no_sleep(_):
    return None


def test_chunk_text_splits_on_words():
    text = "word " * 100
    chunks = chunk_text(text, 50)
    assert all(len(c) <= 50 for c in chunks)
    assert " ".join(chunks) == text.strip()
    assert chunk_text("x" * 120, 50) == ["x" * 50, "x" * 50, "x" * 20]


async def test_brain_remembers_conversation(omniroute):
    brain = Brain(omniroute["url"], system_prompt="sys")
    assert await brain.ask("u1", "amy", "hi") == "echo: amy: hi"
    await brain.ask("u1", "amy", "again")
    sent = omniroute["requests"][-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    brain.reset("u1")
    await brain.ask("u1", "amy", "new")
    assert len(omniroute["requests"][-1]["messages"]) == 2
    await brain.close()


async def test_brain_retries_then_fails(omniroute, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    brain = Brain(omniroute["url"], retries=1)
    omniroute["fail"] = 1
    assert await brain.complete([{"role": "user", "content": "x"}]) == "echo: x"
    omniroute["fail"] = 5
    with pytest.raises(BrainError):
        await brain.complete([{"role": "user", "content": "x"}])
    assert brain.stats["failed"] == 1
    await brain.close()


async def test_memory_persists_and_reaches_prompt(tmp_path, omniroute):
    mem = Memory(tmp_path / "m.json")
    mem.learn("The room owner is Jay")
    assert Memory(tmp_path / "m.json").facts == ["The room owner is Jay"]
    brain = Brain(omniroute["url"], system_prompt="sys", memory=mem)
    await brain.ask("u", "amy", "who owns this?")
    assert "The room owner is Jay" in omniroute["requests"][-1]["messages"][0]["content"]
    assert mem.forget(1) == "The room owner is Jay" and mem.forget(1) is None
    await brain.close()


async def test_bot_answers_mentions_and_ignores_other_chat(tmp_path, omniroute, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    bot = make_bot(tmp_path, omniroute["url"])
    await bot.on_chat(User("u1", "amy"), "hello everyone")
    assert bot.highrise.chats == []
    await bot.on_chat(User("u1", "amy"), "Japalo what's up?")
    assert bot.highrise.chats == ["@amy echo: amy: what's up?"]
    await bot.on_chat(User("bot", "Japalo"), "Japalo talking to myself")
    assert len(bot.highrise.chats) == 1
    await bot.on_whisper(User("u2", "bo"), "secret question")
    assert bot.highrise.whispers == [("u2", "echo: bo: secret question")]
    await bot.brain.close()


async def test_bot_survives_brain_outage(tmp_path, omniroute, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    bot = make_bot(tmp_path, omniroute["url"])
    omniroute["fail"] = 10
    await bot.on_chat(User("u1", "amy"), "japalo hi")
    assert "nap" in bot.highrise.chats[-1]
    assert bot.brain_online is False
    await bot.brain.close()


async def test_commands_and_owner_permissions(tmp_path, omniroute, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    bot = make_bot(tmp_path, omniroute["url"])
    amy, boss = User("u1", "amy"), User("u9", "Boss")
    await bot.on_chat(amy, "!ping")
    await bot.on_chat(amy, "!learn something")
    await bot.on_chat(boss, "!learn Jay built me")
    await bot.on_chat(amy, "!facts")
    await bot.on_chat(boss, "!model gpt-x")
    await bot.on_chat(boss, "!models")
    assert bot.highrise.chats == [
        "pong",
        "Only my owners can use that command.",
        "Learned it. I now know 1 fact(s).",
        "1. Jay built me",
        "Model switched to gpt-x",
        "2 models: auto, gpt-x",
    ]
    assert json.loads((tmp_path / "memory.json").read_text())["facts"] == ["Jay built me"]
    assert omniroute["requests"] == []
    await bot.brain.close()


async def test_cooldown_blocks_spam(tmp_path, omniroute, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    bot = make_bot(tmp_path, omniroute["url"])
    bot.config.user_cooldown = 60
    await bot.on_chat(User("u1", "amy"), "japalo one")
    await bot.on_chat(User("u1", "amy"), "japalo two")
    assert len(bot.highrise.chats) == 1
    await bot.brain.close()
