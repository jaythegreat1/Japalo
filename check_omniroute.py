"""Check that OmniRoute is reachable and answers, without joining Highrise.

Usage: python check_omniroute.py ["your question"]
"""

import asyncio
import sys

from bot.brain import Brain, BrainError
from bot.config import Config


async def check(question: str) -> int:
    config = Config.from_env()
    brain = Brain(
        config.omniroute_url, config.omniroute_key, config.model, retries=0,
        fallback_models=config.fallback_models,
    )
    try:
        print(f"OmniRoute at {config.omniroute_url}")
        try:
            models = await brain.list_models()
            print(f"  models available: {len(models)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not list models: {exc}")
            return 1
        try:
            answer = await brain.complete([{"role": "user", "content": question}])
        except BrainError as exc:
            print(f"  chat failed: {exc}")
            print("  Connect a provider in the OmniRoute dashboard, or set OMNIROUTE_MODEL.")
            return 2
        print(f"  model {brain.stats['last_model']} answered: {answer}")
        return 0
    finally:
        await brain.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(check(sys.argv[1] if len(sys.argv) > 1 else "Say hi in five words.")))
