from __future__ import annotations

import asyncio
import re
import time

from highrise import User
from highrise.models import AnchorPosition, Error, Position, SessionMetadata

from ..ai import intents
from ..ai.brain import Brain, BrainError, Memory
from ..ai.config import AIConfig
from ..ai.plan import ACTION_PROMPT, SYSTEM_PROMPT, parse_plan
from ..emotes import Emote
from ..logging_config import get_logger

logger = get_logger(__name__)

CHAT_LIMIT = 240  # Highrise chat bubbles are short; long answers are split.
REACTIONS = frozenset({"clap", "heart", "thumbs", "wave", "wink"})
SELF_WORDS = frozenset({"me", "myself", "i", "self", "speaker"})
BOT_WORDS = frozenset({"bot", "you", "yourself"})
FOLLOW_GAP = 1.0  # stand this far from the followed player
FOLLOW_DEBOUNCE = 0.6  # walk once the player has stopped moving for this long
AI_SUBCOMMANDS = frozenset({"help", "status", "reset", "facts", "learn", "forget", "model"})


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


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


class AICommandsMixin:
    """Talking to Japalo: any chat that STARTS with the bot's name ("Japalo ...").

    Known requests (emote by number or name, follow, stop, come here, reactions)
    run instantly without the AI. Everything else goes to the AI brain
    (OmniRoute), which answers with a JSON plan; each planned action goes
    through the same checks as the typed commands before it runs:
    emotes use _run_emote_number (so they loop like every other emote and
    `stop` ends them), and acting on other players needs _can_emote_others
    (staff or 100g VIP) or staff.

    Depends on the core class for: self.highrise, self.catalog, self.emote_loops,
    self._settings, self._is_staff, self._can_emote_others, self._find_room_user,
    self._run_emote_number.
    """

    # ------------------------------------------------------------------
    # Setup and room state
    # ------------------------------------------------------------------

    def _init_ai(self, config: AIConfig | None = None, brain: Brain | None = None) -> None:
        self.ai_config = config or AIConfig.from_env()
        cfg = self.ai_config
        self.brain = brain or Brain(
            base_url=cfg.omniroute_url,
            api_key=cfg.omniroute_key,
            model=cfg.model,
            system_prompt=SYSTEM_PROMPT.format(name=cfg.bot_name),
            max_history=cfg.max_history,
            timeout=cfg.timeout,
            memory=Memory(cfg.memory_path),
            fallback_models=cfg.fallback_models,
            min_interval=cfg.min_interval,
            rate_limit_wait=cfg.rate_limit_wait,
        )
        name = re.escape(cfg.bot_name)
        # Only messages that START with the bot's name are for the AI.
        self._ai_address = re.compile(rf"^\s*@?{name}(?![a-z0-9_])[\s,:;!.?-]*", re.IGNORECASE)
        self._ai_users: dict[str, User] = {}
        self._ai_positions: dict[str, Position | AnchorPosition] = {}
        self._ai_following: str | None = None
        self._ai_follow_task: asyncio.Task | None = None
        self._ai_last_used: dict[str, float] = {}
        self._ai_locks: dict[str, asyncio.Lock] = {}

    def _ai_enabled(self) -> bool:
        return self._settings.get("ai", "on").casefold() != "off"

    def _ai_bot_id(self) -> str:
        return getattr(self.highrise, "my_id", "") or ""

    def _ai_addressed(self, text: str) -> str | None:
        """The text after a leading "Japalo", or None if the message isn't for the bot."""
        m = self._ai_address.match(text)
        return text[m.end() :].strip() if m else None

    async def _ai_on_start(self, session_metadata: SessionMetadata) -> None:
        try:
            response = await self.highrise.get_room_users()
            if not isinstance(response, Error):
                for room_user, position in response.content:
                    self._ai_users[room_user.id] = room_user
                    self._ai_positions[room_user.id] = position
        except Exception:  # positions are a nice-to-have; follow re-learns them on move
            logger.exception("AI could not load room positions")

    def _ai_track_move(self, user: User, destination: Position | AnchorPosition) -> None:
        self._ai_users[user.id] = user
        self._ai_positions[user.id] = destination
        if user.id != self._ai_following:
            return
        if self._ai_follow_task and not self._ai_follow_task.done():
            self._ai_follow_task.cancel()
        self._ai_follow_task = asyncio.create_task(self._ai_walk_after(user.id))

    def _ai_user_left(self, user: User) -> None:
        self._ai_users.pop(user.id, None)
        self._ai_positions.pop(user.id, None)
        if self._ai_following == user.id:
            self._ai_stop_following()

    def _ai_stop_following(self) -> None:
        self._ai_following = None
        if self._ai_follow_task and not self._ai_follow_task.done():
            self._ai_follow_task.cancel()
        self._ai_follow_task = None

    def _ai_stop_following_for(self, user: User) -> bool:
        """Plain `stop` also ends following when the speaker is the one being followed."""
        if self._ai_following == user.id:
            self._ai_stop_following()
            return True
        return False

    async def _ai_walk_after(self, user_id: str) -> None:
        try:
            await asyncio.sleep(FOLLOW_DEBOUNCE)
            await self._ai_walk_near(user_id)
        except asyncio.CancelledError:
            pass

    async def _ai_position_of(self, user_id: str) -> Position | AnchorPosition | None:
        position = self._ai_positions.get(user_id)
        if position is None:
            await self._ai_on_start(None)  # refresh from the room list
            position = self._ai_positions.get(user_id)
        return position

    async def _ai_walk_near(self, user_id: str) -> bool:
        position = await self._ai_position_of(user_id)
        if not isinstance(position, Position):
            return False  # unknown spot, or sitting on furniture
        await self.highrise.walk_to(
            Position(position.x + FOLLOW_GAP, position.y, position.z, position.facing)
        )
        return True

    # ------------------------------------------------------------------
    # Chat entry points
    # ------------------------------------------------------------------

    async def _ai_say(self, user: User, text: str, whisper: bool) -> None:
        if not whisper:
            text = f"@{user.username} {text}"
        for piece in chunk_text(text):
            try:
                if whisper:
                    await self.highrise.send_whisper(user.id, piece)
                else:
                    await self.highrise.chat(piece)
            except Exception:
                logger.exception("AI could not send a message")

    async def _handle_ai_message(self, user: User, text: str, whisper: bool = False) -> None:
        """Something said to Japalo: a sub-command, a known action, or a question."""
        self._ai_users[user.id] = user
        if not text:
            await self._ai_say(user, f"Yes? Try '{self.ai_config.bot_name} help'.", whisper)
            return
        first, _, rest = text.partition(" ")
        if first.casefold().strip("!?.,") in AI_SUBCOMMANDS:
            await self._ai_subcommand(user, first.casefold().strip("!?.,"), rest.strip(), whisper)
            return
        actions = intents.parse(text)
        if actions:
            notes = [await self._run_ai_action(user, action) for action in actions]
            notes = [note for note in notes if note]
            if notes:
                await self._ai_say(user, " ".join(notes), whisper)
            return
        if not self._ai_enabled():
            await self._ai_say(user, "My AI chat is switched off in this room right now.", whisper)
            return
        await self._ask_ai(user, text, whisper)

    async def _ask_ai(self, user: User, text: str, whisper: bool) -> None:
        now = time.monotonic()
        if now - self._ai_last_used.get(user.id, 0.0) < self.ai_config.user_cooldown:
            return
        self._ai_last_used[user.id] = now
        lock = self._ai_locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            return  # still answering this player's previous message
        async with lock:
            bot_id = self._ai_bot_id()
            players = ", ".join(u.username for uid, u in self._ai_users.items() if uid != bot_id)
            catalog = " ".join(
                f"{number}:{emote.name}" for number, emote in self.catalog.filter()
            )
            prompt = ACTION_PROMPT.format(emotes=catalog, players=players or "unknown")
            try:
                raw = await self.brain.ask(user.id, user.username, text, extra_system=prompt)
            except BrainError as error:
                logger.error("AI brain failed for %s: %s", user.username, error)
                await self._ai_say(user, "My AI brain is taking a nap, try again in a minute.", whisper)
                return
            answer, actions = parse_plan(raw)
            notes = []
            for action in actions:
                note = await self._run_ai_action(user, action, from_ai=True)
                if note:
                    notes.append(note)
            reply = " ".join([answer, *notes]).strip() or "On it!"
            await self._ai_say(user, reply, whisper)

    # ------------------------------------------------------------------
    # Actions (shared by typed requests and the AI's plans)
    # ------------------------------------------------------------------

    def _ai_find_emote(self, ref: object) -> tuple[int, Emote] | None:
        text = str(ref).strip().lstrip("#")
        if text.isdigit():
            emote = self.catalog.get_by_number(int(text))
            return (int(text), emote) if emote else None
        everything = self.catalog.filter()
        wanted = _key(text)
        for number, emote in everything:
            if wanted and (_key(emote.name) == wanted or emote.emote_id.casefold() == text.casefold()):
                return number, emote
        partial = [(n, e) for n, e in everything if len(wanted) >= 3 and wanted in _key(e.name)]
        return partial[0] if len(partial) == 1 else None

    async def _ai_target(self, user: User, ref: object, staff_check):
        """'me' / 'bot' / a username -> User, "bot", or a refusal string."""
        name = str(ref or "me").strip().lstrip("@").casefold()
        if name in SELF_WORDS or name == user.username.casefold():
            return user
        if name in BOT_WORDS or name == self.ai_config.bot_name.casefold():
            return "bot"
        target = await self._find_room_user(name)
        if target is None:
            return f"I don't see {name} in the room."
        if not await staff_check(user.id):
            return None
        return target

    async def _run_ai_action(self, user: User, action: dict, from_ai: bool = False) -> str | None:
        """Run one action; returns a note for the reply, or None when nothing needs saying."""
        kind = str(action.get("type", "")).casefold()
        try:
            if kind == "emote":
                return await self._ai_emote(user, action.get("emote", ""), action.get("target"))
            if kind == "walk":
                return await self._ai_walk(user, action.get("to") or action.get("target"))
            if kind == "follow":
                return await self._ai_follow(user, action.get("who") or action.get("target"))
            if kind == "stop":
                return await self._ai_stop(user)
            if kind == "react":
                return await self._ai_react(
                    user, action.get("reaction", ""), action.get("to") or action.get("target")
                )
        except Exception as error:  # one failed game call must not kill the chat handler
            logger.exception("AI action %s failed", action)
            return f"(that didn't work: {error.__class__.__name__})"
        return None if from_ai else f"I can't do '{kind}'."

    async def _ai_emote(self, user: User, ref: object, target_ref: object) -> str | None:
        found = self._ai_find_emote(ref)
        if found is None:
            return f"I don't know emote {ref}. See !emotelist or !findemote."
        number, emote = found
        target = await self._ai_target(user, target_ref, self._can_emote_others)
        if target is None:
            return "Only room staff or 100g VIP tippers can emote others."
        if isinstance(target, str) and target != "bot":
            return target
        if target == "bot":
            await self.highrise.send_emote(emote.emote_id)
            return None
        await self._run_emote_number(user, number, target=target)  # loops; whispers its own status
        return None

    async def _ai_walk(self, user: User, target_ref: object) -> str:
        target = await self._ai_target(user, target_ref, self._is_staff)
        if target is None:
            return "Only room staff can send me to other players."
        if isinstance(target, str):
            return "I'm already here." if target == "bot" else target
        if not await self._ai_walk_near(target.id):
            return f"I can't see a floor spot next to {target.username}."
        return f"Coming, {target.username}!"

    async def _ai_follow(self, user: User, target_ref: object) -> str:
        target = await self._ai_target(user, target_ref, self._is_staff)
        if target is None:
            return "Only room staff can make me follow other players."
        if isinstance(target, str):
            return "I can't follow myself." if target == "bot" else target
        self._ai_stop_following()
        self._ai_following = target.id
        await self._ai_walk_near(target.id)
        return f"Following {target.username}. Say '{self.ai_config.bot_name} stop' to stop."

    async def _ai_stop(self, user: User) -> str:
        notes = []
        if self._ai_following is not None:
            if self._ai_following == user.id or await self._is_staff(user.id):
                self._ai_stop_following()
                notes.append("Stopped following.")
            else:
                notes.append("Only the person I'm following or staff can stop that.")
        stopped = await self.emote_loops.stop(user.id)
        logger.info("AI stop by %s (%s): loop %s", user.username, user.id,
                    "stopped" if stopped else "not running")
        if stopped:
            notes.append("Your emote loop stopped.")
        return " ".join(notes) or "Nothing to stop."

    async def _ai_react(self, user: User, reaction: str, target_ref: object) -> str | None:
        reaction = str(reaction or "").casefold()
        if reaction not in REACTIONS:
            return f"Reactions: {', '.join(sorted(REACTIONS))}."
        target = await self._ai_target(user, target_ref, lambda _uid: _always_true())
        if isinstance(target, str):
            return "I can't react to myself." if target == "bot" else target
        await self.highrise.react(reaction, target.id)
        return None

    # ------------------------------------------------------------------
    # "Japalo <subcommand>"
    # ------------------------------------------------------------------

    async def _ai_subcommand(self, user: User, name: str, arg: str, whisper: bool) -> None:
        bot = self.ai_config.bot_name
        memory = self.brain.memory
        if name == "help":
            await self.highrise.send_whisper(
                user.id,
                f"Talk to me by starting with {bot}:\n"
                f"- {bot} <anything> — chat with the AI\n"
                f"- {bot} emote 65 / {bot} emote moonwalk — loop an emote (stop to end)\n"
                f"- {bot} follow me / {bot} stop / {bot} come here\n"
                f"- {bot} send heart to @name\n"
                f"- {bot} come dance with me — the AI picks the moves\n"
                f"- {bot} status / reset / facts\n"
                "Full list: !help ai",
            )
            return
        if name == "reset":
            self.brain.reset(user.id)
            await self._ai_say(user, "Forgot our chat. Fresh start!", whisper)
            return
        if name == "status":
            stats = self.brain.stats
            resting = self.brain.skipped_models()
            following = self._ai_users.get(self._ai_following or "")
            await self.highrise.send_whisper(
                user.id,
                f"AI {'on' if self._ai_enabled() else 'off'} | model {self.brain.model} "
                f"(last answer: {stats['last_model'] or '-'}) | {stats['ok']} answers, "
                f"{stats['failed']} failed | following: {following.username if following else '-'}"
                + (f" | resting: {', '.join(resting)}" if resting else ""),
            )
            return
        if name == "facts":
            facts = memory.facts if memory else []
            await self.highrise.send_whisper(
                user.id,
                "\n".join(f"{i}. {fact}" for i, fact in enumerate(facts, 1))
                or "I haven't learned any facts yet.",
            )
            return
        # learn / forget / model change how the AI behaves for everyone: staff only.
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can do that.")
            return
        if name == "learn":
            if not arg or memory is None:
                await self.highrise.send_whisper(user.id, f"Usage: {bot} learn <fact>")
                return
            memory.learn(arg)
            await self.highrise.send_whisper(user.id, f"Learned it. I know {len(memory.facts)} fact(s).")
        elif name == "forget":
            fact = memory.forget(int(arg)) if memory and arg.isdigit() else None
            await self.highrise.send_whisper(
                user.id, f"Forgot: {fact}" if fact else f"Usage: {bot} forget <number from {bot} facts>"
            )
        elif name == "model":
            if arg:
                self.brain.model = arg
            await self.highrise.send_whisper(user.id, f"AI model: {self.brain.model}")


async def _always_true() -> bool:
    return True
