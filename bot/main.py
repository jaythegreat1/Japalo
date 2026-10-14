"""Japalo: a Highrise bot whose AI brain runs through OmniRoute."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from highrise import BaseBot, User
from highrise.models import AnchorPosition, Position, SessionMetadata

from . import intents
from .actions import Actor
from .brain import Brain, BrainError, Memory
from .config import Config
from .emotes import EmoteBook

log = logging.getLogger(__name__)

CHAT_LIMIT = 240  # Highrise chat bubbles are short; long answers are split.
HEALTH_INTERVAL = 120
MAX_AI_ACTIONS = 3
CHAT_COMMANDS = {"help", "ping", "status", "reset", "facts", "emotes", "model", "models", "learn", "forget"}

ACTION_PROMPT = """You also control your own avatar in the room. Reply ONLY with one JSON object:
{{"say": "<short chat reply>", "actions": [<zero or more actions>]}}
Actions you can use:
{{"type": "emote", "emote": <number or name>, "target": "me" | "bot" | "<username>" | "all"}}
{{"type": "walk", "to": "me" | "<username>"}}
{{"type": "follow", "who": "me" | "<username>"}}
{{"type": "stop"}}  (stop following)
{{"type": "react", "reaction": "clap" | "heart" | "thumbs" | "wave" | "wink", "to": "me" | "<username>"}}
"me" is the player talking to you, "bot" is yourself. Only add actions the player asked for or that clearly
fit (e.g. "dance with me" = an emote for "bot" and one for "me"); otherwise use "actions": [].
Emotes (number:name): {emotes}
Players here: {players}"""


def parse_plan(text: str) -> tuple[str, list[dict]]:
    """Read the AI's {"say": ..., "actions": [...]} reply; plain text becomes just a reply."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    data = None
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(raw[start : end + 1])
            except ValueError:
                data = None
    if not isinstance(data, dict):
        return text.strip(), []
    actions = data.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    actions = [a for a in actions if isinstance(a, dict) and a.get("type")][:MAX_AI_ACTIONS]
    return str(data.get("say") or "").strip(), actions


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
            min_interval=self.config.min_interval,
            rate_limit_wait=self.config.rate_limit_wait,
        )
        self.bot_user_id = ""
        self.last_used: dict[str, float] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.brain_online = True
        self.started_at = time.monotonic()
        self._health_task: asyncio.Task | None = None
        name = re.escape(self.config.bot_name)
        # Only messages that START with the bot's name are for the bot.
        self._address = re.compile(rf"^\s*@?{name}(?![a-z0-9_])[\s,:;!.?-]*", re.IGNORECASE)
        self.actor = Actor(
            host=self,
            emotes=EmoteBook.load(self.config.emotes_file),
            bot_name=self.config.bot_name,
            owners=self.config.owners,
        )

    # ---- helpers -------------------------------------------------------

    def is_owner(self, user: User) -> bool:
        return user.username.lower() in self.config.owners

    def addressed(self, message: str) -> str | None:
        """The text after a leading "Japalo", or None if the message isn't for the bot."""
        m = self._address.match(message)
        return message[m.end() :].strip() if m else None

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
        self.actor.bot_user_id = self.bot_user_id
        log.info("Connected to room as %s", self.bot_user_id)
        await self.actor.load_room()
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())
        name = self.config.bot_name
        await self.say(f"{name} is online! Start a message with {name}, e.g. '{name} help'")

    async def on_user_join(self, user: User, position: Position | AnchorPosition | None = None) -> None:
        self.actor.seen(user, position)
        await self.say(f"Welcome {user.username}! Talk to me by starting with {self.config.bot_name}.")

    async def on_user_leave(self, user: User) -> None:
        self.actor.left(user)

    async def on_user_move(self, user: User, destination: Position | AnchorPosition) -> None:
        if user.id != self.bot_user_id:
            self.actor.moved(user, destination)

    async def on_chat(self, user: User, message: str) -> None:
        if user.id == self.bot_user_id:
            return
        self.actor.seen(user)
        if intents.is_number_emote(message):
            result = await self.actor.emote(user, message.strip().lstrip("#"), "me")
            if not result.ok:
                await self.say(f"@{user.username} {result.message}")
            return
        if message.startswith(self.config.prefix):
            await self.handle_command(user, message[len(self.config.prefix) :])
            return
        text = self.addressed(message)
        if text is not None:
            await self.handle_addressed(user, text)

    async def on_whisper(self, user: User, message: str) -> None:
        if user.id == self.bot_user_id:
            return
        self.actor.seen(user)
        if message.startswith(self.config.prefix):
            await self.handle_command(user, message[len(self.config.prefix) :], whisper=True)
            return
        # A whisper is already private to the bot, so the name is optional here.
        text = self.addressed(message)
        await self.handle_addressed(user, message if text is None else text, whisper=True)

    async def handle_addressed(self, user: User, text: str, whisper: bool = False) -> None:
        """Something said to the bot: a command, a known action, or a question for the AI."""
        reply_to = user.id if whisper else None
        first = text.split(" ", 1)[0].lower().strip("!?.,")
        if first in CHAT_COMMANDS:
            await self.handle_command(user, text, whisper)
            return
        actions = intents.parse(text)
        if actions:
            messages = [(await self.actor.run(user, a)).message for a in actions]
            await self.say(f"@{user.username} " + " ".join(messages), reply_to)
            return
        await self.handle_ai(user, text, whisper)

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
            players = ", ".join(u.username for uid, u in self.actor.users.items() if uid != self.bot_user_id)
            prompt = ACTION_PROMPT.format(emotes=self.actor.emotes.catalog(), players=players or "unknown")
            try:
                raw = await self.brain.ask(user.id, user.username, text, extra_system=prompt)
                self.brain_online = True
            except BrainError as exc:
                log.error("Brain failed for %s: %s", user.username, exc)
                self.brain_online = False
                raw = "My AI brain is taking a nap right now, try again in a minute."
            answer, actions = parse_plan(raw)
            for action in actions:
                result = await self.actor.run(user, action)
                if not result.ok:
                    answer = f"{answer} ({result.message})".strip()
            if not answer:
                answer = "On it!" if actions else "Hmm?"
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
            b = self.config.bot_name
            text = (
                f"Start with {b}: '{b} <question>', '{b} emote 65', '{b} follow me', '{b} stop', "
                f"'{b} come here'. Type just a number (e.g. 65) to do that emote. "
                f"Also: {b} status / reset / facts / emotes"
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
            skipped = self.brain.skipped_models()
            return (
                f"Brain {state} | model {self.brain.model} (last answer: {s['last_model'] or '-'}) "
                f"| answers {s['ok']} ok, {s['failed']} failed | last {s['last_latency']:.1f}s "
                f"| up {up // 60}m" + (f" | resting: {', '.join(skipped)}" if skipped else "")
            )
        if name == "emotes":
            book = self.actor.emotes.emotes
            if arg.isdigit():
                start = max(1, int(arg))
            else:
                start = 1
            page = book[start - 1 : start + 19]
            if not page:
                return f"I know {len(book)} emotes."
            return " ".join(f"{e.number}.{e.name}" for e in page) + (
                f" | more: {self.config.bot_name} emotes {start + 20}" if start + 19 < len(book) else ""
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
