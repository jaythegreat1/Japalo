"""Japalo's AI brain: OpenAI-compatible chat APIs tried in order (Groq, then OmniRoute).

Each "route" is one provider + model. A question goes to the first route that is
not resting or cooling down; if it fails, the next route gets it. Keeps a short
conversation history per user, plus a list of facts the owner taught the bot
(saved to disk so the bot keeps "learning" across restarts).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)


class BrainError(Exception):
    """No route could produce an answer."""

    resting = False

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def permanent(self) -> bool:
        """Errors that retrying the same model will not fix (bad key, blocked, no such model)."""
        return self.status is not None and 400 <= self.status < 500 and self.status not in (408, 429)


class Memory:
    """Facts the bot has been taught, persisted as JSON."""

    def __init__(self, path: Path, limit: int = 50):
        self.path = path
        self.limit = limit
        self.facts: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [str(f) for f in data.get("facts", [])][-self.limit :]
        except FileNotFoundError:
            self.facts = []
        except (OSError, ValueError) as exc:
            log.warning("Could not read memory file %s: %s", self.path, exc)
            self.facts = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"facts": self.facts}, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def learn(self, fact: str) -> None:
        fact = fact.strip()
        if fact and fact not in self.facts:
            self.facts.append(fact)
            self.facts = self.facts[-self.limit :]
            self._save()

    def forget(self, index: int) -> str | None:
        """Remove the fact at 1-based index; returns it, or None if out of range."""
        if 1 <= index <= len(self.facts):
            fact = self.facts.pop(index - 1)
            self._save()
            return fact
        return None


@dataclass
class Route:
    """One provider + model to ask, e.g. Groq's openai/gpt-oss-120b."""

    provider: str
    base_url: str
    model: str
    api_key: str = ""
    min_interval: float = 4.0  # seconds between requests to this provider
    extra: dict = field(default_factory=dict)  # provider-specific request fields

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class Brain:
    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "auto",
        system_prompt: str = "",
        max_history: int = 12,
        timeout: float = 45.0,
        retries: int = 2,
        memory: Memory | None = None,
        fallback_models: list[str] | None = None,
        min_interval: float = 4.0,
        rate_limit_wait: float = 15.0,
        skip_after_failure: float = 600.0,
        routes: list[Route] | None = None,
    ):
        if routes is None:  # single provider: model + fallback models on one base URL
            names = [model] + [m for m in (fallback_models or []) if m and m != model]
            routes = [
                Route("omniroute", base_url.rstrip("/"), name, api_key, min_interval)
                for name in names
            ]
        if not routes:
            raise ValueError("Brain needs at least one route")
        self.routes = routes
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.timeout = timeout
        self.retries = retries
        self.memory = memory
        self.rate_limit_wait = rate_limit_wait
        self.skip_after_failure = skip_after_failure
        # Free tiers rate-limit bursts, so each provider's requests are spaced
        # at least its route's min_interval apart.
        self._pace_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_call: dict[str, float] = defaultdict(float)
        self._skip_until: dict[str, float] = {}  # permanent failure: rest the route
        self._cool_until: dict[str, float] = {}  # rate limited: cool down the route
        self.history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=max_history))
        self.stats = {"ok": 0, "failed": 0, "last_error": "", "last_latency": 0.0, "last_model": ""}
        self._session: aiohttp.ClientSession | None = None

    @property
    def model(self) -> str:
        """The first (preferred) route's model."""
        return self.routes[0].model

    @model.setter
    def model(self, value: str) -> None:
        self.routes[0].model = value

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _headers(route: Route) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if route.api_key:
            headers["Authorization"] = f"Bearer {route.api_key}"
        return headers

    def _system_message(self) -> dict:
        text = self.system_prompt
        if self.memory and self.memory.facts:
            facts = "\n".join(f"- {f}" for f in self.memory.facts)
            text += f"\n\nThings you have learned (treat as true):\n{facts}"
        return {"role": "system", "content": text}

    def reset(self, user_id: str) -> None:
        self.history.pop(user_id, None)

    async def _post(self, route: Route, payload: dict) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{route.base_url}/chat/completions", json=payload, headers=self._headers(route)
        ) as resp:
            body = await resp.text()
            if resp.status >= 400:
                retry_after = None
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    pass
                raise BrainError(f"HTTP {resp.status}: {body[:200]}", resp.status, retry_after)
            try:
                return json.loads(body)
            except ValueError as exc:
                raise BrainError(f"Bad JSON from {route.provider}: {body[:200]}") from exc

    async def _pace(self, route: Route, may_skip: bool) -> None:
        """Wait until the route's provider allows another request.

        If the route started resting while this request waited in line, give up
        the turn instead of spending it on a route that is known to be dead.
        """
        async with self._pace_locks[route.provider]:
            if may_skip and route.label in self.skipped_models():
                exc = BrainError(f"{route.label} is resting after a permanent failure")
                exc.resting = True
                raise exc
            wait = route.min_interval - (time.monotonic() - self._last_call[route.provider])
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[route.provider] = time.monotonic()

    def skipped_models(self) -> list[str]:
        """Routes resting after a permanent failure (bad key, blocked, unknown model)."""
        now = time.monotonic()
        return [label for label, until in self._skip_until.items() if until > now]

    def cooling_models(self) -> list[str]:
        """Routes cooling down after a rate limit."""
        now = time.monotonic()
        return [label for label, until in self._cool_until.items() if until > now]

    async def complete(self, messages: list[dict], model: str | None = None) -> str:
        """Ask each route in order until one answers.

        A route that fails permanently rests for `skip_after_failure` seconds and
        a rate-limited one cools down for the provider's Retry-After, so every
        message doesn't pay for them again. If every route is resting or cooling,
        all of them are tried anyway.
        """
        routes = list(self.routes)
        if model:  # explicit model: ask it first, on the first route's provider
            first = routes[0]
            routes.insert(0, Route(first.provider, first.base_url, model, first.api_key,
                                   first.min_interval, dict(first.extra)))
        unavailable = set(self.skipped_models()) | set(self.cooling_models())
        live = [r for r in routes if r.label not in unavailable] or routes
        errors = []
        for i, route in enumerate(live):
            try:
                answer = await self._complete_one(messages, route, may_skip=i < len(live) - 1)
                self.stats["last_model"] = route.label
                self._skip_until.pop(route.label, None)
                return answer
            except BrainError as exc:
                if exc.resting:
                    continue
                errors.append(f"{route.label}: {exc}")
                if exc.permanent and len(live) > 1:
                    self._skip_until[route.label] = time.monotonic() + self.skip_after_failure
        self.stats["failed"] += 1
        self.stats["last_error"] = " | ".join(errors)
        raise BrainError(self.stats["last_error"])

    async def _complete_one(self, messages: list[dict], route: Route, may_skip: bool = False) -> str:
        """One route, with retries and backoff.

        A rate limit (429) with other routes still to try cools this route down
        and moves on at once; on the last route it waits and retries instead.
        """
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            payload = {"model": route.model, "messages": messages, "stream": False, **route.extra}
            try:
                await self._pace(route, may_skip)
                started = time.monotonic()
                data = await self._post(route, payload)
                text = (data["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise BrainError(f"Empty answer from {route.label}")
                self.stats["ok"] += 1
                self.stats["last_latency"] = time.monotonic() - started
                return text
            except (BrainError, aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as exc:
                if isinstance(exc, BrainError) and exc.resting:
                    raise
                last_exc = exc
                log.warning("AI %s attempt %d failed: %s", route.label, attempt + 1, exc)
                if isinstance(exc, BrainError) and exc.status == 400 and route.extra:
                    # The provider rejected an optional field: drop them and retry.
                    log.warning("AI %s: dropping optional fields %s", route.label, list(route.extra))
                    route.extra = {}
                    continue
                if isinstance(exc, BrainError) and exc.permanent:
                    raise exc
                rate_limited = isinstance(exc, BrainError) and exc.status == 429
                if rate_limited:
                    wait = exc.retry_after or self.rate_limit_wait
                    self._cool_until[route.label] = time.monotonic() + wait
                    if may_skip:
                        raise exc  # let the next route answer now
                if attempt < self.retries:
                    if rate_limited:
                        await asyncio.sleep((exc.retry_after or self.rate_limit_wait) * (attempt + 1))
                    else:
                        await asyncio.sleep(2**attempt)
        status = last_exc.status if isinstance(last_exc, BrainError) else None
        raise BrainError(str(last_exc), status)

    async def ask(self, user_id: str, username: str, text: str, extra_system: str = "") -> str:
        """Answer a user, remembering the conversation with them."""
        history = self.history[user_id]
        user_msg = {"role": "user", "content": f"{username}: {text}"}
        system = self._system_message()
        if extra_system:
            system = {"role": "system", "content": f"{system['content']}\n\n{extra_system}"}
        messages = [system, *history, user_msg]
        answer = await self.complete(messages)
        history.append(user_msg)
        history.append({"role": "assistant", "content": answer})
        return answer

    async def list_models(self) -> list[str]:
        """Models offered by the first route's provider."""
        route = self.routes[0]
        session = await self._get_session()
        async with session.get(f"{route.base_url}/models", headers=self._headers(route)) as resp:
            if resp.status >= 400:
                raise BrainError(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    async def healthy(self) -> bool:
        try:
            await self.list_models()
            return True
        except (BrainError, aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return False
