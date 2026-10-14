"""Japalo's voice.

One bot, many moods. Every pool below deliberately mixes tones — dry/witty,
hype/chaotic-gamer, and warm/chill — in the same list so replies feel like a
character with range instead of one flat joke repeated forever. Pick a pool,
call `pick()`, done.

Toggle: `!config set personality off` makes every wrapped message fall back
to the plain, purely-informational text (see the `plain=` argument on
`voice()` in bot.py's mixins). Nothing user-facing that carries required
info (usage strings, permission errors, numbers, durations) ever lives only
in here — personality wraps information, it never hides it.
"""

from __future__ import annotations

import random
from typing import Sequence

BOT_NAME = "Japalo"


def pick(pool: Sequence[str], **kwargs: object) -> str:
    """Choose one line from a pool and format it. Never mutates the pool."""
    return random.choice(pool).format(bot=BOT_NAME, **kwargs)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

STARTUP_MESSAGES: tuple[str, ...] = (
    "{bot} has entered the chat. Type !help if you're lost, !games if you're bored.",
    "{bot} online and dangerously well-rested. !help for the full menu.",
    "Systems nominal, sass levels optimal — {bot} is here. Try !help.",
    "*{bot} boots up with a little too much enthusiasm.* !help to get started.",
    "{bot} reporting for duty. Emotes, games, and mild chaos on request — !help.",
    "Beep. Boop. Just kidding, {bot} doesn't beep. !help for what I actually do.",
    "{bot}'s awake. Let's cause some (approved) fun. !help !games !emotelist",
    "The room's official third wheel, {bot}, has arrived. !help anytime.",
)

# ---------------------------------------------------------------------------
# Joins / leaves — see messages.py, which imports these pools directly.
# ---------------------------------------------------------------------------

JOIN_MESSAGES: tuple[str, ...] = (
    "{username} just walked in and {bot} felt that. Welcome!",
    "Welcome, {username}! {bot} was starting to get bored, good timing.",
    "{username} has entered the room. Try not to trip on the way to !games.",
    "Yo {username}, welcome! Grab an emote and make yourself at home.",
    "{username}! {bot} was hoping someone cool would show up. You'll do.",
    "Door's always open for {username}. Welcome in.",
    "{username} appeared like a plot twist nobody saw coming. Welcome!",
    "New arrival: {username}. Threat level: probably friendly. Welcome!",
    "Everyone say hi to {username} — or don't, {bot} will do it twice as loud. Welcome!",
    "{username} just joined and {bot} is already rooting for you. Welcome!",
    "Room's a little brighter now that {username} is here. Welcome!",
    "{username}, you found us. Achievement unlocked: good taste. Welcome!",
    "Incoming: {username}! {bot} is contractually obligated to say welcome, but also means it.",
    "Hey {username} — welcome. {bot} promises to only be a LITTLE chaotic.",
    "{username} has entered the building. !emotelist is right there if you're feeling fancy.",
    "Welcome aboard, {username}! First round of !trivia is on the house (it's free either way).",
    "{username}! {bot} was just about to start a game. Perfect timing.",
    "A wild {username} appears! Welcome to the room.",
    "{username}, glad you're here. {bot} was running low on people to hype up.",
    "Fresh face alert: {username} just joined. Welcome!",
)

LEAVE_MESSAGES: tuple[str, ...] = (
    "{username} has left the building. {bot} will recover eventually.",
    "Bye {username}! Come back before {bot} gets too attached.",
    "{username} logged off. The vibes dipped slightly. See you soon!",
    "Safe travels, {username}. {bot} is already planning the next welcome.",
    "{username} has exited stage left. Thanks for stopping by!",
    "Catch you later, {username}. Door's unlocked whenever you're back.",
    "{username} is gone but not forgotten (mostly because the database remembers everything).",
    "Take care, {username}! {bot} will keep the emotes warm for you.",
    "{username} dipped. Respect the hustle, see you next time.",
    "And just like that, {username} vanished. Until next time!",
    "{username} has left. {bot} is now 1 person lonelier and 0% less dramatic about it.",
    "Later, {username}! Don't be a stranger.",
    "{username} peaced out. Hope you had fun — come back for round two.",
    "{username} has left the room. The leaderboard will miss you specifically.",
    "See you around, {username} — {bot} is keeping your favorites saved.",
)

