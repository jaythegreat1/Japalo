"""Tiny HTTP server used only to keep a free Replit Repl awake.

A free Repl goes to sleep after a period with no incoming traffic. This
starts a minimal Flask server in a background thread and exposes one
endpoint. Point an UptimeRobot "HTTP(s)" monitor at this Repl's public URL
(shown at the top of the Replit webview once the app is running) on a
5-minute interval, and Replit will keep waking the Repl to serve the ping.

This process is intentionally decoupled from the Highrise bot's own
websocket connection and reconnect logic (see main.py) — this only keeps
the Repl process itself alive; it has no bearing on whether the bot's
Highrise connection is healthy.
"""

from __future__ import annotations

import logging
import os
from threading import Thread

from flask import Flask

app = Flask(__name__)

# Quiet Flask's per-request access log; it adds noise for a bot process
# whose real logs are the Highrise SDK's own connection/reconnect output.
logging.getLogger("werkzeug").setLevel(logging.WARNING)


@app.route("/")
def index() -> str:
    return "Highrise bot keep-alive: OK"


@app.route("/health")
def health() -> tuple[str, int]:
    return "OK", 200


def _run() -> None:
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


def keep_alive() -> None:
    """Start the keep-alive server in a daemon thread and return immediately."""
    thread = Thread(target=_run, daemon=True, name="keep-alive-http")
    thread.start()
