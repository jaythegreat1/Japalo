"""Command handlers, grouped by concern.

bot.py used to be one 1200-line file with every command handler inline.
It's now a thin core (event hooks + dispatch table) that mixes in these
five files, each owning one slice of the bot's behavior:

  emote_commands.py       emote list/search/play/loop/favorites/capture
  game_commands.py        the five minigames, scoring, leaderboards
  economy_commands.py     tips, VIP, profile, wallet reinvestment
  moderation_commands.py  warnings, kick/ban/mute, freeze, mod grants
  admin_commands.py       !config settings storage + cooldown gate
  help_commands.py        !help
  interaction_commands.py !punch / !slap / !explode two-player emotes
  command_builder.py      AI-built custom commands: design, test, save, run
  ai_commands.py          "Japalo ..." AI chat + AI-driven actions (follow, emotes, ...)

Each Mixin only calls methods it owns plus a small shared surface from the
core class: self.highrise, self.storage, self.catalog, self._settings,
self._setting_int/_setting_float, self._is_staff, self._find_room_user,
and self._voice (personality helper). Because HighriseRoomBot inherits
from every mixin, `self.<anything>` still resolves normally at runtime —
splitting files never means splitting the object.
"""
