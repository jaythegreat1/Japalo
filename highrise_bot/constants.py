"""Shared constants: file paths, game metadata, and the !config schema.

Lives on its own so bot.py and every highrise_bot/commands/*.py mixin can
import from it without anyone importing back from bot.py (which would be
a circular import, since bot.py imports the mixins).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / os.environ.get("HIGHRISE_EMOTE_CATALOG", "config/emotes.json")
WORD_FILTER_PATH = ROOT / os.environ.get(
    "HIGHRISE_WORD_FILTER", "config/moderation_words.json"
)
DB_PATH = ROOT / os.environ.get("HIGHRISE_BOT_DB", "data/bot.db")

GAME_NAMES: dict[str, str] = {
    "trivia": "Trivia",
    "scramble": "Word Scramble",
    "math": "Math Blitz",
    "riddle": "Emoji Riddle",
    "guessnumber": "Guess the Number",
}
GAME_TIMEOUTS: dict[str, int] = {
    "trivia": 30,
    "scramble": 45,
    "math": 20,
    "riddle": 45,
    "guessnumber": 60,
}

# Rarity filters accepted by !emotelist / !surprise.
RARITY_FILTERS = frozenset(
    {"common", "none_", "unknown", "uncommon", "rare", "epic"}
)

# key -> (value type, default as string). Backing store for !config.
# Imported lazily-ish: moderation_filters' defaults are needed here, so this
# import happens at module load, same as it did inside the old bot.py.
from .moderation_filters import (  # noqa: E402
    DEFAULT_AUTO_MUTE_SECONDS,
    DEFAULT_SPAM_MESSAGE_THRESHOLD,
    DEFAULT_SPAM_WINDOW_SECONDS,
    DEFAULT_WARNING_MUTE_THRESHOLD,
)

SETTINGS_SCHEMA: dict[str, tuple[type, str]] = {
    "warning_mute_threshold": (int, str(DEFAULT_WARNING_MUTE_THRESHOLD)),
    "auto_mute_seconds": (int, str(DEFAULT_AUTO_MUTE_SECONDS)),
    "spam_window_seconds": (float, str(DEFAULT_SPAM_WINDOW_SECONDS)),
    "spam_message_threshold": (int, str(DEFAULT_SPAM_MESSAGE_THRESHOLD)),
    "command_cooldown_seconds": (float, "1.0"),
    "raid_join_threshold": (int, "8"),
    "raid_window_seconds": (float, "30.0"),
    "raid_kick_enabled": (str, "true"),
    "game_reward_gold": (int, "0"),
    "game_reward_gold_cap": (int, "100"),
    "auto_room_boost": (str, "false"),
    "auto_voice_time": (str, "false"),
    "auto_spend_min_gold": (int, "100"),
    "enabled_games": (str, ",".join(GAME_NAMES)),
    "emote_capture_enabled": (str, "false"),
    # New: personality toggle. "on" = Japalo's full voice everywhere below.
    # "off" = plain, purely-informational text (same tone as the original
    # bot). Room devs who want a quieter room can flip this without losing
    # any functionality.
    "personality": (str, "on"),
}
