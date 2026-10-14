"""The bot's AI brain: talks to OmniRoute's OpenAI-compatible API.

Keeps a short conversation history per user, plus a list of facts the owner
taught the bot (saved to disk so the bot keeps "learning" across restarts).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)


class BrainError(Exception):
    """OmniRoute could not produce an answer."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

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


class Brain:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "auto",
        system_prompt: str = "",
        max_history: int = 12,
        timeout: float = 45.0,
        retries: int = 2,
        memory: Memory | None = None,
        fallback_models: list[str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.timeout = timeout
        self.retries = retries
        self.memory = memory
        self.fallback_models = [m for m in (fallback_models or []) if m]
        self.history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=max_history))
        self.stats = {"ok": 0, "failed": 0, "last_error": "", "last_latency": 0.0, "last_model": ""}
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _system_message(self) -> dict:
        text = self.system_prompt
        if self.memory and self.memory.facts:
            facts = "\n".join(f"- {f}" for f in self.memory.facts)
            text += f"\n\nThings you have learned (treat as true):\n{facts}"
        return {"role": "system", "content": text}

    def reset(self, user_id: str) -> None:
        self.history.pop(user_id, None)

    async def _post(self, path: str, payload: dict) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}{path}", json=payload, headers=self._headers()
        ) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise BrainError(f"HTTP {resp.status}: {body[:200]}", resp.status)
            try:
                return json.loads(body)
            except ValueError as exc:
                raise BrainError(f"Bad JSON from OmniRoute: {body[:200]}") from exc

    async def complete(self, messages: list[dict], model: str | None = None) -> str:
        """Ask the main model, then each fallback model in turn, until one answers."""
        chain = [model or self.model]
        chain += [m for m in self.fallback_models if m not in chain]
        errors = []
        for name in chain:
            try:
                answer = await self._complete_one(messages, name)
                self.stats["last_model"] = name
                return answer
            except BrainError as exc:
                errors.append(f"{name}: {exc}")
        self.stats["failed"] += 1
        self.stats["last_error"] = " | ".join(errors)
        raise BrainError(self.stats["last_error"])

    async def _complete_one(self, messages: list[dict], model: str) -> str:
        """One model, with retries and exponential backoff."""
        payload = {"model": model, "messages": messages, "stream": False}
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                data = await self._post("/chat/completions", payload)
                text = (data["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise BrainError("Empty answer from OmniRoute")
                self.stats["ok"] += 1
                self.stats["last_latency"] = time.monotonic() - started
                return text
            except (BrainError, aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as exc:
                last_exc = exc
                log.warning("OmniRoute %s attempt %d failed: %s", model, attempt + 1, exc)
                if isinstance(exc, BrainError) and exc.permanent:
                    break
                if attempt < self.retries:
                    await asyncio.sleep(2**attempt)
        raise BrainError(str(last_exc))

    async def ask(self, user_id: str, username: str, text: str) -> str:
        """Answer a user, remembering the conversation with them."""
        history = self.history[user_id]
        user_msg = {"role": "user", "content": f"{username}: {text}"}
        messages = [self._system_message(), *history, user_msg]
        answer = await self.complete(messages)
        history.append(user_msg)
        history.append({"role": "assistant", "content": answer})
        return answer

    async def list_models(self) -> list[str]:
        session = await self._get_session()
        async with session.get(f"{self.base_url}/models", headers=self._headers()) as resp:
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
