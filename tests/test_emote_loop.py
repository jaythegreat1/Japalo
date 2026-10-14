import asyncio
import unittest
from unittest.mock import patch

from highrise_bot import emote_loop as emote_loop_module
from highrise_bot.emote_loop import EmoteLoopManager
from highrise_bot.emotes import Emote


class EmoteLoopTests(unittest.TestCase):
    def test_stop_ends_loop_and_does_not_overlap(self) -> None:
        async def scenario() -> None:
            manager = EmoteLoopManager()
            sent: list[tuple[str, str]] = []
            started = asyncio.Event()

            async def sender(emote_id: str, user_id: str) -> None:
                sent.append((emote_id, user_id))
                started.set()

            await manager.start(
                "user-1",
                Emote("Wave", "emote-wave", "common", 0.02),
                sender,
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0.07)
            await manager.stop("user-1")
            count_at_stop = len(sent)
            await asyncio.sleep(0.05)

            self.assertGreaterEqual(count_at_stop, 2)
            self.assertEqual(len(sent), count_at_stop)
            self.assertFalse(manager.is_running("user-1"))

        asyncio.run(scenario())

    def test_slow_send_does_not_create_catch_up_burst(self) -> None:
        async def scenario() -> None:
            manager = EmoteLoopManager()
            send_times: list[float] = []
            loop = asyncio.get_running_loop()

            async def sender(emote_id: str, user_id: str) -> None:
                send_times.append(loop.time())
                await asyncio.sleep(0.2)

            await manager.start(
                "user-1",
                Emote("Slow", "emote-slow", "common", 0.05),
                sender,
            )
            await asyncio.sleep(0.58)
            await manager.stop("user-1")

            gaps = [
                later - earlier
                for earlier, later in zip(send_times, send_times[1:])
            ]
            self.assertGreaterEqual(len(gaps), 2)
            self.assertTrue(all(gap >= 0.23 for gap in gaps))

        asyncio.run(scenario())

    def test_sender_error_stops_loop_and_calls_error_handler(self) -> None:
        async def scenario() -> None:
            manager = EmoteLoopManager()
            errors: list[tuple[str, str]] = []

            async def sender(emote_id: str, user_id: str) -> None:
                raise RuntimeError("rejected")

            async def on_error(user_id: str, error: Exception) -> None:
                errors.append((user_id, str(error)))

            await manager.start(
                "user-1",
                Emote("Broken", "emote-broken", "common", 1),
                sender,
                on_error=on_error,
            )
            await asyncio.sleep(2.5)

            self.assertEqual(errors, [("user-1", "rejected")])
            self.assertFalse(manager.is_running("user-1"))
            self.assertFalse(await manager.stop("user-1"))

        asyncio.run(scenario())

    def test_sender_transient_error_is_retried(self) -> None:
        async def scenario() -> None:
            manager = EmoteLoopManager()
            attempts = 0
            errors: list[Exception] = []

            async def sender(emote_id: str, user_id: str) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary rejection")

            async def on_error(user_id: str, error: Exception) -> None:
                errors.append(error)

            await manager.start(
                "user-1",
                Emote("Retry", "emote-retry", "common", 10),
                sender,
                on_error=on_error,
            )
            await asyncio.sleep(0.9)
            await manager.stop("user-1")

            self.assertEqual(attempts, 2)
            self.assertEqual(errors, [])

        asyncio.run(scenario())

    def test_target_ownership_error_gets_longer_recovery_retries(self) -> None:
        async def scenario() -> None:
            manager = EmoteLoopManager()
            attempts = 0
            errors: list[Exception] = []

            async def sender(emote_id: str, user_id: str) -> None:
                nonlocal attempts
                attempts += 1
                if attempts <= 3:
                    raise RuntimeError(
                        "Emote is not free or owned by target user"
                    )

            async def on_error(user_id: str, error: Exception) -> None:
                errors.append(error)

            with patch.object(
                emote_loop_module,
                "SEND_RETRY_DELAYS",
                (0.01,),
            ), patch.object(
                emote_loop_module,
                "TARGET_OWNERSHIP_RETRY_DELAYS",
                (0.01, 0.01),
            ):
                await manager.start(
                    "user-1",
                    Emote("Retry ownership", "emote-retry", "common", 10),
                    sender,
                    on_error=on_error,
                )
                await asyncio.sleep(0.1)
                await manager.stop("user-1")

            self.assertEqual(attempts, 4)
            self.assertEqual(errors, [])

        asyncio.run(scenario())

if __name__ == "__main__":
    unittest.main()