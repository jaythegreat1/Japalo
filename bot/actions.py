"""What the bot can physically do in the room: emote, walk, follow, react.

Every action, whether it came from a typed command or from the AI, goes through
`Actor.run()`, which checks it against the allowed list and the speaker's permissions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from highrise import User
from highrise.models import AnchorPosition, Position

from .emotes import EmoteBook

log = logging.getLogger(__name__)

REACTIONS = {"clap", "heart", "thumbs", "wave", "wink"}
SELF_WORDS = {"me", "myself", "i", "self", "speaker"}
BOT_WORDS = {"bot", "you", "yourself", "japalo"}
ALL_WORDS = {"all", "everyone", "everybody", "room"}
FOLLOW_GAP = 1.0  # stand this far from the followed player
FOLLOW_DEBOUNCE = 0.6  # walk once the player has stopped moving for this long


@dataclass
class Result:
    ok: bool
    message: str


@dataclass
class Actor:
    host: object  # the bot; its `.highrise` is only set once connected
    emotes: EmoteBook
    bot_name: str = "Japalo"
    owners: set[str] = field(default_factory=set)
    bot_user_id: str = ""
    users: dict[str, User] = field(default_factory=dict)
    positions: dict[str, Position | AnchorPosition] = field(default_factory=dict)
    following: str | None = None
    _follow_task: asyncio.Task | None = None

    # ---- room state ----------------------------------------------------

    def is_owner(self, user: User) -> bool:
        return user.username.lower() in self.owners

    def seen(self, user: User, position: Position | AnchorPosition | None = None) -> None:
        self.users[user.id] = user
        if position is not None:
            self.positions[user.id] = position

    def left(self, user: User) -> None:
        self.users.pop(user.id, None)
        self.positions.pop(user.id, None)
        if self.following == user.id:
            self.stop_following()

    def find_user(self, name: str) -> User | None:
        name = name.strip().lstrip("@").lower()
        for user in self.users.values():
            if user.username.lower() == name:
                return user
        return None

    async def load_room(self) -> None:
        """Learn who is in the room and where they stand."""
        try:
            resp = await self.host.highrise.get_room_users()
            for user, pos in getattr(resp, "content", []) or []:
                self.seen(user, pos)
        except Exception:  # the room list is a nice-to-have; keep running without it
            log.exception("Could not load room users")

    # ---- following -----------------------------------------------------

    def stop_following(self) -> None:
        self.following = None
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
        self._follow_task = None

    def moved(self, user: User, destination: Position | AnchorPosition) -> None:
        """Called on every room movement; walks after the followed player."""
        self.seen(user, destination)
        if user.id != self.following:
            return
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
        self._follow_task = asyncio.create_task(self._walk_after(user.id, FOLLOW_DEBOUNCE))

    async def _walk_after(self, user_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._walk_near(user_id)
        except asyncio.CancelledError:
            pass

    async def _walk_near(self, user_id: str) -> bool:
        pos = self.positions.get(user_id)
        if not isinstance(pos, Position):
            return False  # unknown spot, or sitting on furniture
        await self.host.highrise.walk_to(Position(pos.x + FOLLOW_GAP, pos.y, pos.z, pos.facing))
        return True

    # ---- actions -------------------------------------------------------

    def _target(self, speaker: User, ref: str | None, allow_all: bool = False):
        """Resolve 'me' / 'bot' / 'all' / a username, enforcing permissions.

        Returns a User, "bot", "all", or a Result explaining the refusal.
        """
        ref = (ref or "me").strip().lower().lstrip("@")
        if ref in SELF_WORDS or ref == speaker.username.lower():
            return speaker
        if ref in BOT_WORDS or ref == self.bot_name.lower():
            return "bot"
        if not self.is_owner(speaker):
            return Result(False, "I can only do that for you or me. My owners can pick other players.")
        if ref in ALL_WORDS:
            return "all" if allow_all else Result(False, "I can't do that for everyone.")
        user = self.find_user(ref)
        return user or Result(False, f"I don't see {ref} in the room.")

    async def emote(self, speaker: User, ref: str | int, target: str | None = None) -> Result:
        emote = self.emotes.find(ref)
        if emote is None:
            return Result(False, f"I don't know emote {ref}. Try 1-{len(self.emotes.emotes)} or a name.")
        who = self._target(speaker, target, allow_all=True)
        if isinstance(who, Result):
            return who
        if who == "bot":
            await self.host.highrise.send_emote(emote.id)
            return Result(True, f"*does {emote.name}*")
        if who == "all":
            for uid in list(self.users):
                if uid != self.bot_user_id:
                    await self.host.highrise.send_emote(emote.id, uid)
            return Result(True, f"Everyone: {emote.name}!")
        await self.host.highrise.send_emote(emote.id, who.id)
        return Result(True, f"{emote.number}. {emote.name} for {who.username}")

    async def walk(self, speaker: User, target: str | None = None) -> Result:
        who = self._target(speaker, target)
        if isinstance(who, Result):
            return who
        if who == "bot":
            return Result(False, "I'm already here.")
        if not await self._walk_near(who.id):
            return Result(False, f"I can't see where {who.username} is standing.")
        return Result(True, f"Coming, {who.username}!")

    async def follow(self, speaker: User, target: str | None = None) -> Result:
        who = self._target(speaker, target)
        if isinstance(who, Result):
            return who
        if who == "bot":
            return Result(False, "I can't follow myself.")
        self.stop_following()
        self.following = who.id
        await self._walk_near(who.id)
        return Result(True, f"Following {who.username}. Say '{self.bot_name} stop' to stop.")

    async def stop(self, speaker: User) -> Result:
        if self.following is None:
            return Result(True, "I'm not following anyone.")
        if self.following != speaker.id and not self.is_owner(speaker):
            return Result(False, "Only the person I'm following or my owners can stop me.")
        self.stop_following()
        return Result(True, "Stopped. I'll stay here.")

    async def react(self, speaker: User, reaction: str, target: str | None = None) -> Result:
        reaction = (reaction or "").lower()
        if reaction not in REACTIONS:
            return Result(False, f"Reactions: {', '.join(sorted(REACTIONS))}")
        who = self._target(speaker, target)
        if isinstance(who, Result):
            return who
        if who == "bot":
            return Result(False, "I can't react to myself.")
        await self.host.highrise.react(reaction, who.id)
        return Result(True, f"Sent {reaction} to {who.username}")

    async def run(self, speaker: User, action: dict) -> Result:
        """Run one validated action dict, e.g. {"type": "emote", "emote": 65, "target": "me"}."""
        kind = str(action.get("type", "")).lower()
        try:
            if kind == "emote":
                return await self.emote(speaker, action.get("emote", ""), action.get("target"))
            if kind == "walk":
                return await self.walk(speaker, action.get("to") or action.get("target"))
            if kind == "follow":
                return await self.follow(speaker, action.get("who") or action.get("target"))
            if kind == "stop":
                return await self.stop(speaker)
            if kind == "react":
                return await self.react(speaker, action.get("reaction", ""), action.get("to") or action.get("target"))
        except Exception as exc:  # one failed game call must not kill the chat handler
            log.exception("Action %s failed", action)
            return Result(False, f"That didn't work ({exc.__class__.__name__}).")
        return Result(False, f"I can't do '{kind}'.")
