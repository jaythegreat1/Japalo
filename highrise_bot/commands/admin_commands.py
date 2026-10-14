from __future__ import annotations

import time

from highrise import User

from .. import personality
from ..constants import GAME_NAMES, SETTINGS_SCHEMA
from ..logging_config import get_logger

logger = get_logger(__name__)


class AdminCommandsMixin:
    """!config (room-dev-only settings view/edit) and the small helpers
    every other mixin leans on: typed setting lookups and the per-user
    command cooldown gate.

    Depends on the core class for: self.highrise, self.storage,
    self._settings, self.room_owner_id, self._command_cooldowns, self._voice.
    """

    def _setting_int(self, key: str) -> int:
        return int(self._settings.get(key, SETTINGS_SCHEMA[key][1]))

    def _setting_float(self, key: str) -> float:
        return float(self._settings.get(key, SETTINGS_SCHEMA[key][1]))

    async def _consume_command_cooldown(self, user_id: str) -> bool:
        cooldown = self._setting_float("command_cooldown_seconds")
        now = time.monotonic()
        last = self._command_cooldowns.get(user_id, 0.0)
        if cooldown > 0 and now - last < cooldown:
            return False
        self._command_cooldowns[user_id] = now
        return True

    async def _handle_config(self, user: User, args: list[str]) -> None:
        if user.id != self.room_owner_id:
            await self.highrise.send_whisper(user.id, "Only the room dev can view or change settings.")
            return

        if not args:
            lines = [f"{key} = {self._settings[key]}" for key in SETTINGS_SCHEMA]
            await self.highrise.send_whisper(
                user.id,
                "Current settings (!config set <key> <value>):\n" + "\n".join(lines),
            )
            return

        if args[0].casefold() != "set" or len(args) < 3:
            await self.highrise.send_whisper(user.id, "Usage: !config   OR   !config set <key> <value>")
            return

        key = args[1].casefold()
        value = " ".join(args[2:])
        if key not in SETTINGS_SCHEMA:
            known = ", ".join(SETTINGS_SCHEMA)
            await self.highrise.send_whisper(user.id, f"Unknown setting '{key}'. Known settings: {known}")
            return

        value_type, _default = SETTINGS_SCHEMA[key]
        if key == "enabled_games":
            requested = {g.strip() for g in value.split(",") if g.strip()}
            unknown = requested - set(GAME_NAMES)
            if unknown or not requested:
                await self.highrise.send_whisper(
                    user.id,
                    f"enabled_games must be a comma-separated list from: {', '.join(GAME_NAMES)}",
                )
                return
        elif key == "personality":
            if value.casefold() not in {"on", "off"}:
                await self.highrise.send_whisper(user.id, "personality must be 'on' or 'off'.")
                return
            value = value.casefold()
        else:
            try:
                value_type(value)
            except ValueError:
                await self.highrise.send_whisper(
                    user.id, f"'{value}' is not a valid {value_type.__name__} for {key}."
                )
                return

        await self.storage.set_setting(key, value)
        self._settings[key] = value
        logger.info("%s changed setting %s = %s", user.username, key, value)
        text = self._voice(
            personality.CONFIG_CHANGE_MESSAGES,
            f"Updated {key} = {value}",
            key=key,
            value=value,
        )
        await self.highrise.send_whisper(user.id, text)
