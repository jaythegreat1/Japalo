from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from highrise_bot.logging_config import get_logger
from keep_alive import keep_alive

RESTART_DELAYS = (5, 15, 30, 60)
# After this many consecutive fast failures (i.e. we've cycled through the
# whole backoff ladder once with nothing sticking), send one alert instead
# of staying silent while the bot is effectively down.
ALERT_AFTER_CONSECUTIVE_FAILURES = len(RESTART_DELAYS)
MIN_HEALTHY_RUN_SECONDS = 120  # a run at least this long resets the streak

logger = get_logger("main")


def send_alert(message: str) -> None:
    """Best-effort webhook alert. No-op if ALERT_WEBHOOK_URL isn't set.

    Compatible with Discord and Slack-style incoming webhooks (both accept
    a JSON body with a "content" key). This is deliberately independent of
    the bot's own Highrise connection: a "the bot can't reconnect" alert
    can't be delivered by having the bot whisper someone, because if it
    can't reconnect, it isn't connected to whisper anyone. This process-
    level path is what can still get the word out.
    """
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        logger.warning("No ALERT_WEBHOOK_URL configured; alert not sent: %s", message)
        return
    payload = json.dumps({"content": message}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=10)
        logger.info("Sent alert webhook.")
    except urllib.error.URLError as error:
        logger.error("Failed to send alert webhook: %s", error)


def main() -> int:
    room_id = os.environ.get("HIGHRISE_ROOM_ID", "").strip()
    token = os.environ.get("HIGHRISE_BOT_TOKEN", "").strip()
    if not room_id or not token:
        raise SystemExit(
            "Missing HIGHRISE_ROOM_ID or HIGHRISE_BOT_TOKEN. "
            "Add both through secure project secrets."
        )

    # Free Repls sleep without inbound traffic. This starts a tiny web
    # server so an external uptime monitor (e.g. UptimeRobot) can ping the
    # Repl and keep it awake. See keep_alive.py and the README.
    keep_alive()

    delay_index = 0
    consecutive_failures = 0
    alerted_this_streak = False

    while True:
        started_at = time.monotonic()
        exit_code = subprocess.call(
            [
                sys.executable,
                "-m",
                "highrise",
                "highrise_bot.bot:HighriseRoomBot",
                room_id,
                token,
            ]
        )
        ran_for = time.monotonic() - started_at
        logger.warning(
            "Highrise SDK process exited with code %s after %.1fs; restarting.",
            exit_code, ran_for,
        )

        if ran_for >= MIN_HEALTHY_RUN_SECONDS:
            delay_index = 0
            consecutive_failures = 0
            alerted_this_streak = False
        else:
            consecutive_failures += 1

        if (
            consecutive_failures >= ALERT_AFTER_CONSECUTIVE_FAILURES
            and not alerted_this_streak
        ):
            send_alert(
                f"⚠️ Highrise bot has failed to stay up {consecutive_failures} times "
                "in a row and may be down. Check the Replit console."
            )
            alerted_this_streak = True

        delay = RESTART_DELAYS[min(delay_index, len(RESTART_DELAYS) - 1)]
        delay_index += 1
        logger.info("Waiting %ss before restarting the Highrise SDK.", delay)
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
