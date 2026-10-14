from __future__ import annotations

import json

from highrise import User

from .. import personality
from ..constants import CATALOG_PATH, RARITY_FILTERS
from ..emote_loop import TARGET_OWNERSHIP_ERROR_MARKER
from ..emotes import Emote
from ..logging_config import get_logger

logger = get_logger(__name__)


class EmoteCommandsMixin:
    """!emotelist, !emote, !surprise, !findemote, !fav, !testemote,
    !emotecapture, !capturedemotes, !catalog, stop, and the emote-loop
    error/rejection handling behind all of them.

    Depends on the core class for: self.highrise, self.catalog,
    self.emote_loops, self.storage, self._catalog_write_lock,
    self._known_emote_ids, self._voice, self._is_staff,
    self._find_room_user, self._run_emote_number (also defined here).
    """

    async def _send_emote_list(self, user: User, args: list[str]) -> None:
        rarity = args[0].casefold() if args else None
        if rarity is not None and rarity not in RARITY_FILTERS:
            await self.highrise.send_whisper(
                user.id,
                "Filter must be common, none_, unknown, uncommon, rare, or epic.",
            )
            return
        pages = self.catalog.pages(rarity=rarity)
        for index, page in enumerate(pages, 1):
            prefix = f"Emotes ({len(self.catalog)}) — page {index}/{len(pages)}:\n"
            await self.highrise.send_whisper(user.id, prefix + page)

    async def _handle_emote_command(self, user: User, args: list[str]) -> None:
        target = user
        if args and args[0].startswith("@"):
            if len(args) < 2 or not args[1].isdigit():
                await self.highrise.send_whisper(
                    user.id, "Use !emote @PlayerName <number>."
                )
                return
            target = await self._find_room_user(args[0])
            if target is None:
                await self.highrise.send_whisper(user.id, "That user is not in the room.")
                return
            if not await self._can_emote_others(user.id):
                await self.highrise.send_whisper(
                    user.id, "Only room staff or 100g VIP tippers can emote others."
                )
                return
            args = args[1:]
        if not args or not args[0].isdigit():
            await self.highrise.send_whisper(
                user.id, "Use !emote <number>. See the exact numbered list with !emotelist."
            )
            return
        await self._run_emote_number(user, int(args[0]), target=target)

    async def _run_emote_number(
        self, user: User, number: int, target: User | None = None
    ) -> None:
        target = target or user
        emote = self.catalog.get_by_number(number)
        if emote is None:
            await self.highrise.send_whisper(
                user.id, f"Emote number {number} is not in the configured list."
            )
            return

        async def send(emote_id: str, target_user_id: str) -> None:
            try:
                await self.highrise.send_emote(emote_id, target_user_id)
            except Exception as error:
                raise RuntimeError(
                    f"emote #{number} {emote.name!r} ({emote_id}): {error}"
                ) from error

        await self.emote_loops.start(
            target.id,
            emote,
            send,
            on_error=lambda target_user_id, error: self._handle_emote_loop_error(
                target_user_id, error, emote
            ),
        )
        if target.id != user.id:
            text = self._voice(
                personality.EMOTE_LOOP_OTHER_MESSAGES,
                f"Looping {emote.name} on {target.username}. Type stop to stop.",
                emote=emote.name,
                target=target.username,
            )
        else:
            text = self._voice(
                personality.EMOTE_LOOP_MESSAGES,
                f"Looping {emote.name}. Type stop to stop.",
                emote=emote.name,
            )
        await self.highrise.send_whisper(user.id, text)

    async def _surprise_emote(self, user: User, args: list[str]) -> None:
        rarity = args[0].casefold() if args else None
        if rarity and rarity not in RARITY_FILTERS:
            await self.highrise.send_whisper(user.id, "Unknown rarity filter.")
            return
        choice = self.catalog.random(rarity=rarity)
        if choice is None:
            await self.highrise.send_whisper(user.id, "No emotes match that filter.")
            return
        number, emote = choice
        text = self._voice(
            personality.SURPRISE_PICK_MESSAGES,
            f"Surprise pick: #{number} {emote.name} [{emote.rarity}]",
            number=number,
            name=emote.name,
            rarity=emote.rarity,
        )
        await self.highrise.send_whisper(user.id, text)
        await self._run_emote_number(user, number)

    async def _find_emote(self, user: User, args: list[str]) -> None:
        query = " ".join(args).strip()
        if not query:
            await self.highrise.send_whisper(user.id, "Usage: !findemote <name or ID fragment>.")
            return
        matches = self.catalog.filter(query=query)
        if not matches:
            await self.highrise.send_whisper(user.id, "No matching emotes found.")
            return
        await self.highrise.send_whisper(
            user.id,
            "Matches:\n" + "\n".join(
                f"{number}. {emote.name} [{emote.rarity}]"
                for number, emote in matches[:30]
            ),
        )

    async def _handle_favorite(self, user: User, args: list[str]) -> None:
        if not args:
            favorites = await self.storage.list_favorites(user.id)
            if not favorites:
                await self.highrise.send_whisper(
                    user.id, "No favorites. Save one with !fav <slot> <emote number>."
                )
                return
            await self.highrise.send_whisper(
                user.id,
                "Favorites:\n" + "\n".join(
                    f"{slot}. #{number} {self.catalog.get_by_number(number).name}"
                    for slot, number in favorites
                    if self.catalog.get_by_number(number) is not None
                ),
            )
            return
        if args[0].casefold() in {"remove", "delete"}:
            if len(args) != 2 or not args[1].isdigit():
                await self.highrise.send_whisper(user.id, "Usage: !fav remove <slot>.")
                return
            await self.storage.delete_favorite(user.id, int(args[1]))
            await self.highrise.send_whisper(user.id, "Favorite removed.")
            return
        if not args[0].isdigit():
            await self.highrise.send_whisper(user.id, "Usage: !fav <slot> [emote number].")
            return
        slot = int(args[0])
        if not 1 <= slot <= 9:
            await self.highrise.send_whisper(user.id, "Favorite slots are 1 through 9.")
            return
        if len(args) == 1:
            number = await self.storage.get_favorite(user.id, slot)
            if number is None:
                await self.highrise.send_whisper(user.id, "That favorite slot is empty.")
                return
            await self._run_emote_number(user, number)
            return
        if len(args) != 2 or not args[1].isdigit():
            await self.highrise.send_whisper(user.id, "Usage: !fav <slot> <emote number>.")
            return
        number = int(args[1])
        if self.catalog.get_by_number(number) is None:
            await self.highrise.send_whisper(user.id, "That emote number is not configured.")
            return
        await self.storage.set_favorite(user.id, slot, number)
        await self.highrise.send_whisper(user.id, f"Saved emote #{number} to favorite {slot}.")

    async def _test_emote(self, user: User, args: list[str]) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can test an emote.")
            return
        if len(args) != 1 or not args[0].isdigit():
            await self.highrise.send_whisper(user.id, "Usage: !testemote <number>.")
            return
        emote = self.catalog.get_by_number(int(args[0]))
        if emote is None:
            await self.highrise.send_whisper(user.id, "That emote number is not configured.")
            return
        await self.highrise.send_emote(emote.emote_id, user.id)
        await self.highrise.send_whisper(user.id, f"Tested {emote.name} once.")

    async def _handle_emote_capture(self, user: User, args: list[str]) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can toggle emote capture.")
            return
        choice = args[0].casefold() if args else "status"
        if choice not in {"on", "off", "status"}:
            await self.highrise.send_whisper(user.id, "Usage: !emotecapture on | off | status.")
            return
        if choice != "status":
            enabled = "true" if choice == "on" else "false"
            self._settings["emote_capture_enabled"] = enabled
            await self.storage.set_setting("emote_capture_enabled", enabled)
            if choice == "off":
                self._captured_this_run.clear()
        state = self._settings.get("emote_capture_enabled", "false")
        await self.highrise.send_whisper(
            user.id,
            f"Emote capture is {'ON' if state == 'true' else 'OFF'}. "
            "While on, any emote performed in the room that isn't in our "
            "catalog gets logged (never guessed) for review with !capturedemotes.",
        )

    async def _send_captured_emotes(self, user: User, args: list[str] | None = None) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only room staff can review captured emotes.")
            return
        captured = await self.storage.list_captured_emotes()
        if not captured:
            await self.highrise.send_whisper(user.id, "No unrecognized emote ids captured yet.")
            return
        lines = [f"{emote_id}" for emote_id, _user_id, _seen_at in captured[:30]]
        await self.highrise.send_whisper(
            user.id,
            f"{len(captured)} captured id(s), newest first:\n" + "\n".join(lines),
        )

    async def _handle_catalog_command(self, user: User, args: list[str]) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(
                user.id, "Only room staff can run catalog audits."
            )
            return
        if len(args) != 1 or args[0].casefold() != "audit":
            await self.highrise.send_whisper(user.id, "Usage: !catalog audit")
            return

        from tools.emote_catalog.catalog_audit import build_report

        report = build_report()
        await self.highrise.send_whisper(
            user.id,
            "Catalog audit:\n"
            f"discovered={report['total_discovered']}, "
            f"source_verified={report['source_verified']}, "
            f"verified_real={report['verified_real_emotes']}, "
            f"configured={report['configured_runtime_emotes']}\n"
            f"rare={report['rare']}, epic={report['epic']}, "
            f"other_allowed={report['other_allowed_rarity']}\n"
            f"unreleased_removed={report['unreleased']}, "
            f"future={report['future']}, invalid={report['invalid']}, "
            f"purchase_locked={report['requires_purchase']}, "
            f"needs_review={report['needs_review']}",
        )

    async def _can_emote_others(self, user_id: str) -> bool:
        return await self._is_staff(user_id) or await self.storage.get_tip_total(user_id) >= 100

    async def _handle_emote_loop_error(
        self, user_id: str, error: Exception, emote: Emote | None = None
    ) -> None:
        logger.warning("Emote loop stopped for %s: %s", user_id, error)
        removed = False
        if (
            emote is not None
            and TARGET_OWNERSHIP_ERROR_MARKER in str(error).casefold()
        ):
            removed = await self._remove_rejected_emote(emote)
        await self.highrise.send_whisper(
            user_id,
            (
                f"{emote.name} was removed from the emote list because Highrise "
                "rejected it for the target user."
                if removed
                else "Your emote loop stopped because Highrise rejected the "
                f"emote after retries: {error}"
            ),
        )

    async def _remove_rejected_emote(self, emote: Emote) -> bool:
        """Persistently remove an emote Highrise rejected for a target user."""
        async with self._catalog_write_lock:
            updated, removed = self.catalog.without_id(emote.emote_id)
            if not removed:
                return False
            try:
                CATALOG_PATH.write_text(
                    json.dumps(
                        [
                            {
                                "name": item.name,
                                "id": item.emote_id,
                                "rarity": item.rarity,
                                "duration_seconds": item.duration_seconds,
                            }
                            for item in updated._emotes
                        ],
                        indent=2,
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError:
                logger.exception(
                    "Could not persist removal of rejected emote %s",
                    emote.emote_id,
                )
                return False
            self.catalog = updated
            self._known_emote_ids = self.catalog.known_ids()
            logger.warning(
                "Removed rejected emote %s (%s) from %s",
                emote.name,
                emote.emote_id,
                CATALOG_PATH,
            )
            return True

    async def _stop_emote(self, user: User, args: list[str] | None = None) -> None:
        if await self.emote_loops.stop(user.id):
            await self.highrise.send_whisper(user.id, "Your emote loop stopped.")
        else:
            await self.highrise.send_whisper(user.id, "You do not have an emote loop running.")
