"""Custom commands built by the AI from staff descriptions ("Japalo make a command ...").

A custom command is data, not code: a short list of steps from a fixed set of
building blocks the bot already knows how to run safely. The AI only ever
produces this JSON; validate() checks it against the emote catalog and the
limits below before it can be tested or saved, so nothing the AI writes is
ever executed as Python.

    {
      "name": "hug",                      # used as !hug
      "description": "Hug someone",
      "needs_target": true,               # usage: !hug @name
      "staff_only": false,
      "cooldown_seconds": 5,
      "steps": [
        {"do": "emote", "who": "speaker", "emote": "Hug Yourself"},
        {"do": "wait", "seconds": 1},
        {"do": "emote", "who": "target", "emote": ["Bashful", "Heart Eyes"]},
        {"do": "say", "text": "{speaker} hugged {target}! 💕"}
      ]
    }

Steps:
  emote    who: speaker|target|bot, emote: number, name or id (a list = random pick)
  say      text (a list = random pick), in room chat
  whisper  to: speaker|target, text
  react    to: speaker|target, reaction: clap|heart|thumbs|wave|wink
  wait     seconds (0.1 to 5)
  walk     to: speaker|target (the bot walks next to them)
Text may use {speaker}, {target} and {bot}.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .emotes import EmoteCatalog

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,19}$")
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]*)\}")
PLACEHOLDERS = frozenset({"speaker", "target", "bot"})
REACTIONS = frozenset({"clap", "heart", "thumbs", "wave", "wink"})
STEP_KINDS = ("emote", "say", "whisper", "react", "wait", "walk")
MAX_STEPS = 12
MAX_TOTAL_WAIT = 10.0
MAX_TEXT = 200
MAX_CHOICES = 6
MAX_COOLDOWN = 300.0


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _check_text(value: Any, where: str, needs_target: bool, errors: list[str]) -> list[str]:
    texts = [t for t in _as_list(value) if isinstance(t, str) and t.strip()]
    if not texts:
        errors.append(f"{where}: text must be a non-empty string or list of strings")
        return []
    if len(texts) > MAX_CHOICES:
        errors.append(f"{where}: at most {MAX_CHOICES} text choices")
    for text in texts:
        if len(text) > MAX_TEXT:
            errors.append(f"{where}: text is longer than {MAX_TEXT} characters")
        for name in PLACEHOLDER_PATTERN.findall(text):
            if name not in PLACEHOLDERS:
                errors.append(f"{where}: unknown placeholder {{{name}}}; use {{speaker}}, {{target}} or {{bot}}")
            elif name == "target" and not needs_target:
                errors.append(f"{where}: uses {{target}} but needs_target is false")
    return [t.strip() for t in texts[:MAX_CHOICES]]


def _check_person(value: Any, where: str, allowed: tuple[str, ...], needs_target: bool,
                  errors: list[str]) -> str:
    person = str(value or "").strip().casefold()
    if person not in allowed:
        errors.append(f"{where}: must be one of {', '.join(allowed)}")
    elif person == "target" and not needs_target:
        errors.append(f"{where}: refers to the target but needs_target is false")
    return person


def validate(raw: Any, catalog: EmoteCatalog, reserved: set[str]) -> tuple[dict | None, list[str]]:
    """Check an AI-written command; returns (clean spec, []) or (None, errors).

    The clean spec has emotes resolved to exact Highrise ids, so a saved
    command keeps working even if names in the catalog change.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["command must be a JSON object"]

    name = str(raw.get("name", "")).strip().casefold().lstrip("!")
    if not NAME_PATTERN.match(name):
        errors.append("name must be 2-20 lowercase letters, digits or _ and start with a letter")
    elif name in reserved:
        errors.append(f"!{name} is already a built-in command; pick another name")

    needs_target = raw.get("needs_target", False)
    staff_only = raw.get("staff_only", False)
    if not isinstance(needs_target, bool) or not isinstance(staff_only, bool):
        errors.append("needs_target and staff_only must be true or false")
        needs_target, staff_only = bool(needs_target), bool(staff_only)
    cooldown = raw.get("cooldown_seconds", 5)
    if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)) or not 0 <= cooldown <= MAX_COOLDOWN:
        errors.append(f"cooldown_seconds must be a number from 0 to {MAX_COOLDOWN:g}")
        cooldown = 5
    description = str(raw.get("description", "")).strip()[:120]

    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        errors.append("steps must be a non-empty list")
        steps_raw = []
    if len(steps_raw) > MAX_STEPS:
        errors.append(f"at most {MAX_STEPS} steps")

    steps: list[dict] = []
    total_wait = 0.0
    for index, step in enumerate(steps_raw[:MAX_STEPS], 1):
        where = f"step {index}"
        if not isinstance(step, dict):
            errors.append(f"{where}: must be an object")
            continue
        kind = str(step.get("do", "")).strip().casefold()
        if kind not in STEP_KINDS:
            errors.append(f"{where}: 'do' must be one of {', '.join(STEP_KINDS)}")
            continue
        if kind == "emote":
            who = _check_person(step.get("who"), f"{where} who", ("speaker", "target", "bot"), needs_target, errors)
            refs = _as_list(step.get("emote"))
            ids = []
            for ref in refs[:MAX_CHOICES]:
                found = catalog.find(ref) if ref not in (None, "") else None
                if found is None:
                    errors.append(f"{where}: no emote matches {ref!r}; use a number or exact name from the list")
                else:
                    ids.append(found[1].emote_id)
            steps.append({"do": "emote", "who": who, "emote": ids})
        elif kind == "say":
            steps.append({"do": "say", "text": _check_text(step.get("text"), where, needs_target, errors)})
        elif kind == "whisper":
            to = _check_person(step.get("to"), f"{where} to", ("speaker", "target"), needs_target, errors)
            steps.append({"do": "whisper", "to": to,
                          "text": _check_text(step.get("text"), where, needs_target, errors)})
        elif kind == "react":
            to = _check_person(step.get("to"), f"{where} to", ("speaker", "target"), needs_target, errors)
            reaction = str(step.get("reaction", "")).strip().casefold()
            if reaction not in REACTIONS:
                errors.append(f"{where}: reaction must be one of {', '.join(sorted(REACTIONS))}")
            steps.append({"do": "react", "to": to, "reaction": reaction})
        elif kind == "wait":
            seconds = step.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0.1 <= seconds <= 5:
                errors.append(f"{where}: seconds must be a number from 0.1 to 5")
                seconds = 0.1
            total_wait += float(seconds)
            steps.append({"do": "wait", "seconds": float(seconds)})
        elif kind == "walk":
            to = _check_person(step.get("to"), f"{where} to", ("speaker", "target"), needs_target, errors)
            steps.append({"do": "walk", "to": to})
    if total_wait > MAX_TOTAL_WAIT:
        errors.append(f"waits add up to {total_wait:g}s; the limit is {MAX_TOTAL_WAIT:g}s")

    if errors:
        return None, errors
    return {
        "name": name,
        "description": description,
        "needs_target": needs_target,
        "staff_only": staff_only,
        "cooldown_seconds": float(cooldown),
        "steps": steps,
    }, []