# Milestone joins (10th / 25th / 50th / 100th visit) — bigger occasion, bigger line.
MILESTONE_MESSAGES: tuple[str, ...] = (
    "Hold up — {username} just clocked their {count}th visit! Loyalty like that deserves applause.",
    "{count} visits and counting. {username}, you're basically furniture at this point (a beloved one).",
    "Achievement unlocked: {username} hit visit #{count}. {bot} is genuinely touched.",
    "{username} keeps coming back — visit number {count}! Someone give this person a medal (or a !fav slot).",
    "Milestone alert! {username} just walked in for the {count}th time. Absolute regular energy.",
    "{count} visits from {username}? At this rate you should just move in.",
)

# ---------------------------------------------------------------------------
# Raid protection
# ---------------------------------------------------------------------------

RAID_ALERT_MESSAGES: tuple[str, ...] = (
    "Uh oh — a suspicious wave of joins just hit. Raid protection is on it. Staff, eyes up.",
    "Whoa, that's a lot of new faces at once. {bot} just flagged it as a possible raid. Staff, please watch the room.",
    "Red alert (a calm, purely informational one): join burst detected. Staff should keep an eye on things.",
    "That was a suspiciously large crowd all at once. Raid protection engaged — staff, stay sharp.",
)

# ---------------------------------------------------------------------------
# Tips / economy
# ---------------------------------------------------------------------------

TIP_THANKS_MESSAGES: tuple[str, ...] = (
    "{amount}g from {username}? {bot} is blushing (metaphorically, {bot} has no face).",
    "Thank you {username} for the {amount}g! You've officially made {bot}'s day.",
    "{username} just tipped {amount}g. {bot} accepts gold and compliments equally.",
    "Cha-ching! {amount}g from {username}, much appreciated.",
    "{username} tipped {amount}g — {bot} promises to spend it responsibly (no promises).",
    "{amount}g?! {username}, you're too kind. Thank you!",
    "Generosity detected: {username} sent {amount}g. {bot} salutes you.",
    "{username} just fed the tip jar {amount}g. It's thriving. Thank you!",
)
TIP_TOTAL_SUFFIXES: tuple[str, ...] = (
    " Running total: {total}g — impressive.",
    " That's {total}g lifetime. Legend status pending.",
    " {total}g total now. {bot} is keeping a very affectionate spreadsheet.",
    " Lifetime tip count: {total}g. Not that anyone's counting. ({bot} is counting.)",
)
VIP_UNLOCK_MESSAGES: tuple[str, ...] = (
    "{username} just crossed 100g total and unlocked VIP! You can now boss the emotes around with !emote @name.",
    "VIP STATUS UNLOCKED for {username}! 100g lifetime tips — welcome to the good seats.",
    "{username} hit the 100g mark. VIP privileges are live: !emote @someone <number> is yours to use.",
    "Big moment: {username} is now VIP. Emote-other privileges unlocked, use them wisely (or don't).",
)

# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------

WARNING_MESSAGES: tuple[str, ...] = (
    "Warning {count} for {username}: {reason}. {bot} is keeping score.",
    "{username}, that's warning {count} ({reason}). Let's not make it three.",
    "Flag on the play: {username} gets warning {count} for {reason}.",
    "Warning {count}, {username} — {reason}. {bot} believes in second chances (and third, but that's it).",
    "Noted: warning {count} for {username} ({reason}). Escalation is real, please don't test it.",
)
AUTO_MUTE_MESSAGES: tuple[str, ...] = (
    "{username} hit 3 warnings and earned a {duration}s timeout. Cool off, come back better.",
    "Auto-mute engaged on {username} for {duration}s. Three strikes, {bot} isn't messing around.",
    "{username} has been muted for {duration}s after warning #3. Use the time wisely.",
    "That's three warnings, {username} — {duration}s of quiet time, courtesy of the house rules.",
)
AUTO_KICK_MESSAGES: tuple[str, ...] = (
    "{username} racked up 5 warnings and has been shown the door. Fresh start next time.",
    "Warning #5 hit — {username} has been kicked. {bot} did not enjoy this part.",
    "{username} is out after five warnings. The counter's reset if you come back and behave.",
)
MOD_ACTION_MESSAGES: tuple[str, ...] = (
    "{actor} used {action} on {target}. House rules, no hard feelings.",
    "{actor} laid down the law — {action} on {target}.",
    "Moderation log: {actor} -> {action} -> {target}. Keep the room nice, folks.",
    "{action} incoming for {target}, courtesy of {actor}.",
)
FREEZE_MESSAGES: tuple[str, ...] = (
    "{target} is soft-frozen in place. Not magic, just very persistent teleporting.",
    "{target} isn't going anywhere now (probably). Soft-freeze engaged.",
    "Pinned: {target}. It's a best-effort freeze, not sorcery, but it'll hold.",
)
UNFREEZE_MESSAGES: tuple[str, ...] = (
    "{target} has been released back into the wild.",
    "{target} can move freely again. Go forth.",
    "Unfroze {target}. Try to behave this time.",
)
MODERATOR_GRANT_MESSAGES: tuple[str, ...] = (
    "{target} is now a moderator. Use your powers for good (or at least for chaos control).",
    "Congrats {target}, you're staff now. {bot} expects great things.",
    "{target} just got promoted to moderator. The room is in slightly more capable hands.",
)
MODERATOR_REVOKE_MESSAGES: tuple[str, ...] = (
    "{target} is no longer a moderator. Thanks for your service.",
    "{target}'s moderator badge has been retired. It was a good run.",
    "{target} stepped down (or was stepped down) from moderator duty.",
)
COOLDOWN_MESSAGES: tuple[str, ...] = (
    "Whoa, speed racer. Give it a second between commands.",
    "Slow down a little — {bot} needs a breath between commands.",
    "Easy there! Commands have a short cooldown, try again in a moment.",
    "One at a time! Cooldown's still ticking.",
)

# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

GAME_INTRO_LINES: tuple[str, ...] = (
    "Game time!",
    "Let's go, brains on:",
    "{bot} interrupts your regularly scheduled chatting for:",
    "New round, let's see who's paying attention:",
    "Round start! Fastest fingers win:",
    "Alright, showtime:",
)
GAME_ALREADY_ACTIVE_MESSAGES: tuple[str, ...] = (
    "{active} is already running — finish it, ride it out, or ask staff for !endgame.",
    "Hold your emotes, {active} is still live. Wrap that one up first.",
    "One game at a time! {active} is currently in progress.",
)
GAME_WIN_MESSAGES: tuple[str, ...] = (
    "Correct, {username}! Big brain energy. {points} point(s) now.",
    "{username} nails it! {points} point(s) and counting.",
    "That's a win for {username}! Sitting pretty at {points} point(s).",
    "{username} got it! {points} point(s) on the board.",
    "Ding ding ding, {username} wins the round! {points} point(s) total.",
    "Clean answer from {username}. {points} point(s) now.",
)
GAME_TIMEOUT_MESSAGES: tuple[str, ...] = (
    "Time's up! Nobody got it. {reveal}",
    "Round over — silence from the crowd. {reveal}",
    "Clock hit zero. Nobody claimed it this time. {reveal}",
    "And that's time. Tough round. {reveal}",
)
GAME_FORCE_END_MESSAGES: tuple[str, ...] = (
    "{game} was cut short by {username}. Staff's call.",
    "{username} ended {game} early. Onwards.",
    "{game} has been shut down by {username}. New round whenever.",
)

# ---------------------------------------------------------------------------
# Emotes
# ---------------------------------------------------------------------------

SURPRISE_PICK_MESSAGES: tuple[str, ...] = (
    "Fate has chosen: #{number} {name} [{rarity}].",
    "Rolling the dice... it's #{number} {name} [{rarity}]!",
    "Surprise! You get #{number} {name} [{rarity}].",
    "Random.org (not really) says: #{number} {name} [{rarity}].",
)
EMOTE_LOOP_MESSAGES: tuple[str, ...] = (
    "Looping {emote} — type stop whenever you've had enough.",
    "{emote}, on repeat, until you say stop.",
    "Locked in on {emote}. Type stop to break the loop.",
)
EMOTE_LOOP_OTHER_MESSAGES: tuple[str, ...] = (
    "Looping {emote} on {target}. They can thank (or blame) you.",
    "{target} is now doing {emote} on repeat. Powerful stuff.",
    "Making {target} do {emote} until someone says stop.",
)

# ---------------------------------------------------------------------------
# Config / help
# ---------------------------------------------------------------------------

CONFIG_CHANGE_MESSAGES: tuple[str, ...] = (
    "Done — {key} is now {value}.",
    "{key} updated to {value}. {bot} adapts instantly, no reboot required.",
    "Setting locked in: {key} = {value}.",
)
HELP_INTROS: tuple[str, ...] = (
    "Here's everything {bot} can do, no fluff:",
    "The full menu, as requested:",
    "{bot}'s command list, fresh out the oven:",
)
