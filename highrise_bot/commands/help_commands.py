from __future__ import annotations

from highrise import User

from .. import personality

# Each category: (display title, staff-only, [lines]). Lines are shown
# as-is, one per line, in !help <category>. Keeping this as data (not
# hardcoded prose) means adding a command is a one-line edit here, not a
# rewrite of a paragraph.
HELP_CATEGORIES: dict[str, tuple[str, bool, list[str]]] = {
    "emotes": (
        "Emotes",
        False,
        [
            "<number> — play that emote on yourself (see the numbers with !emotelist)",
            "!emotelist [rarity] — full numbered list, optionally filtered "
            "(common, uncommon, rare, epic, none_, unknown)",
            "!findemote <text> — search emotes by name",
            "!surprise [rarity] — play a random emote, optionally filtered",
            "!fav — list your saved favorites",
            "!fav <slot 1-9> — play a saved favorite",
            "!fav <slot> <number> — save an emote to that slot",
            "!fav remove <slot> — clear a favorite slot",
            "stop — stop your current emote loop",
            "!emote @name <number> — play an emote on someone else "
            "(VIP tippers at 100g+ lifetime, or staff)",
        ],
    ),
    "ai": (
        "Talk to Japalo (AI)",
        False,
        [
            "Start any message with Japalo — other chat is ignored by the AI",
            "Japalo <anything> — chat with the AI; it can also act, e.g. "
            "'Japalo come dance with me'",
            "Japalo emote 65 / Japalo emote moonwalk — loop an emote (stop to end)",
            "Japalo follow me / Japalo stop / Japalo come here",
            "Japalo send heart to @name — reactions: clap, heart, thumbs, wave, wink",
            "Japalo status / reset / facts — AI status, forget our chat, learned facts",
            "Staff: Japalo learn <fact>, Japalo forget <n>, Japalo model <name>, "
            "Japalo follow @name, Japalo emote 65 on @name",
            "Whisper the bot to chat privately",
        ],
    ),
    "games": (
        "Games",
        False,
        [
            "!games — see which minigames are enabled right now",
            "!trivia, !scramble, !math, !riddle, !guessnumber — start that minigame "
            "(only one runs room-wide at a time)",
            "!answer <text> — answer the active round (Guess the Number "
            "instead takes a plain number typed in chat)",
            "!score — your point total",
            "!leaderboard [daily|weekly|all] — top 5 (defaults to all-time)",
        ],
    ),
    "economy": (
        "Tips & profile",
        False,
        [
            "!profile — your level, XP, visits, points, and VIP status",
            "!tipleaderboard — top 5 lifetime tippers",
            "Tipping the bot 100g total unlocks VIP (!emote @name <number>)",
        ],
    ),
    "mod": (
        "Staff",
        True,
        [
            "!warn @name <reason> — issue a warning (3 = auto-mute, 5 = auto-kick)",
            "!warnings [@name] — check a warning count",
            "!kick @name, !ban @name, !unban @name",
            "!mute @name <seconds> — duration is required, mutes always self-expire",
            "!freeze @name / !unfreeze @name — best-effort soft-freeze, not a "
            "native Highrise freeze",
            "!endgame — force-end the active minigame round",
            "!testemote <number> — play an emote once on yourself, no loop",
            "!emotecapture on|off|status — log unrecognized emote ids performed live",
            "!capturedemotes — review what's been captured",
            "!catalog audit — run the emote catalog audit report",
        ],
    ),
    "admin": (
        "Room dev only",
        True,
        [
            "!setmod @name / !delmod @name — grant or revoke moderator",
            "!config — view every tunable setting",
            "!config set <key> <value> — change one, e.g. "
            "!config set personality off",
        ],
    ),
}

CATEGORY_ALIASES: dict[str, str] = {
    "japalo": "ai",
    "chat": "ai",
    "emote": "emotes",
    "game": "games",
    "tip": "economy",
    "tips": "economy",
    "profile": "economy",
    "staff": "mod",
    "moderation": "mod",
    "moderator": "mod",
    "dev": "admin",
    "owner": "admin",
    "config": "admin",
}


class HelpMixin:
    """!help / !commands, plus !help <category> for a focused sub-page.
    Depends on the core class for self.highrise, self._voice, self._is_staff.
    """

    async def _send_help(self, user: User, args: list[str] | None = None) -> None:
        args = args or []
        if args:
            await self._send_help_category(user, args[0])
            return

        is_staff = await self._is_staff(user.id)
        intro = self._voice(personality.HELP_INTROS, "Commands:")
        lines = [f"{intro} (!help <category> for details)"]
        for key, (title, staff_only, _entries) in HELP_CATEGORIES.items():
            if staff_only and not is_staff:
                continue
            lines.append(f"• !help {key} — {title}")
        await self.highrise.send_whisper(user.id, "\n".join(lines))

    async def _send_help_category(self, user: User, requested: str) -> None:
        key = CATEGORY_ALIASES.get(requested.casefold(), requested.casefold())
        category = HELP_CATEGORIES.get(key)
        if category is None:
            known = ", ".join(HELP_CATEGORIES)
            await self.highrise.send_whisper(
                user.id, f"No help category '{requested}'. Try: {known}."
            )
            return

        title, staff_only, entries = category
        if staff_only and not await self._is_staff(user.id):
            await self.highrise.send_whisper(
                user.id, "That help category is staff-only."
            )
            return

        body = "\n".join(f"- {entry}" for entry in entries)
        await self.highrise.send_whisper(user.id, f"{title}:\n{body}")
