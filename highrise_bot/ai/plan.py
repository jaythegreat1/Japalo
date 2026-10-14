"""The AI's action plan: the prompt that offers room actions, and parsing its reply."""

from __future__ import annotations

import json

MAX_AI_ACTIONS = 3

ACTION_PROMPT = """You also control your own avatar in the room. Reply ONLY with one JSON object:
{{"say": "<short chat reply>", "actions": [<zero or more actions>]}}
Actions you can use:
{{"type": "emote", "emote": <number or name>, "target": "me" | "bot" | "<username>"}}
{{"type": "walk", "to": "me" | "<username>"}}
{{"type": "follow", "who": "me" | "<username>"}}
{{"type": "stop"}}  (stop following / stop the player's emote loop)
{{"type": "react", "reaction": "clap" | "heart" | "thumbs" | "wave" | "wink", "to": "me" | "<username>"}}
"me" is the player talking to you, "bot" is yourself. Only add actions the player asked for or that clearly
fit (e.g. "dance with me" = a dance emote for "bot" and the same for "me"); otherwise use "actions": [].
Emotes (number:name): {emotes}
Players here: {players}"""

SYSTEM_PROMPT = (
    "You are {name}, the resident bot of a Highrise room: witty, warm, a bit chaotic, never mean. "
    "Keep answers short (1-2 sentences) because chat bubbles are small. "
    "Never pretend to be a human moderator, never ask for passwords or gold."
)


def parse_plan(text: str) -> tuple[str, list[dict]]:
    """Read the AI's {"say": ..., "actions": [...]} reply; plain text becomes just a reply."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    data = None
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(raw[start : end + 1])
            except ValueError:
                data = None
    if not isinstance(data, dict):
        return text.strip(), []
    actions = data.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    actions = [a for a in actions if isinstance(a, dict) and a.get("type")][:MAX_AI_ACTIONS]
    return str(data.get("say") or "").strip(), actions
