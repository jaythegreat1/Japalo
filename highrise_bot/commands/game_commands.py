from __future__ import annotations

import asyncio

from highrise import User

from .. import personality
from ..constants import GAME_NAMES, GAME_TIMEOUTS
from ..logging_config import get_logger

logger = get_logger(__name__)


class GameCommandsMixin:
    """!games, !trivia/!scramble/!math/!riddle/!guessnumber, !answer, plain
    numbers (Guess the Number), !score, !leaderboard, !endgame, and the
    reward payout after a win.

    Depends on the core class for: self.highrise, self.storage,
    self.active_game/self.game_task, the five game engine instances
    (self.trivia, self.scramble, self.math_blitz, self.guess_number,
    self.emoji_riddle), self._voice, self._enabled_games (also here),
    self._setting_int, self._is_staff.
    """

    def _enabled_games(self) -> set[str]:
        raw = self._settings.get("enabled_games", "")
        return {g.strip() for g in raw.split(",") if g.strip()}

    async def _send_games_list(self, user: User, args: list[str] | None = None) -> None:
        enabled = self._enabled_games()
        listing = ", ".join(f"!{name}" for name in GAME_NAMES if name in enabled)
        await self.highrise.send_whisper(
            user.id,
            f"Games: {listing or '(none enabled)'}. Guess the Number uses "
            "plain numbers in chat; the rest use !answer <text>.",
        )

    async def _start_game(self, game: str) -> None:
        if game not in self._enabled_games():
            await self.highrise.chat(f"{GAME_NAMES[game]} is currently disabled by room settings.")
            return
        if self.active_game is not None:
            active_name = GAME_NAMES[self.active_game]
            text = self._voice(
                personality.GAME_ALREADY_ACTIVE_MESSAGES,
                f"{active_name} is already running. Finish it, wait for it "
                "to time out, or ask staff to !endgame.",
                active=active_name,
            )
            await self.highrise.chat(text)
            return

        if game == "trivia":
            question = self.trivia.start_next()
            prompt = "Trivia: " + question.prompt + " " + " | ".join(question.choices)
        elif game == "scramble":
            round_ = self.scramble.start_next()
            prompt = f"Scramble! Unscramble: {round_.scrambled}  (hint: {round_.hint}) — !answer <word>"
        elif game == "math":
            round_ = self.math_blitz.start_next()
            prompt = f"Math Blitz! {round_.prompt} = ?  — !answer <number>"
        elif game == "riddle":
            round_ = self.emoji_riddle.start_next()
            prompt = f"Emoji Riddle: {round_.clue}  (hint: {round_.hint}) — !answer <text>"
        elif game == "guessnumber":
            round_ = self.guess_number.start_next()
            prompt = (
                f"Guess the Number! I'm thinking of a number between "
                f"{round_.low} and {round_.high}. Just type a number in chat."
            )
        else:
            return

        self.active_game = game
        intro = self._voice(personality.GAME_INTRO_LINES, "")
        await self.highrise.chat(f"{intro} {prompt}".strip())
        self.game_task = asyncio.create_task(
            self._expire_game(game, GAME_TIMEOUTS[game])
        )

    async def _expire_game(self, game: str, timeout: float) -> None:
        await asyncio.sleep(timeout)
        if self.active_game == game:
            reveal = self._reveal_answer(game)
            self._clear_game(game)
            text = self._voice(
                personality.GAME_TIMEOUT_MESSAGES,
                f"Time's up! No one got it. {reveal}",
                reveal=reveal,
            )
            await self.highrise.chat(text)

    def _reveal_answer(self, game: str) -> str:
        if game == "trivia" and self.trivia.current is not None:
            return f"The answer was {self.trivia.current.answer.upper()}."
        if game == "scramble" and self.scramble.current is not None:
            return f"The word was {self.scramble.current.answer}."
        if game == "math" and self.math_blitz.current is not None:
            return f"The answer was {self.math_blitz.current.answer}."
        if game == "riddle" and self.emoji_riddle.current is not None:
            return f"The answer was {self.emoji_riddle.current.answer}."
        if game == "guessnumber" and self.guess_number.current is not None:
            return f"The number was {self.guess_number.current.secret}."
        return ""

    def _clear_game(self, game: str, cancel_task: bool = False) -> None:
        if game == "trivia":
            self.trivia.clear()
        elif game == "scramble":
            self.scramble.clear()
        elif game == "math":
            self.math_blitz.clear()
        elif game == "riddle":
            self.emoji_riddle.clear()
        elif game == "guessnumber":
            self.guess_number.clear()
        if self.active_game == game:
            self.active_game = None
        if cancel_task and self.game_task is not None:
            self.game_task.cancel()
            self.game_task = None

    async def _answer_active_game(self, user: User, args: list[str]) -> None:
        if self.active_game is None:
            await self.highrise.send_whisper(user.id, "There is no active game. Start one with !games.")
            return
        if self.active_game == "guessnumber":
            await self.highrise.send_whisper(
                user.id, "Guess the Number uses plain numbers typed in chat, not !answer."
            )
            return

        guess = " ".join(args).strip()
        if not guess:
            await self.highrise.send_whisper(user.id, "Usage: !answer <your answer>.")
            return

        correct = self._check_game_answer(self.active_game, guess)
        if not correct:
            await self.highrise.send_whisper(user.id, "Not quite. The round is still open.")
            return

        game = self.active_game
        extra = ""
        if game == "trivia" and self.trivia.current is not None:
            extra = " " + self.trivia.current.explanation
        points = await self.storage.add_point(user.id, game=game)
        await self._maybe_reward_winner(user)
        self._clear_game(game, cancel_task=True)
        text = self._voice(
            personality.GAME_WIN_MESSAGES,
            f"Correct, {user.username}! You have {points} point(s).",
            username=user.username,
            points=points,
        )
        await self.highrise.chat(f"{text}{extra}")

    def _check_game_answer(self, game: str, guess: str) -> bool:
        if game == "trivia":
            return self.trivia.answer_is_correct(guess)
        if game == "scramble":
            return self.scramble.check(guess)
        if game == "math":
            return self.math_blitz.check(guess)
        if game == "riddle":
            return self.emoji_riddle.check(guess)
        return False

    async def _guess_number_attempt(self, user: User, number: int) -> None:
        if self.active_game != "guessnumber" or self.guess_number.current is None:
            return
        round_ = self.guess_number.current
        result = self.guess_number.guess(number)

        if result == "correct":
            points = await self.storage.add_point(user.id, game="guessnumber")
            await self._maybe_reward_winner(user)
            self._clear_game("guessnumber", cancel_task=True)
            text = self._voice(
                personality.GAME_WIN_MESSAGES,
                f"{user.username} got it! The number was {number}.",
                username=user.username,
                points=points,
            )
            await self.highrise.chat(f"{text} (The number was {number}.)")
        elif result == "out_of_range":
            await self.highrise.send_whisper(
                user.id, f"Guess must be between {round_.low} and {round_.high}."
            )
        elif result == "no_more_attempts":
            secret = round_.secret
            self._clear_game("guessnumber", cancel_task=True)
            await self.highrise.chat(f"Out of guesses! The number was {secret}.")
        else:
            await self.highrise.send_whisper(user.id, f"{result.capitalize()}! Try again.")

    async def _force_end_game(self, user: User, args: list[str] | None = None) -> None:
        if not await self._is_staff(user.id):
            await self.highrise.send_whisper(user.id, "Only the room dev or a moderator can end a game early.")
            return
        if self.active_game is None:
            await self.highrise.send_whisper(user.id, "No game is active.")
            return
        game = self.active_game
        game_name = GAME_NAMES[game]
        self._clear_game(game, cancel_task=True)
        text = self._voice(
            personality.GAME_FORCE_END_MESSAGES,
            f"{game_name} was ended early by {user.username}.",
            game=game_name,
            username=user.username,
        )
        await self.highrise.chat(text)

    async def _send_leaderboard(self, user: User, args: list[str]) -> None:
        period = args[0].casefold() if args else "all"
        if period not in {"daily", "weekly", "all"}:
            await self.highrise.send_whisper(user.id, "Use !leaderboard daily, weekly, or all.")
            return
        top = await self.storage.top_scores_period(period=period, limit=5)
        if not top:
            await self.highrise.chat(
                f"No {period} points on the board yet — play a game with !games."
            )
            return
        lines = []
        for index, (user_id, points) in enumerate(top, 1):
            name = await self.storage.get_username(user_id) or user_id
            lines.append(f"{index}. {name} — {points} pt(s)")
        await self.highrise.chat(
            f"{period.title()} leaderboard:\n" + "\n".join(lines)
        )

    async def _send_score(self, user: User, args: list[str] | None = None) -> None:
        points = await self.storage.get_score(user.id)
        await self.highrise.chat(f"{user.username} has {points} point(s).")

    async def _maybe_reward_winner(self, user: User) -> None:
        reward = max(0, self._setting_int("game_reward_gold"))
        cap = max(0, self._setting_int("game_reward_gold_cap"))
        reward = min(reward, cap)
        if reward <= 0:
            return
        denominations = [
            (10_000, "gold_bar_10k"), (5_000, "gold_bar_5000"),
            (1_000, "gold_bar_1k"), (500, "gold_bar_500"),
            (100, "gold_bar_100"), (50, "gold_bar_50"),
            (10, "gold_bar_10"), (5, "gold_bar_5"), (1, "gold_bar_1"),
        ]
        amount, gold_bar = next(
            ((amount, item) for amount, item in denominations if amount <= reward),
            (0, ""),
        )
        if not gold_bar:
            return
        try:
            result = await self.highrise.tip_user(user.id, gold_bar)
            if result == "success":
                await self.highrise.chat(
                    f"{user.username} won {amount}g for that minigame round!"
                )
            else:
                logger.info("Game reward for %s was not sent: %s", user.id, result)
        except Exception:
            logger.exception("Could not reward minigame winner %s", user.id)
