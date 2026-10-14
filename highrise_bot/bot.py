"""Japalo's core: SDK event hooks + command dispatch.

This file used to hold every command handler inline (~1200 lines, one long
if/elif chain). It's now just:
  1. The HighriseRoomBot class definition, mixing in the command groups
     from highrise_bot/commands/ (see that package's docstring).
  2. The Highrise SDK event hooks (on_start, on_user_join, on_tip, ...).
  3. on_chat's dispatch, driven by small lookup tables instead of a long
     if/elif chain — adding a command means adding a table row, not
     hunting for the right spot in a wall of elifs.

Personality (the "Japalo" voice) lives in personality.py and is applied
through self._voice(), which respects !config set personality off.
"""

from __future__ import annotations

import asyncio
import shlex
import time

from highrise import BaseBot, User
from highrise.models import AnchorPosition, Error, Position, SessionMetadata

from . import personality
from .commands.admin_commands import AdminCommandsMixin
from .commands.ai_commands import AICommandsMixin
from .commands.command_builder import CommandBuilderMixin
from .commands.economy_commands import EconomyCommandsMixin
from .commands.emote_commands import EmoteCommandsMixin
from .commands.game_commands import GameCommandsMixin
from .commands.help_commands import HelpMixin
from .commands.interaction_commands import InteractionCommandsMixin
from .commands.moderation_commands import ModerationCommandsMixin
from .constants import (
    CATALOG_PATH,
    DB_PATH,
    INTERACTIONS_PATH,
    SETTINGS_SCHEMA,
    WORD_FILTER_PATH,
)
from .emote_loop import EmoteLoopManager
from .emotes import load_catalog
from .games.emoji_riddle import EmojiRiddleGame
from .games.guess_number import GuessNumberGame
from .games.math_blitz import MathBlitzGame
from .games.scramble import ScrambleGame
from .interactions import load_interactions
from .logging_config import get_logger
from .messages import (
    plain_join_message,
    plain_leave_message,
    random_join_message,
    random_leave_message,
)
from .moderation_filters import SpamTracker, load_word_filter
from .storage import Storage
from .trivia import TriviaGame

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Command dispatch tables. Each maps a chat command to how on_chat should
# route it. Adding a new command means adding one row here, not editing a
# long if/elif chain.
# ---------------------------------------------------------------------------

# command -> handler method name. Handler signature: (self, user, args).
COMMAND_TABLE: dict[str, str] = {
    "!help": "_send_help",
    "!commands": "_send_help",
    "!emotelist": "_send_emote_list",
    "!emote": "_handle_emote_command",
    "!emotes": "_handle_emote_command",
    "!surprise": "_surprise_emote",
    "!surpriseme": "_surprise_emote",
    "!randomemote": "_surprise_emote",
    "!findemote": "_find_emote",
    "!fav": "_handle_favorite",
    "!testemote": "_test_emote",
    "!emotetest": "_test_emote",
    "!emotecapture": "_handle_emote_capture",
    "!capturedemotes": "_send_captured_emotes",
    "!catalog": "_handle_catalog_command",
    "!games": "_send_games_list",
    "!answer": "_answer_active_game",
    "!score": "_send_score",
    "!leaderboard": "_send_leaderboard",
    "!tipleaderboard": "_send_tip_leaderboard",
    "!tips": "_send_tip_leaderboard",
    "!profile": "_send_profile",
    "!endgame": "_force_end_game",
    "!config": "_handle_config",
    "!customcommands": "_list_custom_commands",
    "!delcommand": "_delete_custom_command",
}

# command -> which minigame it starts. Handler signature: self._start_game(game).
GAME_START_COMMANDS: dict[str, str] = {
    "!trivia": "trivia",
    "!scramble": "scramble",
    "!math": "math",
    "!riddle": "riddle",
    "!guessnumber": "guessnumber",
}

