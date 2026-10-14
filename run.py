"""Start the Japalo bot: `python run.py` (settings come from .env)."""

import asyncio
import logging
import sys

from highrise.__main__ import BotDefinition, main

from bot.config import Config
from bot.main import JapaloBot


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = Config.from_env()
    missing = config.missing()
    if missing:
        sys.exit(f"Missing settings: {', '.join(missing)}. Copy .env.example to .env and fill them in.")
    bot = JapaloBot(config)
    asyncio.run(main([BotDefinition(bot, config.room_id, config.api_token)]))


if __name__ == "__main__":
    run()
