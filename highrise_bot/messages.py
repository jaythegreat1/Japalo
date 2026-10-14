from __future__ import annotations

import random

from .personality import JOIN_MESSAGES, LEAVE_MESSAGES, BOT_NAME

# Kept for anyone with !config set personality off — plain, no jokes.
PLAIN_JOIN_MESSAGE = "Welcome, {username}!"
PLAIN_LEAVE_MESSAGE = "{username} has left the room."


def random_join_message(username: str) -> str:
    return random.choice(JOIN_MESSAGES).format(username=username, bot=BOT_NAME)


def random_leave_message(username: str) -> str:
    return random.choice(LEAVE_MESSAGES).format(username=username, bot=BOT_NAME)


def plain_join_message(username: str) -> str:
    return PLAIN_JOIN_MESSAGE.format(username=username)


def plain_leave_message(username: str) -> str:
    return PLAIN_LEAVE_MESSAGE.format(username=username)