# command -> (handler method name, fixed action string). These handlers
# need to know *which* action fired (warn vs warnings, kick vs ban vs mute
# vs unban, freeze vs unfreeze), so the table carries that alongside the
# command. Handler signature: (self, user, action, args).
ACTION_COMMANDS: dict[str, tuple[str, str]] = {
    "!warn": ("_handle_warning_command", "warn"),
    "!warnings": ("_handle_warning_command", "warnings"),
    "!ban": ("_handle_moderation", "ban"),
    "!kick": ("_handle_moderation", "kick"),
    "!mute": ("_handle_moderation", "mute"),
    "!unban": ("_handle_moderation", "unban"),
    "!freeze": ("_handle_freeze", "freeze"),
    "!unfreeze": ("_handle_freeze", "unfreeze"),
    "!punch": ("_handle_interaction", "punch"),
    "!slap": ("_handle_interaction", "slap"),
    "!explode": ("_handle_interaction", "explode"),
}

# command -> grant (True) or revoke (False) moderator.
MOD_CHANGE_COMMANDS: dict[str, bool] = {
    "!setmod": True,
    "!delmod": False,
}

STOP_COMMANDS = {"stop", "!stop"}


class HighriseRoomBot(
    BaseBot,
    AICommandsMixin,
    CommandBuilderMixin,
    EmoteCommandsMixin,
    InteractionCommandsMixin,
    GameCommandsMixin,
    EconomyCommandsMixin,
    ModerationCommandsMixin,
    AdminCommandsMixin,
    HelpMixin,
):
    """Room fun and moderation bot for one Highrise room, voiced as Japalo."""

    def __init__(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self._catalog_write_lock = asyncio.Lock()
        self.emote_loops = EmoteLoopManager()
        self.storage = Storage(DB_PATH)
        # Stage 4 (emote discovery pipeline): ids already in the configured
        # catalog are never re-logged; ids already captured this run are
        # only logged to storage once, on first sight.
        self._known_emote_ids: frozenset[str] = self.catalog.known_ids()
        self._captured_this_run: set[str] = set()
        self._settings: dict[str, str] = {
            key: default for key, (_type, default) in SETTINGS_SCHEMA.items()
        }

        # Minigames: only one is active room-wide at a time.
        self.trivia = TriviaGame()
        self.scramble = ScrambleGame()
        self.math_blitz = MathBlitzGame()
        self.guess_number = GuessNumberGame()
        self.emoji_riddle = EmojiRiddleGame()
        self.active_game: str | None = None
        self.game_task: asyncio.Task[None] | None = None

        # Moderation.
        self.room_owner_id: str | None = None
        self._moderator_cache: dict[str, tuple[float, bool]] = {}
        self.word_filter = load_word_filter(WORD_FILTER_PATH)
        self.spam_tracker = SpamTracker()
        self._command_cooldowns: dict[str, float] = {}
        self._join_times: list[float] = []
        self._frozen_users: dict[str, Position] = {}
        self._last_auto_spend = 0.0

        # !punch / !slap / !explode (interaction_commands.py).
        self.interactions = load_interactions(INTERACTIONS_PATH)
        self._interaction_cooldowns: dict[str, float] = {}

        # AI: talking to "Japalo ..." and letting the AI act (ai_commands.py),
        # plus AI-built custom commands (command_builder.py).
        self._init_ai()
        self._init_command_builder()

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def _personality_on(self) -> bool:
        return self._settings.get("personality", "on").casefold() != "off"

    def _voice(self, pool: tuple[str, ...], plain: str, **kwargs: object) -> str:
        """Pick a flavored line from `pool`, or fall back to `plain` text if
        the room has `!config set personality off`. Every call site passes
        a `plain` string that alone carries all required info, so turning
        personality off never hides functionality, only flavor."""
        if not self._personality_on():
            return plain
        return personality.pick(pool, **kwargs)

    # ------------------------------------------------------------------
    # Highrise SDK event hooks
    # ------------------------------------------------------------------

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.room_owner_id = session_metadata.room_info.owner_id
        await self.storage.connect()
        stored_settings = await self.storage.all_settings()
        for key, (_type, default) in SETTINGS_SCHEMA.items():
            self._settings[key] = stored_settings.get(key, default)
        logger.info("Bot started in room owned by %s", self.room_owner_id)
        await self._load_custom_commands()
        await self._ai_on_start(session_metadata)
        text = self._voice(
            personality.STARTUP_MESSAGES,
            "Bot online. Type !help for emotes, games, and room commands.",
        )
        await self.highrise.chat(text)

    async def on_user_leave(self, user: User) -> None:
        await self.emote_loops.stop(user.id)
        self._ai_user_left(user)
        self._frozen_users.pop(user.id, None)
        if self._personality_on():
            await self.highrise.chat(random_leave_message(user.username))
        else:
            await self.highrise.chat(plain_leave_message(user.username))

    async def on_user_join(self, user: User, position: object) -> None:
        if user.id == getattr(self.highrise, "my_id", None):
            return
        await self.storage.remember_username(user.id, user.username)
        join_count = await self.storage.record_join(user.id)
        now = time.monotonic()
        self._join_times.append(now)
        window = self._setting_float("raid_window_seconds")
        self._join_times = [stamp for stamp in self._join_times if now - stamp <= window]
        if len(self._join_times) >= self._setting_int("raid_join_threshold"):
            raid_text = self._voice(
                personality.RAID_ALERT_MESSAGES,
                "Raid protection triggered: a burst of joins was detected. "
                "Staff should watch the room closely.",
            )
            await self.highrise.chat(raid_text)
            self._join_times.clear()
            if self._settings.get("raid_kick_enabled", "true").casefold() == "true":
                try:
                    await self.highrise.moderate_room(user.id, "kick")
                    logger.warning("Raid protection kicked joining user %s", user.id)
                    return
                except Exception:
                    logger.exception("Raid protection could not kick %s", user.id)
        if join_count in {10, 25, 50, 100}:
            milestone_text = self._voice(
                personality.MILESTONE_MESSAGES,
                f"Welcome back, {user.username} — that's your {join_count}th visit!",
                username=user.username,
                count=join_count,
            )
            await self.highrise.chat(milestone_text)
        elif self._personality_on():
            await self.highrise.chat(random_join_message(user.username))
        else:
            await self.highrise.chat(plain_join_message(user.username))

    async def on_user_move(
        self, user: User, destination: Position | AnchorPosition
    ) -> None:
        if user.id != getattr(self.highrise, "my_id", None):
            self._ai_track_move(user, destination)
        frozen_at = self._frozen_users.get(user.id)
        if frozen_at is None:
            return
        # Highrise has no native freeze request. Re-teleporting on every move
        # is deliberately documented as a best-effort soft-freeze.
        try:
            await self.highrise.teleport(user.id, frozen_at)
        except Exception:
            logger.exception("Soft-freeze teleport failed for %s", user.id)

    async def on_tip(self, sender: User, receiver: User, tip: object) -> None:
        if receiver.id != getattr(self.highrise, "my_id", None):
            return
        await self._handle_tip(sender, tip)

    async def on_moderate(
        self,
        moderator_id: str,
        target_user_id: str,
        moderation_type: str,
        duration: int | None,
    ) -> None:
        await self.storage.record_moderation(
            moderator_id, target_user_id, moderation_type, duration
        )
        logger.info(
            "Native moderation event: %s moderated %s (%s, duration=%s)",
            moderator_id, target_user_id, moderation_type, duration,
        )

    async def on_emote(self, user: User, emote_id: str, receiver: User) -> None:
        """Stage 4 of the emote pipeline: while capture is enabled (see
        !emotecapture), any emote_id actually performed in the room that
        isn't in our configured catalog gets logged - a real id seen live,
        never guessed. Review it with !capturedemotes."""
        if self._settings.get("emote_capture_enabled", "false").casefold() != "true":
            return
        if emote_id in self._known_emote_ids or emote_id in self._captured_this_run:
            return
        self._captured_this_run.add(emote_id)
        is_new = await self.storage.record_captured_emote(emote_id, user.id)
        if is_new:
            logger.info(
                "Captured new emote id via on_emote: %s (performed by %s)",
                emote_id, user.username,
            )

    # ------------------------------------------------------------------
    # Chat dispatch
    # ------------------------------------------------------------------

    async def on_chat(self, user: User, message: str) -> None:
        text = message.strip()
        if not text:
            return

        await self.storage.remember_username(user.id, user.username)

        if not await self._is_staff(user.id):
            await self._apply_moderation_filters(user, text)

        if text.isdigit():
            number = int(text)
            if self.active_game == "guessnumber":
                await self._guess_number_attempt(user, number)
            else:
                await self._run_emote_number(user, number)
            return

        # "Japalo ..." is for the AI. Checked before shlex, which would choke
        # on ordinary apostrophes ("Japalo what's up?").
        ai_text = self._ai_addressed(text)
        if ai_text is not None:
            await self._handle_ai_message(user, ai_text)
            return

        try:
            tokens = shlex.split(text)
        except ValueError:
            # An apostrophe ("!emote let's go shopping", "!warn @x don't spam")
            # isn't a broken quote, so fall back to splitting on spaces.
            tokens = text.split()

        command = tokens[0].casefold()
        args = tokens[1:]
        if command.startswith("!") and not await self._consume_command_cooldown(user.id):
            cooldown_text = self._voice(
                personality.COOLDOWN_MESSAGES,
                "Slow down a little — commands have a short cooldown.",
            )
            await self.highrise.send_whisper(user.id, cooldown_text)
            return

        if command.rstrip(".!?,") in STOP_COMMANDS:  # "stop!", "Stop." count too
            if self._ai_stop_following_for(user):
                await self.highrise.send_whisper(user.id, "Stopped following you.")
            await self._stop_emote(user)
            return
        if command in GAME_START_COMMANDS:
            await self._start_game(GAME_START_COMMANDS[command])
            return
        if command in MOD_CHANGE_COMMANDS:
            await self._handle_moderator_change(user, MOD_CHANGE_COMMANDS[command], args)
            return
        if command in ACTION_COMMANDS:
            handler_name, action = ACTION_COMMANDS[command]
            await getattr(self, handler_name)(user, action, args)
            return
        if command == "!unmute":
            await self.highrise.chat(
                "Highrise's official SDK has no native unmute request. "
                "Mutes expire automatically when their duration ends."
            )
            return

        handler_name = COMMAND_TABLE.get(command)
        if handler_name is not None:
            await getattr(self, handler_name)(user, args)
            return
        custom = self.custom_commands.get(command[1:]) if command.startswith("!") else None
        if custom is not None:
            await self._run_custom_command(user, custom, args)

    async def on_whisper(self, user: User, message: str) -> None:
        """Whispers go straight to the AI (the bot's name is optional there)."""
        if user.id == getattr(self.highrise, "my_id", None):
            return
        text = message.strip()
        if not text:
            return
        ai_text = self._ai_addressed(text)
        await self._handle_ai_message(user, text if ai_text is None else ai_text, whisper=True)

    # ------------------------------------------------------------------
    # Shared utility (used across multiple command mixins)
    # ------------------------------------------------------------------

    def _reserved_command_names(self) -> set[str]:
        """Built-in command names (without "!"), which custom commands may not reuse."""
        names = set(COMMAND_TABLE) | set(GAME_START_COMMANDS) | set(ACTION_COMMANDS)
        names |= set(MOD_CHANGE_COMMANDS) | STOP_COMMANDS | {"!unmute"}
        return {name.lstrip("!") for name in names}

    async def _find_room_user(self, query: str) -> User | None:
        normalized = query.strip().lstrip("@")
        if not normalized:
            return None
        response = await self.highrise.get_room_users()
        if isinstance(response, Error):
            return None
        for room_user, _position in response.content:
            if room_user.id == normalized or room_user.username.casefold() == normalized.casefold():
                return room_user
        return None