def fill(text: str, speaker: str, target: str | None, bot: str) -> str:
    """Replace only the known placeholders (never str.format on stored text)."""
    return (
        text.replace("{speaker}", speaker)
        .replace("{target}", target or "")
        .replace("{bot}", bot)
    )


def describe(spec: dict, catalog: EmoteCatalog) -> str:
    """A plain-English summary of exactly what the command will do."""
    names = {emote.emote_id: f"{emote.name} (#{number})" for number, emote in catalog.filter()}
    usage = f"!{spec['name']}" + (" @name" if spec["needs_target"] else "")
    who = {"speaker": "you", "target": "they", "bot": "the bot"}
    lines = []
    for step in spec["steps"]:
        kind = step["do"]
        if kind == "emote":
            options = " or ".join(names.get(i, i) for i in step["emote"])
            lines.append(f"{who[step['who']]} do {options}")
        elif kind == "say":
            lines.append("room sees: " + " / ".join(f'"{t}"' for t in step["text"]))
        elif kind == "whisper":
            lines.append(f"whisper to {'you' if step['to'] == 'speaker' else 'them'}: "
                         + " / ".join(f'"{t}"' for t in step["text"]))
        elif kind == "react":
            lines.append(f"send {step['reaction']} to {'you' if step['to'] == 'speaker' else 'them'}")
        elif kind == "wait":
            lines.append(f"wait {step['seconds']:g}s")
        elif kind == "walk":
            lines.append(f"bot walks to {'you' if step['to'] == 'speaker' else 'them'}")
    extras = []
    if spec["staff_only"]:
        extras.append("staff only")
    if spec["cooldown_seconds"]:
        extras.append(f"{spec['cooldown_seconds']:g}s cooldown")
    head = f"{usage}" + (f" — {spec['description']}" if spec["description"] else "")
    return head + "\n" + "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) + (
        f"\n({', '.join(extras)})" if extras else ""
    )


def dumps(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
