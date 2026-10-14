from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .emotes import Emote

EmoteSender = Callable[[str, str], Awaitable[None]]
EmoteErrorHandler = Callable[[str, Exception], Awaitable[None]]
SEND_RETRY_DELAYS = (0.75, 1.5)
TARGET_OWNERSHIP_ERROR_MARKER = (
    "emote is not free or owned by target user"
)
TARGET_OWNERSHIP_RETRY_DELAYS = (3.0, 10.0, 20.0)


class EmoteLoopManager:
    """Keeps one precise, independently stoppable emote loop per user."""

    def __init__(self) -> None:
        self._loops: dict[str, tuple[asyncio.Event, asyncio.Task[None]]] = {}

    async def start(
        self,
        user_id: str,
        emote: Emote,
        sender: EmoteSender,
        on_error: EmoteErrorHandler | None = None,
    ) -> None:
        await self.stop(user_id)
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            self._run(stop_event, emote, user_id, sender, on_error)
        )
        self._loops[user_id] = (stop_event, task)

    async def stop(self, user_id: str) -> bool:
        current = self._loops.pop(user_id, None)
        if current is None:
            return False

        stop_event, task = current
        stop_event.set()
        await task
        return True

    async def stop_all(self) -> None:
        for user_id in tuple(self._loops):
            await self.stop(user_id)

    def is_running(self, user_id: str) -> bool:
        current = self._loops.get(user_id)
        return current is not None and not current[1].done()

    async def _run(
        self,
        stop_event: asyncio.Event,
        emote: Emote,
        user_id: str,
        sender: EmoteSender,
        on_error: EmoteErrorHandler | None,
    ) -> None:
        loop = asyncio.get_running_loop()

        try:
            while not stop_event.is_set():
                send_error: Exception | None = None
                for retry_delay in (0.0, *SEND_RETRY_DELAYS):
                    if retry_delay:
                        try:
                            await asyncio.wait_for(
                                stop_event.wait(), timeout=retry_delay
                            )
                            return
                        except asyncio.TimeoutError:
                            pass
                    try:
                        await sender(emote.emote_id, user_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        send_error = error
                        continue
                    else:
                        send_error = None
                        break

                if send_error is not None:
                    if TARGET_OWNERSHIP_ERROR_MARKER in str(
                        send_error
                    ).casefold():
                        for retry_delay in TARGET_OWNERSHIP_RETRY_DELAYS:
                            try:
                                await asyncio.wait_for(
                                    stop_event.wait(), timeout=retry_delay
                                )
                                return
                            except asyncio.TimeoutError:
                                pass
                            try:
                                await sender(emote.emote_id, user_id)
                            except asyncio.CancelledError:
                                raise
                            except Exception as error:
                                send_error = error
                                continue
                            else:
                                send_error = None
                                break

                    if send_error is None:
                        try:
                            await asyncio.wait_for(
                                stop_event.wait(), timeout=emote.duration_seconds
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue

                    if on_error is not None:
                        try:
                            await on_error(user_id, send_error)
                        except Exception:
                            pass
                    return

                # Anchor the next interval after the request completes. This
                # prevents short emotes such as Punch from being sent again
                # before Highrise has finished applying the previous one.
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=emote.duration_seconds
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            current = self._loops.get(user_id)
            if current is not None and current[0] is stop_event:
                self._loops.pop(user_id, None)