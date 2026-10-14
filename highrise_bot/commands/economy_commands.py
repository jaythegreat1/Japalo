from __future__ import annotations

import time

from highrise import User
from highrise.models import Error

from .. import personality
from ..logging_config import get_logger

logger = get_logger(__name__)


class EconomyCommandsMixin:
    """Tip processing (called from on_tip), VIP unlock, !tipleaderboard,
    !tips, !profile, and optional wallet reinvestment into room boosts or
    voice time.

    Depends on the core class for: self.highrise, self.storage, self._voice,
    self._setting_int, self._is_staff, self._find_room_user,
    self._last_auto_spend.
    """

    async def _handle_tip(self, sender: User, tip: object) -> None:
        """Called from on_tip once we know the receiver is this bot."""
        await self.storage.remember_username(sender.id, sender.username)
        amount = int(getattr(tip, "amount", 0))
        if getattr(tip, "type", "") != "gold" or amount <= 0:
            await self.highrise.chat(f"Thank you, {sender.username}, for the tip!")
            return
        previous = await self.storage.get_tip_total(sender.id)
        total, _room_total = await self.storage.add_tip(sender.id, amount)

        thanks = self._voice(
            personality.TIP_THANKS_MESSAGES,
            f"Thank you {sender.username} for the {amount}g tip!",
            username=sender.username,
            amount=amount,
        )
        suffix = self._voice(
            personality.TIP_TOTAL_SUFFIXES,
            f" You've tipped {total}g total.",
            total=total,
        )
        await self.highrise.chat(f"{thanks}{suffix}")

        if previous < 100 <= total:
            vip_line = self._voice(
                personality.VIP_UNLOCK_MESSAGES,
                f"{sender.username} unlocked VIP for tipping the bot 100g!",
                username=sender.username,
            )
            await self.highrise.chat(vip_line)
        await self._maybe_spend_wallet()

    async def _send_tip_leaderboard(self, user: User | None = None, args: list[str] | None = None) -> None:
        top = await self.storage.top_tippers(limit=5)
        if not top:
            await self.highrise.chat("No tips recorded yet — be the first VIP supporter!")
            return
        lines = []
        for index, (user_id, gold) in enumerate(top, 1):
            name = await self.storage.get_username(user_id) or user_id
            vip = " VIP" if gold >= 100 else ""
            lines.append(f"{index}. {name} — {gold}g{vip}")
        await self.highrise.chat("Tip leaderboard:\n" + "\n".join(lines))

    async def _send_profile(self, user: User, args: list[str]) -> None:
        target = user
        if args:
            if not await self._is_staff(user.id):
                await self.highrise.send_whisper(
                    user.id, "Only staff can inspect another user's profile."
                )
                return
            target = await self._find_room_user(args[0])
            if target is None:
                await self.highrise.send_whisper(user.id, "That user is not in the room.")
                return
        xp = await self.storage.get_xp(target.id)
        joins = await self.storage.get_join_count(target.id)
        points = await self.storage.get_score(target.id)
        tipped = await self.storage.get_tip_total(target.id)
        level = 1 + xp // 100
        vip = "yes" if tipped >= 100 else "no"
        await self.highrise.send_whisper(
            user.id,
            f"{target.username}: level {level} ({xp} XP), {joins} visit(s), "
            f"{points} game point(s), tipped {tipped}g, VIP: {vip}.",
        )

    async def _maybe_spend_wallet(self) -> None:
        """Optionally reinvest bot-earned gold using the real SDK requests.

        Disabled by default. The minimum balance and cooldown keep a busy tip
        stream from making a request on every tip.
        """
        if time.monotonic() - self._last_auto_spend < 60:
            return
        boost_on = self._settings.get("auto_room_boost", "false").casefold() == "true"
        voice_on = self._settings.get("auto_voice_time", "false").casefold() == "true"
        if not boost_on and not voice_on:
            return
        try:
            wallet = await self.highrise.get_wallet()
            if isinstance(wallet, Error):
                logger.warning("Could not read bot wallet for auto-spend: %s", wallet)
                return
            gold = sum(
                int(getattr(item, "amount", 0))
                for item in wallet.content
                if getattr(item, "type", "") == "gold"
            )
            if gold < self._setting_int("auto_spend_min_gold"):
                return
            self._last_auto_spend = time.monotonic()
            if boost_on:
                result = await self.highrise.buy_room_boost("bot_wallet_only", 1)
                logger.info("Auto-spend room boost result: %s", result)
            if voice_on:
                result = await self.highrise.buy_voice_time("bot_wallet_only")
                logger.info("Auto-spend voice time result: %s", result)
        except Exception:
            logger.exception("Auto-spend request failed")
