"""Fast, AI-free understanding of the common commands.

`parse()` turns the text after "Japalo" into action dicts for `Actor.run()`,
or returns None so the AI handles it.
"""

from __future__ import annotations

import re

_TARGET = r"(?:\s+(?:on|for|to|with)?\s*@?(?P<who>[\w.]+))?"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "stop", "stop following", "stay", "stay here"
    (re.compile(r"^(?:please\s+)?(?:stop(?:\s+following(?:\s+me)?)?|stay(?:\s+here)?|unfollow)\W*$"), "stop"),
    # "follow me", "follow @amy"
    (re.compile(r"^(?:please\s+)?follow(?:\s+@?(?P<who>[\w.]+))?\W*$"), "follow"),
    # "come here", "come to me", "walk to amy", "go to @amy"
    (re.compile(r"^(?:please\s+)?(?:come(?:\s+here|\s+to\s+me)?|(?:walk|go|come)\s+to\s+@?(?P<who>[\w.]+))\W*$"), "walk"),
    # "emote 65", "do emote 65", "i want to do the emote number 65", "do 65 on amy", "make amy do 65"
    (re.compile(
        r"^(?:please\s+)?(?:i\s+want\s+to\s+|let\s+me\s+|can\s+i\s+|make\s+me\s+)?(?:do|play|perform|use)?\s*"
        r"(?:the\s+|an?\s+)?(?:emote|dance)?\s*(?:number|no\.?|#)?\s*(?P<emote>\d{1,3})" + _TARGET + r"\W*$"
    ), "emote"),
    (re.compile(r"^(?:please\s+)?make\s+@?(?P<who>[\w.]+)\s+(?:do\s+)?(?:emote\s+)?(?:number\s+|#)?(?P<emote>\d{1,3})\W*$"), "emote"),
    # "emote macarena", "do the macarena"
    (re.compile(r"^(?:please\s+)?(?:do|play)?\s*(?:the\s+)?emote\s+(?P<emote>[a-z][\w-]*)" + _TARGET + r"\W*$"), "emote"),
    # "send heart to amy", "react heart"
    (re.compile(r"^(?:please\s+)?(?:send|react|give)\s+(?:a\s+)?(?P<reaction>clap|heart|thumbs|wave|wink)" + _TARGET + r"\W*$"), "react"),
]


def parse(text: str) -> list[dict] | None:
    cleaned = " ".join(text.lower().split()).strip(" ,.!?")
    for pattern, kind in _PATTERNS:
        m = pattern.match(cleaned)
        if not m:
            continue
        groups = {k: v for k, v in m.groupdict().items() if v}
        action: dict = {"type": kind}
        if kind == "emote":
            action["emote"] = groups["emote"]
            action["target"] = groups.get("who", "me")
        elif kind in ("follow", "walk"):
            action["target"] = groups.get("who", "me")
        elif kind == "react":
            action["reaction"] = groups["reaction"]
            action["target"] = groups.get("who", "me")
        return [action]
    return None


def is_number_emote(message: str) -> bool:
    """A chat message that is just a number, e.g. '65' (the classic emote-bot shortcut)."""
    return bool(re.fullmatch(r"\s*#?\d{1,3}\s*", message))
