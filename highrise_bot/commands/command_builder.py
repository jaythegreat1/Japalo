from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field

from highrise import User

from .. import custom_commands as cc
from ..ai.brain import BrainError
from ..ai.designer import DESIGN_PROMPT, parse_design
from ..logging_config import get_logger

logger = get_logger(__name__)

DESIGN_REQUEST = re.compile(
    r"\b(make|create|add|build|new|design|edit|change|update|fix)\b.*\bcommands?\b", re.IGNORECASE
)
SESSION_TIMEOUT = 15 * 60  # a design conversation is dropped after 15 quiet minutes
MAX_REPAIRS = 2  # times the AI may fix its own draft after the validator rejects it
WHISPER_LIMIT = 400


@dataclass
class DesignSession:
    """One staff member's command-design conversation with the AI."""

    turns: list[dict] = field(default_factory=list)  # chat messages after the system prompt
    draft: dict | None = None  # last validated command
    tested: bool = False
    editing: str | None = None  # name of the saved command being changed
    touched: float = field(default_factory=time.monotonic)


class CommandBuilderMixin:
    """AI command builder: staff explain a command, the AI builds it, they test it, then save it.

      Japalo make a command !hug where I hug them and they blush
        -> the AI asks about anything unclear and suggests ideas, or drafts it
      (reply in normal words to answer or change things)
      Japalo test @name   -> runs the draft for real (target defaults to you)
      Japalo save         -> keeps it; needs a successful test first
      Japalo cancel       -> drops the draft
      !customcommands     -> list saved commands; !delcommand <name> (staff) removes one

    Commands are data checked by custom_commands.validate(), never code.
    Depends on the core class for: self.highrise, self.catalog, self.storage, self.brain,
    self.ai_config, self._is_staff, self._find_room_user, self._ai_walk_near,
    self._reserved_command_names.
    """

    def _init_command_builder(self) -> None:
        self.custom_commands: dict[str, dict] = {}
        self._design_sessions: dict[str, DesignSession] = {}
        self._custom_cooldowns: dict[tuple[str, str], float] = {}

    async def _load_custom_commands(self) -> None:
        reserved = self._reserved_command_names()
        for name, spec_json in await self.storage.list_custom_commands():
            try:
                spec, errors = cc.validate(json.loads(spec_json), self.catalog, reserved)
            except ValueError as error:
                spec, errors = None, [str(error)]
            if spec is None:
                logger.warning("Skipping saved custom command !%s: %s", name, "; ".join(errors))
                continue
            self.custom_commands[spec["name"]] = spec
        logger.info("Loaded %d custom command(s)", len(self.custom_commands))

    async def _builder_whisper(self, user: User, text: str) -> None:
        """Whisper long text in pieces, splitting at line breaks where possible."""
        while text:
            piece = text[:WHISPER_LIMIT]
            if len(text) > WHISPER_LIMIT and "\n" in piece:
                piece = piece[: piece.rindex("\n")]
            await self.highrise.send_whisper(user.id, piece.strip())
            text = text[len(piece):].lstrip("\n")

    # ------------------------------------------------------------------
    # Design conversation (entered from AICommandsMixin._handle_ai_message)
    # ------------------------------------------------------------------

    def _design_session(self, user_id: str) -> DesignSession | None:
        session = self._design_sessions.get(user_id)
        if session and time.monotonic() - session.touched > SESSION_TIMEOUT:
            self._design_sessions.pop(user_id, None)
            return None
        return session

    def _wants_design(self, user: User, text: str) -> bool:
        return self._design_session(user.id) is not None or bool(DESIGN_REQUEST.search(text))

    async def _handle_design(self, user: User, text: str) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can create commands.")
            return
        if not self._ai_enabled():
            await self.highrise.send_whisper(user.id, "AI is switched off (!config set ai on), so I can't build commands.")
            return
        session = self._design_session(user.id)
        word, _, rest = text.strip().partition(" ")
        word = word.casefold().strip("!.?,")
        if session is not None and word in {"test", "save", "cancel", "show"}:
            await getattr(self, f"_design_{word}")(user, session, rest.strip())
            return
        if session is None:
            session = DesignSession()
            existing = self._mentioned_custom_command(text)
            if existing is not None:
                session.draft, session.editing = dict(existing), existing["name"]
            self._design_sessions[user.id] = session
        session.touched = time.monotonic()
        await self._design_turn(user, session, text)

    def _mentioned_custom_command(self, text: str) -> dict | None:
        if not re.search(r"\b(edit|change|update|fix)\b", text, re.IGNORECASE):
            return None
        for name in re.findall(r"!([a-z][a-z0-9_]{1,19})", text.casefold()):
            if name in self.custom_commands:
                return self.custom_commands[name]
        return None

    def _design_system_prompt(self, session: DesignSession) -> str:
        current = ""
        if session.draft is not None:
            current = "\nCurrent draft (change it as the user asks; keep the rest):\n" + cc.dumps(session.draft) + "\n"
        catalog = " ".join(f"{number}:{emote.name}" for number, emote in self.catalog.filter())
        existing = ", ".join(f"!{n}" for n in sorted(self.custom_commands)) or "none"
        return DESIGN_PROMPT.format(
            bot=self.ai_config.bot_name,
            reserved=", ".join(sorted(self._reserved_command_names())),
            existing=existing,
            current=current,
            emotes=catalog,
        )

    async def _design_turn(self, user: User, session: DesignSession, text: str) -> None:
        session.turns.append({"role": "user", "content": text})
        session.turns = session.turns[-12:]
        # Built-ins and other custom commands are taken; the one being edited may keep its name.
        reserved = (self._reserved_command_names() | set(self.custom_commands)) - {session.editing}
        messages = [{"role": "system", "content": self._design_system_prompt(session)}, *session.turns]
        try:
            for attempt in range(MAX_REPAIRS + 1):
                # Designing is rare and harder than chat, so let the model think more.
                raw = await self.brain.complete(messages, overrides={"reasoning_effort": "medium"})
                reply = parse_design(raw)
                status = reply.get("status")
                if reply.get("command") is not None and status != "question":
                    status = "ready"
                if status == "question" and reply["questions"]:
                    session.turns.append({"role": "assistant", "content": raw})
                    await self._builder_whisper(user, self._format_questions(reply))
                    return
                if status == "ready":
                    spec, errors = cc.validate(reply.get("command"), self.catalog, reserved)
                    if spec is not None:
                        break
                else:
                    errors = ['reply with ONE JSON object: {"status": "question", "questions": [...], '
                              '"ideas": [...]} or {"status": "ready", "command": {...}, "ideas": [...]}']
                # Self-repair: show the AI exactly what was wrong with its reply.
                logger.info("Design reply rejected (attempt %d): %s | reply: %.300s",
                            attempt + 1, errors, raw)
                messages = [*messages, {"role": "assistant", "content": raw}, {
                    "role": "user",
                    "content": "The bot rejected that reply:\n- " + "\n- ".join(errors)
                    + "\nReturn the corrected JSON only.",
                }]
            else:
                await self._builder_whisper(
                    user,
                    "I couldn't build a valid command from that:\n- " + "\n- ".join(errors[:4])
                    + "\nCan you describe it differently?",
                )
                return
        except BrainError as error:
            logger.error("Command designer AI failed: %s", error)
            await self.highrise.send_whisper(user.id, "My AI brain is taking a nap, try again in a minute.")
            return

        session.turns.append({"role": "assistant", "content": cc.dumps(spec)})
        session.draft, session.tested = spec, False
        ideas = reply.get("ideas") or []
        bot = self.ai_config.bot_name
        await self._builder_whisper(
            user,
            "Draft:\n" + cc.describe(spec, self.catalog)
            + ("\nIdeas:\n" + "\n".join(f"- {idea}" for idea in ideas) if ideas else "")
            + f"\nNext: '{bot} test" + (" @name" if spec["needs_target"] else "")
            + f"' to try it, then '{bot} save'. Or tell me what to change.",
        )

    @staticmethod
    def _format_questions(reply: dict) -> str:
        questions = reply.get("questions") or ["Can you tell me a bit more about what the command should do?"]
        text = "A few questions first:\n" + "\n".join(f"- {q}" for q in questions)
        ideas = reply.get("ideas") or []
        if ideas:
            text += "\nIdeas:\n" + "\n".join(f"- {idea}" for idea in ideas)
        return text

    async def _design_show(self, user: User, session: DesignSession, rest: str) -> None:
        if session.draft is None:
            await self.highrise.send_whisper(user.id, "No draft yet. Describe the command you want.")
            return
        await self._builder_whisper(user, cc.describe(session.draft, self.catalog))

    async def _design_cancel(self, user: User, session: DesignSession, rest: str) -> None:
        self._design_sessions.pop(user.id, None)
        await self.highrise.send_whisper(user.id, "Draft dropped.")

    async def _design_test(self, user: User, session: DesignSession, rest: str) -> None:
        if session.draft is None:
            await self.highrise.send_whisper(user.id, "No draft to test yet. Describe the command first.")
            return
        target = user
        if rest:
            target = await self._find_room_user(rest.split()[0])
            if target is None:
                await self.highrise.send_whisper(user.id, "That user is not in the room.")
                return
        session.touched = time.monotonic()
        failures = await self._run_custom_steps(session.draft, user, target)
        if failures:
            session.tested = False
            await self._builder_whisper(
                user,
                "Test ran with problems:\n- " + "\n- ".join(failures)
                + "\nTell me what to change, or test again.",
            )
            return
        session.tested = True
        await self.highrise.send_whisper(
            user.id, f"Test passed. Say '{self.ai_config.bot_name} save' to keep !{session.draft['name']}."
        )

    async def _design_save(self, user: User, session: DesignSession, rest: str) -> None:
        if session.draft is None:
            await self.highrise.send_whisper(user.id, "No draft to save yet.")
            return
        if not session.tested:
            await self.highrise.send_whisper(
                user.id, f"Test it first: '{self.ai_config.bot_name} test'. I only keep commands that passed a test."
            )
            return
        spec = session.draft
        if session.editing and session.editing != spec["name"]:
            await self.storage.delete_custom_command(session.editing)
            self.custom_commands.pop(session.editing, None)
        await self.storage.save_custom_command(spec["name"], cc.dumps(spec), user.id)
        self.custom_commands[spec["name"]] = spec
        self._design_sessions.pop(user.id, None)
        usage = f"!{spec['name']}" + (" @name" if spec["needs_target"] else "")
        await self.highrise.chat(f"New command: {usage}" + (f" — {spec['description']}" if spec["description"] else ""))
        logger.info("Custom command !%s saved by %s", spec["name"], user.username)

    # ------------------------------------------------------------------
    # Running saved commands (from on_chat) and managing them
    # ------------------------------------------------------------------

    async def _run_custom_command(self, user: User, spec: dict, args: list[str]) -> None:
        if spec["staff_only"] and not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, f"!{spec['name']} is staff-only.")
            return
        target = None
        if spec["needs_target"]:
            target = await self._find_room_user(args[0]) if args else None
            if target is None:
                await self.highrise.send_whisper(user.id, f"Use !{spec['name']} @PlayerName.")
                return
        key = (user.id, spec["name"])
        now = time.monotonic()
        if now - self._custom_cooldowns.get(key, 0.0) < spec["cooldown_seconds"]:
            await self.highrise.send_whisper(user.id, f"Wait a few seconds before using !{spec['name']} again.")
            return
        self._custom_cooldowns[key] = now
        failures = await self._run_custom_steps(spec, user, target)
        for failure in failures:
            logger.warning("!%s by %s: %s", spec["name"], user.username, failure)

    async def _run_custom_steps(self, spec: dict, speaker: User, target: User | None) -> list[str]:
        """Run each step; returns a list of what didn't work (empty = all good)."""
        bot_id = getattr(self.highrise, "my_id", None)
        bot_name = self.ai_config.bot_name
        people = {"speaker": speaker, "target": target or speaker}
        failures = []
        for index, step in enumerate(spec["steps"], 1):
            kind = step["do"]
            try:
                if kind == "emote":
                    emote_id = random.choice(step["emote"])
                    person = None if step["who"] == "bot" else people[step["who"]]
                    if person is None or person.id == bot_id:
                        await self.highrise.send_emote(emote_id)
                    else:
                        await self.highrise.send_emote(emote_id, person.id)
                elif kind in ("say", "whisper"):
                    text = cc.fill(random.choice(step["text"]), speaker.username,
                                   (target or speaker).username, bot_name)
                    if kind == "say":
                        await self.highrise.chat(text)
                    else:
                        await self.highrise.send_whisper(people[step["to"]].id, text)
                elif kind == "react":
                    person = people[step["to"]]
                    if person.id != bot_id:
                        await self.highrise.react(step["reaction"], person.id)
                elif kind == "wait":
                    await asyncio.sleep(step["seconds"])
                elif kind == "walk":
                    if not await self._ai_walk_near(people[step["to"]].id):
                        failures.append(f"step {index}: can't see a floor spot next to {people[step['to']].username}")
            except Exception as error:
                failures.append(f"step {index} ({kind}): {error}")
        return failures

    async def _list_custom_commands(self, user: User, args: list[str]) -> None:
        if not self.custom_commands:
            await self.highrise.send_whisper(
                user.id, f"No custom commands yet. Staff can make one: '{self.ai_config.bot_name} make a command ...'"
            )
            return
        lines = [
            f"!{name}" + (" @name" if spec["needs_target"] else "")
            + (f" — {spec['description']}" if spec["description"] else "")
            for name, spec in sorted(self.custom_commands.items())
        ]
        await self._builder_whisper(user, "Custom commands:\n" + "\n".join(lines))

    async def _delete_custom_command(self, user: User, args: list[str]) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can delete commands.")
            return
        name = args[0].casefold().lstrip("!") if args else ""
        if name not in self.custom_commands:
            await self.highrise.send_whisper(user.id, "Usage: !delcommand <name> (see !customcommands).")
            return
        await self.storage.delete_custom_command(name)
        self.custom_commands.pop(name, None)
        await self.highrise.send_whisper(user.id, f"Deleted !{name}.")
