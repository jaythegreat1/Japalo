"""Japalo: a Highrise bot whose AI brain runs through OmniRoute."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from highrise import BaseBot, User
from highrise.models import SessionMetadata

from .brain import Brain, BrainError, Memory
from .config import Config

log = logging.getLogger(__name__)

CHAT_LIMIT = 240  # Highrise chat bubbles are short; long answers are split.
HEALTH_INTERVAL = 120


def chunk_text(text: str, limit: int = CHAT_LIMIT) -> list[str]:
    """Split text into pieces no longer than `limit`, preferring word breaks."""
    text = " ".join(text.split())
    chunks = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


class JapaloBot(BaseBot):
    def __init__(self, config: Config | None = None, brain: Brain | None = None):
        super().__init__()
        self.config = config or Config.from_env()
        self.brain = brain or Brain(
            base_url=self.config.omniroute_url,
            api_key=self.config.omniroute_key,
            model=self.config.model,
            system_prompt=self.config.system_prompt.format(name=self.config.bot_name),
            max_history=self.config.max_history,
            timeout=self.config.request_timeout,
            memory=Memory(self.config.data_dir / "memory.json"),
            fallback_models=self.config.fallback_models,
        )
        self.bot_user_id = ""
        self.last_used: dict[str, float] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.brain_online = True
        self.started_at = time.monotonic()
        self._health_task: asyncio.Task | None = None
        name = re.escape(self.config.bot_name.lower())
        self._mention = re.compile(rf"(^|[^a-z0-9_])@?{name}([^a-z0-9_]|$)")

    # ---- helpers -------------------------------------------------------

    def is_owner(self, user: User) -> bool:
        return user.username.lower() in self.config.owners

    def mentions_me(self, message: str) -> bool:
        return bool(self._mention.search(message.lower()))

    def strip_mention(self, message: str) -> str:
        name = re.escape(self.config.bot_name)
        return re.sub(rf"@?{name}[,:]?", "", message, flags=re.IGNORECASE).strip()

    def on_cooldown(self, user: User) -> bool:
        if self.is_owner(user):
            return False
        now = time.monotonic()
        if now - self.last_used.get(user.id, 0.0) < self.config.user_cooldown:
            return True
        self.last_used[user.id] = now
        return False

    async def say(self, text: str, whisper_to: str | None = None) -> None:
        for piece in chunk_text(text):
            try:
                if whisper_to:
                    await self.highrise.send_whisper(whisper_to, piece)
                else:
                    await self.highrise.chat(piece)
            except Exception:  # never let a send error kill the event handler
                log.exception("Failed to send message")
            await asyncio.sleep(0.4)

    # ---- events --------------------------------------------------------

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_user_id = session_metadata.user_id
        log.info("Connected to room as %s", self.bot_user_id)
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())
        await self.say(f"{self.config.bot_name} is online! Say my name or type {self.config.prefix}help")

    async def on_user_join(self, user: User, position=None) -> None:
        await self.say(f"Welcome {user.username}! Talk to me by saying {self.config.bot_name}.")

    async def on_chat(self, user: User, message: str) -> None:
        if user.id == self.bot_user_id:
            return
        if message.startswith(self.config.prefix):
            await self.handle_command(user, message[len(self.config.prefix) :])
        elif self.mentions_me(message):
            await self.handle_ai(user, self.strip_mention(message))

    async def on_whisper(self, user: User, message: str) -> None:
        if user.id == self.bot_user_id:
            return
        if message.startswith(self.config.prefix):
            await self.handle_command(user, message[len(self.config.prefix) :], whisper=True)
        else:
            await self.handle_ai(user, message, whisper=True)

    # ---- AI ------------------------------------------------------------

    async def handle_ai(self, user: User, text: str, whisper: bool = False) -> None:
        reply_to = user.id if whisper else None
        if not text:
            await self.say(f"Yes {user.username}? Ask me anything.", reply_to)
            return
        if self.on_cooldown(user):
            return
        lock = self.locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            return  # still answering this user's previous message
        async with lock:
            try:
                answer = await self.brain.ask(user.id, user.username, text)
                self.brain_online = True
            except BrainError as exc:
                log.error("Brain failed for %s: %s", user.username, exc)
                self.brain_online = False
                answer = "My AI brain is taking a nap right now, try again in a minute."
            if not whisper:
                answer = f"@{user.username} {answer}"
            await self.say(answer, reply_to)

    async def _health_loop(self) -> None:
        """Watch OmniRoute and announce when the brain goes down or comes back."""
        while True:
            await asyncio.sleep(HEALTH_INTERVAL)
            ok = await self.brain.healthy()
            if ok != self.brain_online:
                self.brain_online = ok
                log.warning("OmniRoute is now %s", "online" if ok else "offline")
                if ok:
                    await self.say("My AI brain is back online.")

    # ---- commands ------------------------------------------------------

    async def handle_command(self, user: User, text: str, whisper: bool = False) -> None:
        reply_to = user.id if whisper else None
        name, _, arg = text.strip().partition(" ")
        name, arg = name.lower(), arg.strip()
        reply = await self.run_command(user, name, arg)
        if reply:
            await self.say(reply, reply_to)

    async def run_command(self, user: User, name: str, arg: str) -> str | None:
        p = self.config.prefix
        owner = self.is_owner(user)
        mem = self.brain.memory

        if name == "help":
            text = (
                f"Say {self.config.bot_name} + a question, or whisper me. Commands: "
                f"{p}ping {p}status {p}reset {p}facts"
            )
            if owner:
                text += f" | owner: {p}model [name] {p}models {p}learn <fact> {p}forget <n>"
            return text
        if name == "ping":
            return "pong"
        if name == "reset":
            self.brain.reset(user.id)
            return f"{user.username}, I forgot our chat. Fresh start!"
        if name == "status":
            s = self.brain.stats
            up = int(time.monotonic() - self.started_at)
            state = "online" if self.brain_online else "OFFLINE"
            return (
                f"Brain {state} | model {self.brain.model} (last answer: {s['last_model'] or '-'}) | answers {s['ok']} ok, "
                f"{s['failed']} failed | last {s['last_latency']:.1f}s | up {up // 60}m"
            )
        if name == "facts":
            if not mem or not mem.facts:
                return "I haven't learned any facts yet."
            return " | ".join(f"{i}. {f}" for i, f in enumerate(mem.facts, 1))

        owner_commands = {"model", "models", "learn", "forget"}
        if name in owner_commands and not owner:
            return "Only my owners can use that command."
        if name == "model":
            if not arg:
                return f"Current model: {self.brain.model}"
            self.brain.model = arg
            return f"Model switched to {arg}"
        if name == "models":
            try:
                models = await self.brain.list_models()
            except Exception as exc:  # noqa: BLE001 - report any failure to the owner
                return f"Couldn't list models: {exc}"
            shown = ", ".join(models[:15])
            return f"{len(models)} models: {shown}" + (" ..." if len(models) > 15 else "")
        if name == "learn":
            if not arg or mem is None:
                return f"Usage: {p}learn <fact>"
            mem.learn(arg)
            return f"Learned it. I now know {len(mem.facts)} fact(s)."
        if name == "forget":
            if mem is None or not arg.isdigit():
                return f"Usage: {p}forget <number from {p}facts>"
            fact = mem.forget(int(arg))
            return f"Forgot: {fact}" if fact else "No fact with that number."
        return None
