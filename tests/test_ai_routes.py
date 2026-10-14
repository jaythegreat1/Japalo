"""The AI brain's route chain: Groq first, OmniRoute as fallback.

A local aiohttp server plays both providers; each test scripts how it answers.
"""

import asyncio
import os
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from highrise_bot.ai.brain import Brain, BrainError, Route
from highrise_bot.ai.config import AIConfig


class FakeProviders:
    """POST /<provider>/chat/completions; `script` maps model -> list of replies."""

    def __init__(self):
        self.calls = []
        self.script = {}

    async def handler(self, request):
        provider = request.match_info["provider"]
        body = await request.json()
        self.calls.append((provider, body["model"], {k: v for k, v in body.items() if k not in ("model", "messages", "stream")}))
        replies = self.script.get(body["model"], [])
        status, payload, headers = replies.pop(0) if replies else (200, "ok", {})
        if callable(payload):
            status, payload = payload(body)
        if status != 200:
            return web.Response(status=status, text=str(payload), headers=headers)
        return web.json_response({"choices": [{"message": {"content": f"{provider}:{body['model']}:{payload}"}}]})


class RouteTests(unittest.TestCase):
    def run_brain(self, scenario):
        async def wrapper():
            fake = FakeProviders()
            app = web.Application()
            app.router.add_post("/{provider}/chat/completions", fake.handler)
            server = TestServer(app)
            await server.start_server()
            base = str(server.make_url("")).rstrip("/")

            def route(provider, model, extra=None, min_interval=0):
                return Route(provider, f"{base}/{provider}", model, "key", min_interval, dict(extra or {}))

            try:
                await scenario(fake, route)
            finally:
                await server.close()

        asyncio.run(wrapper())

    def test_groq_answers_first(self):
        async def scenario(fake, route):
            brain = Brain(routes=[route("groq", "big"), route("omniroute", "ddg")])
            self.assertEqual(await brain.complete([{"role": "user", "content": "hi"}]), "groq:big:ok")
            self.assertEqual(brain.stats["last_model"], "groq:big")
            await brain.close()

        self.run_brain(scenario)

    def test_rate_limit_moves_on_at_once_and_cools_the_route(self):
        async def scenario(fake, route):
            fake.script["big"] = [(429, "slow down", {"retry-after": "30"})]
            brain = Brain(routes=[route("groq", "big"), route("groq", "small"), route("omniroute", "ddg")])
            with patch("asyncio.sleep") as sleep:
                answer = await brain.complete([{"role": "user", "content": "hi"}])
            self.assertEqual(answer, "groq:small:ok")
            sleep.assert_not_called()  # no waiting while another route can answer
            self.assertEqual(brain.cooling_models(), ["groq:big"])
            await brain.complete([{"role": "user", "content": "again"}])
            self.assertEqual([m for _, m, _ in fake.calls], ["big", "small", "small"])
            await brain.close()

        self.run_brain(scenario)

    def test_bad_groq_key_falls_back_to_omniroute_and_rests_groq(self):
        async def scenario(fake, route):
            fake.script["big"] = [(401, "invalid api key", {})]
            brain = Brain(routes=[route("groq", "big"), route("omniroute", "ddg")])
            self.assertEqual(await brain.complete([{"role": "user", "content": "hi"}]), "omniroute:ddg:ok")
            self.assertEqual(brain.skipped_models(), ["groq:big"])
            await brain.close()

        self.run_brain(scenario)

    def test_rejected_optional_field_is_dropped(self):
        async def scenario(fake, route):
            def picky(body):
                return (400, "unknown field reasoning_effort") if "reasoning_effort" in body else (200, "ok")

            fake.script["big"] = [(0, picky, {}), (0, picky, {})]
            groq = route("groq", "big", extra={"reasoning_effort": "low"})
            brain = Brain(routes=[groq])
            self.assertEqual(await brain.complete([{"role": "user", "content": "hi"}]), "groq:big:ok")
            self.assertEqual(fake.calls[0][2], {"reasoning_effort": "low"})
            self.assertEqual(fake.calls[1][2], {})
            self.assertEqual(groq.extra, {})
            await brain.close()

        self.run_brain(scenario)

    def test_everything_down_raises(self):
        async def scenario(fake, route):
            fake.script["big"] = [(401, "bad key", {})]
            fake.script["ddg"] = [(403, "blocked", {})]
            brain = Brain(routes=[route("groq", "big"), route("omniroute", "ddg")])
            with self.assertRaises(BrainError):
                await brain.complete([{"role": "user", "content": "hi"}])
            self.assertEqual(brain.stats["failed"], 1)
            await brain.close()

        self.run_brain(scenario)


class ConfigTests(unittest.TestCase):
    def labels(self, env):
        with patch.dict(os.environ, env, clear=True):
            return [r.label for r in AIConfig.from_env().routes()]

    def test_route_order(self):
        self.assertEqual(self.labels({}), ["omniroute:auto"])
        self.assertEqual(
            self.labels({"GROQ_API_KEY": "k"}),
            ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"],
        )
        self.assertEqual(
            self.labels({
                "GROQ_API_KEY": "k",
                "OMNIROUTE_URL": "http://x/v1",
                "OMNIROUTE_MODEL": "ddgw/gpt-5.4-mini",
                "OMNIROUTE_FALLBACK_MODELS": "ddgw/gpt-5-mini",
            }),
            ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b",
             "omniroute:ddgw/gpt-5.4-mini", "omniroute:ddgw/gpt-5-mini"],
        )

    def test_groq_gets_low_reasoning_effort(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "k"}, clear=True):
            routes = AIConfig.from_env().routes()
        self.assertEqual(routes[0].extra, {"reasoning_effort": "low"})
        self.assertEqual(routes[0].base_url, "https://api.groq.com/openai/v1")


if __name__ == "__main__":
    unittest.main()
