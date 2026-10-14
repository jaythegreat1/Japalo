from __future__ import annotations

import time

from highrise import RoomPermissions, User
from highrise.models import Error, Position

from .. import personality
from ..logging_config import get_logger

logger = get_logger(__name__)


class ModerationCommandsMixin:
    """Automatic spam/word filters, the shared warning counter and its
    escalation (auto-mute at 3, auto-kick at 5), manual !warn/!ban/!kick/
    !mute/!unban, soft !freeze/!unfreeze, !setmod/!delmod, and the staff
    check every gated command relies on.

    Depends on the core class for: self.highrise, self.storage,
    self.spam_tracker, self.word_filter, self._voice, self._setting_int,
    self._setting_float, self._find_room_user, self.room_owner_id,
    self._moderator_cache, self._frozen_users.
    """

    async def _apply_moderation_filters(self, user: User, text: str) -> None:
        is_spam = self.spam_tracker.record(
            user.id,
            window_seconds=self._setting_float("spam_window_seconds"),
            threshold=self._setting_int("spam_message_threshold"),
        )
        matched_phrase = self.word_filter.matches(text)
        if not is_spam and matched_phrase is None:
            return

        reason = "sending messages too quickly" if is_spam else "using blocked language"
        await self._issue_warning(user, reason, source="auto-filter")

    async def _issue_warning(
        self,
        target: User,
        reason: str,
        source: str = "manual",
        actor_id: str | None = None,
    ) -> int:
        count = await self.storage.record_warning(
            target.id, reason, source=source, actor_id=actor_id
        )
        warn_text = self._voice(
            personality.WARNING_MESSAGES,
            f"Warning {count}: {reason}. Escalation: 3 warnings = mute, "
            "5 warnings = kick.",
            username=target.username,
            count=count,
            reason=reason,
        )
        await self.highrise.send_whisper(target.id, warn_text)
        if count == 3:
            duration = self._setting_int("auto_mute_seconds")
            try:
                await self.highrise.moderate_room(target.id, "mute", duration)
                mute_text = self._voice(
                    personality.AUTO_MUTE_MESSAGES,
                    f"{target.username} was automatically muted for {duration} "
                    "seconds after reaching 3 warnings.",
                    username=target.username,
                    duration=duration,
                )
                await self.highrise.chat(mute_text)
            except Exception:
                logger.exception("Warning escalation mute failed for %s", target.id)
        elif count >= 5:
            try:
                await self.highrise.moderate_room(target.id, "kick")
                kick_text = self._voice(
                    personality.AUTO_KICK_MESSAGES,
                    f"{target.username} was kicked after reaching 5 warnings.",
                    username=target.username,
                )
                await self.highrise.chat(kick_text)
                await self.storage.reset_warnings(target.id)
            except Exception:
                logger.exception("Warning escalation kick failed for %s", target.id)
        return count

    async def _handle_warning_command(
        self, actor: User, action: str, args: list[str]
    ) -> None:
        if action == "warnings":
            target = actor
            if args:
                if not await self._is_staff(actor.id):
                    await self.highrise.send_whisper(
                        actor.id, "Only staff can inspect another user's warnings."
                    )
                    return
                target = await self._find_room_user(args[0])
                if target is None:
                    await self.highrise.send_whisper(actor.id, "That user is not in the room.")
                    return
            count = await self.storage.get_warning_count(target.id)
            await self.highrise.send_whisper(
                actor.id, f"{target.username} has {count} active warning(s)."
            )
            return
        if not await self._is_staff(actor.id):
            await self.highrise.send_whisper(
                actor.id, "Only the room dev or a moderator can warn users."
            )
            return
        if len(args) < 1:
            await self.highrise.send_whisper(actor.id, "Usage: !warn @name [reason].")
            return
        target = await self._find_room_user(args[0])
        if target is None:
            await self.highrise.send_whisper(actor.id, "That user is not in the room.")
            return
        if target.id in {self.room_owner_id, getattr(self.highrise, "my_id", None)}:
            await self.highrise.send_whisper(actor.id, "The room owner and bot cannot be warned.")
            return
        count = await self._issue_warning(
            target,
            " ".join(args[1:]).strip() or "unspecified reason",
            source="manual",
            actor_id=actor.id,
        )
        logger.info("%s warned %s; count=%s", actor.username, target.username, count)

    async def _handle_moderation(
        self, actor: User, action: str, args: list[str]
    ) -> None:
        if not await self._is_staff(actor.id):
            await self.highrise.send_whisper(actor.id, "Only the room dev or a moderator can use that command.")
            return
        target = await self._find_room_user(args[0] if args else "")
        if target is None:
            await self.highrise.send_whisper(actor.id, "Use a current room username such as !kick @PlayerName.")
            return
        if target.id in {self.room_owner_id, getattr(self.highrise, "my_id", None)}:
            await self.highrise.send_whisper(actor.id, "The room owner and bot cannot be moderated by this command.")
            return

        duration: int | None = None
        if action == "mute":
            # A duration is mandatory: the API has no "unmute" action, so a
            # mute issued without one would be effectively permanent and
            # unreversible from this bot. Requiring a duration guarantees
            # every mute self-expires.
            if len(args) <= 1:
                await self.highrise.send_whisper(
                    actor.id,
                    "Usage: !mute @PlayerName <seconds>. A duration is "
                    "required so the mute always expires on its own.",
                )
                return
            try:
                duration = int(args[1])
            except ValueError:
                duration = 0
            if duration <= 0 or duration > 86_400:
                await self.highrise.send_whisper(actor.id, "Mute duration must be between 1 and 86400 seconds.")
                return

        await self.highrise.moderate_room(target.id, action, duration)
        if action in {"kick", "ban"}:
            await self.storage.reset_warnings(target.id)
        await self.storage.record_moderation(actor.id, target.id, action, duration)
        logger.info("%s used %s on %s", actor.username, action, target.username)
        text = self._voice(
            personality.MOD_ACTION_MESSAGES,
            f"{actor.username} used {action} on {target.username}.",
            actor=actor.username,
            action=action,
            target=target.username,
        )
        await self.highrise.chat(text)

    async def _handle_freeze(self, actor: User, action: str, args: list[str]) -> None:
        if not await self._is_staff(actor.id):
            await self.highrise.send_whisper(actor.id, "Only staff can use soft-freeze.")
            return
        target = await self._find_room_user(args[0] if args else "")
        if target is None:
            await self.highrise.send_whisper(actor.id, "Use !freeze @PlayerName.")
            return
        if action == "unfreeze":
            self._frozen_users.pop(target.id, None)
            text = self._voice(
                personality.UNFREEZE_MESSAGES,
                f"{target.username} is unfrozen.",
                target=target.username,
            )
            await self.highrise.send_whisper(actor.id, text)
            return
        response = await self.highrise.get_room_users()
        if isinstance(response, Error):
            await self.highrise.send_whisper(actor.id, "Could not read room positions.")
            return
        position = next(
            (pos for room_user, pos in response.content if room_user.id == target.id),
            None,
        )
        if not isinstance(position, Position):
            await self.highrise.send_whisper(
                actor.id,
                "That user has no floor position to pin. Soft-freeze is only an "
                "approximation and is not a real server-side freeze.",
            )
            return
        self._frozen_users[target.id] = position
        text = self._voice(
            personality.FREEZE_MESSAGES,
            f"Soft-freeze enabled for {target.username}. It uses continuous "
            "teleport-back and is not a real native freeze.",
            target=target.username,
        )
        await self.highrise.send_whisper(actor.id, text)

    async def _handle_moderator_change(
        self, actor: User, grant: bool, args: list[str]
    ) -> None:
        if actor.id != self.room_owner_id:
            await self.highrise.send_whisper(actor.id, "Only the room dev can change moderators.")
            return
        target = await self._find_room_user(args[0] if args else "")
        if target is None:
            await self.highrise.send_whisper(actor.id, "Use a current room username such as !setmod @PlayerName.")
            return
        await self.highrise.change_room_privilege(
            target.id, RoomPermissions(moderator=grant)
        )
        self._moderator_cache.pop(target.id, None)
        pool = personality.MODERATOR_GRANT_MESSAGES if grant else personality.MODERATOR_REVOKE_MESSAGES
        status = "now a moderator" if grant else "no longer a moderator"
        text = self._voice(pool, f"{target.username} is {status}.", target=target.username)
        await self.highrise.chat(text)

    async def _is_staff(self, user_id: str) -> bool:
        if user_id == self.room_owner_id:
            return True

        cached = self._moderator_cache.get(user_id)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]

        privilege = await self.highrise.get_room_privilege(user_id)
        is_moderator = not isinstance(privilege, Error) and bool(
            privilege.moderator
        )
        self._moderator_cache[user_id] = (now + 30, is_moderator)
        return is_moderator
