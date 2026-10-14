from __future__ import annotations

import asyncio
import random
import time

from highrise import User

from .. import personality
from ..logging_config import get_logger

logger = get_logger(__name__)

VOICE_POOLS = {
    "punch": personality.PUNCH_MESSAGES,
    "slap": personality.SLAP_MESSAGES,
    "explode": personality.EXPLODE_MESSAGES,
}
PLAIN_VERBS = {"punch": "punched", "slap": "slapped", "explode": "exploded"}


class InteractionCommandsMixin:
    """!punch @name, !slap @name, !explode @name.

    !punch / !slap: the speaker plays Punch / Slap and, after a short impact
    delay, the tagged player plays a random falling emote.
    !explode: only the tagged player plays Boo; the speaker does nothing.
    Each emote list is tried in order until Highrise accepts one, so an
    emote a player can't use doesn't break the whole interaction.
    Emote ids and delays live in config/interactions.json.

    Depends on the core class for: self.highrise, self.interactions,
    self._interaction_cooldowns, self._setting_float, self._voice,
    self._find_room_user.
    """

    async def _handle_interaction(self, user: User, action: str, args: list[str]) -> None:
        interaction = self.interactions.get(action)
        if interaction is None:
            return
        if not args:
            await self.highrise.send_whisper(user.id, f"Use !{action} @PlayerName.")
            return
        target = await self._find_room_user(args[0])
        if target is None:
            await self.highrise.send_whisper(user.id, "That user is not in the room.")
            return
        if target.id == user.id:
            await self.highrise.send_whisper(
                user.id, f"You can't {action} yourself. Pick someone: !{action} @PlayerName."
            )
            return

        cooldown = self._setting_float("interaction_cooldown_seconds")
        now = time.monotonic()
        if now - self._interaction_cooldowns.get(user.id, 0.0) < cooldown:
            await self.highrise.send_whisper(
                user.id, f"Easy there — wait a few seconds before the next !{action}."
            )
            return
        self._interaction_cooldowns[user.id] = now

        attack = None
        if interaction.actor_emote_ids:
            attack = await self._send_first_emote(interaction.actor_emote_ids, user.id)
            await asyncio.sleep(interaction.impact_delay_seconds)
        reactions = list(interaction.target_emote_ids)
        if not reactions:
            reactions = list(self.interactions.fall_emote_ids)
            random.shuffle(reactions)
        bot_id = getattr(self.highrise, "my_id", None)
        reaction = await self._send_first_emote(
            reactions, None if target.id == bot_id else target.id
        )

        if reaction is None and (attack is None or not interaction.actor_emote_ids):
            await self.highrise.send_whisper(
                user.id, f"Highrise refused the {action} emotes right now. Try again in a bit."
            )
            return
        plain = f"{user.username} {PLAIN_VERBS.get(action, action)} {target.username}!"
        pool = VOICE_POOLS.get(action)
        text = (
            self._voice(pool, plain, attacker=user.username, target=target.username)
            if pool
            else plain
        )
        await self.highrise.chat(text)

    async def _send_first_emote(self, emote_ids, user_id: str | None) -> str | None:
        """Send the first emote id Highrise accepts; None means the bot itself emotes."""
        for emote_id in emote_ids:
            try:
                if user_id is None:
                    await self.highrise.send_emote(emote_id)
                else:
                    await self.highrise.send_emote(emote_id, user_id)
                return emote_id
            except Exception as error:
                logger.warning("Interaction emote %s refused for %s: %s", emote_id, user_id, error)
        return None
