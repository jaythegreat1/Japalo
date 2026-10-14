"""Repeatable maintenance entry point for the self-healing emote catalog.

This command refreshes official Highrise metadata first. The following live
probe can then be run in a private/test room with the same secrets:

    python refresh_catalog.py
    EMOTE_VERIFY_EXISTING=true EMOTE_VERIFY_PRUNE_INVALID=true \
      EMOTE_VERIFY_MEASURE_DURATION=true \
      python -m highrise tools.emote_catalog.verify_emotes:EmoteVerifierBot \
      "$HIGHRISE_ROOM_ID" "$HIGHRISE_BOT_TOKEN"

The separation is intentional. Fetching is safe and read-only; probing sends
visible emotes into a room and is never performed silently by the production
bot. Purchase-locked IDs are audited but are not pruned.
"""
from __future__ import annotations

import os
import subprocess
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FETCHER = ROOT / "tools" / "emote_catalog" / "fetch_catalog.py"
CANDIDATES = Path(
    os.environ.get(
        "EMOTE_CANDIDATES_PATH",
        str(ROOT / "tools" / "emote_catalog" / "data" / "candidates.json"),
    )
)


def _preserve_progress(previous: list[dict], current: list[dict]) -> list[dict]:
    """Keep live evidence while replacing the official source snapshot."""
    terminal = {
        "verified",
        "id_confirmed",
        "requires_purchase",
        "id_invalid",
        "needs_review",
    }
    previous_by_id = {
        row.get("catalog_item_id"): row
        for row in previous
        if row.get("catalog_item_id")
    }
    for row in current:
        old = previous_by_id.get(row.get("catalog_item_id"))
        if old and old.get("status") in terminal:
            for key in (
                "status",
                "runtime_check",
                "error_class",
                "note",
                "duration_seconds",
            ):
                if key in old:
                    row[key] = old[key]
    return current


def main() -> int:
    env = os.environ.copy()
    env["HIGHRISE_CATALOG_OUTPUT"] = str(CANDIDATES)
    env.setdefault("HIGHRISE_CATALOG_PRESERVE_KNOWN_ON_EMPTY", "false")
    previous = []
    if CANDIDATES.exists():
        previous = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    result = subprocess.run([sys.executable, str(FETCHER)], cwd=ROOT, env=env)
    if result.returncode:
        return result.returncode
    if CANDIDATES.exists():
        current = json.loads(CANDIDATES.read_text(encoding="utf-8"))
        CANDIDATES.write_text(
            json.dumps(_preserve_progress(previous, current), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    print(
        "\nOfficial refresh complete. Run the live probe with "
        "EMOTE_VERIFY_EXISTING=true and EMOTE_VERIFY_PRUNE_INVALID=true "
        "to classify allowed, purchase-locked, and invalid IDs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())