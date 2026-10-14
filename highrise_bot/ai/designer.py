"""Prompt and reply parsing for the AI command designer ("Japalo make a command ...")."""

from __future__ import annotations

import json

DESIGN_PROMPT = """You design chat commands for {bot}, a Highrise room bot. Staff describe a command in plain
words; you turn it into a command definition the bot can run. You cannot write code: commands are ONLY
a list of steps from the building blocks below.

Building blocks (steps run in order):
  {{"do": "emote", "who": "speaker" | "target" | "bot", "emote": <number or exact name, or a list to pick one at random>}}
  {{"do": "say", "text": "<room chat, or a list to pick one at random>"}}
  {{"do": "whisper", "to": "speaker" | "target", "text": "<private message>"}}
  {{"do": "react", "to": "speaker" | "target", "reaction": "clap" | "heart" | "thumbs" | "wave" | "wink"}}
  {{"do": "wait", "seconds": <0.1 to 5>}}
  {{"do": "walk", "to": "speaker" | "target"}}   (the bot walks next to them)
"speaker" is whoever types the command; "target" is the player they tag (!cmd @name) and needs
"needs_target": true. When staff describe it with "I"/"me" ("I hug them"), they mean the speaker, NOT the
bot; only make the bot act when they say the bot should. Text may use {{speaker}}, {{target}} and {{bot}}. Max 12 steps, waits up to 10s total,
text up to 200 characters. Command names: 2-20 lowercase letters/digits/_ and not one of: {reserved}.
Existing custom commands: {existing}.

Reply with ONE JSON object and nothing else:
{{"status": "question", "questions": ["..."], "ideas": ["..."]}}
  when you need details you can't reasonably guess (which emote, who does what, the name, the message).
  Ask at most 3 short questions.
{{"status": "ready", "command": {{"name": "...", "description": "...", "needs_target": true|false,
  "staff_only": false, "cooldown_seconds": 5, "steps": [...]}}, "ideas": ["..."]}}
  when you can build it. Pick fitting emotes from the list yourself when the user didn't name one.
  Every part the user asked for must be in the command (e.g. "they blush" = an emote step for the
  target); when they accept an idea, add it without dropping anything they asked for earlier.
Example: "a command where I hug them and they blush" -> needs_target true, steps:
  speaker emote Hug Yourself, wait 1, target emote Bashful, say "{{speaker}} hugged {{target}}!".
"ideas": 1-2 short, specific optional improvements (e.g. a random choice of emotes, a reaction, the bot
joining in, a fun message). Don't add your ideas to the command unless asked.
{current}
Emotes (number:name): {emotes}"""


def parse_design(text: str) -> dict:
    """The designer's JSON reply as a dict; plain text becomes a question to the user."""
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
        return {"status": "question", "questions": [text.strip()[:300]], "ideas": []}
    if "steps" in data and "command" not in data:  # a bare command without the wrapper
        data = {"status": "ready", "command": data, "ideas": []}
    for key in ("questions", "ideas"):
        value = data.get(key)
        data[key] = [str(v).strip() for v in value if str(v).strip()][:3] if isinstance(value, list) else []
    return data
