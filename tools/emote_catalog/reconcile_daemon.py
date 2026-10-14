"""Safe periodic source refresh + live Highrise emote reconciliation.

This is intentionally a separate process from the production room bot. It
requires a dedicated verification room and an explicit opt-in, then repeats:

1. refresh official Highrise source records;
2. probe the real SDK send_emote interface against BOTH those fresh
   candidates and every entry already in the live runtime catalog
   (``config/emotes.json``), so entries Highrise silently stopped
   accepting get caught, not just newly discovered ones;
3. audit accepted, invalid, purchase-locked, and ambiguous results;
4. remove only the explicit invalid-ID results from the runtime catalog;
5. (opt-in, see EMOTE_RECONCILE_AUTO_MERGE below) merge newly confirmed
   ids into the runtime catalog.

It never auto-buys, and by default it never merges anything new INTO the
runtime catalog - a newly accepted id just sits in the audit as
``id_confirmed``/``verified`` until a human runs Stage 3
(``merge_catalog.py``) by hand.

Set ``EMOTE_RECONCILE_AUTO_MERGE=true`` to have the daemon run Stage 3
itself after a clean probe. This only works because Stage 2
(``verify_emotes.py``) now marks a Highrise-confirmed id "verified" with a
placeholder ``duration_seconds`` unless ``EMOTE_VERIFY_REQUIRE_MEASURED_DURATION``
is set - the id is what matters for the emote to actually work; precise
loop timing is a polish step that can be refined later per-entry. If you
want the daemon to only merge ids that were properly measured by a human,
set ``EMOTE_RECONCILE_REQUIRE_MEASURED_DURATION=true`` alongside
``EMOTE_RECONCILE_AUTO_MERGE=true``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT / "tools" / "emote_catalog" / "refresh_catalog.py"
MERGE = ROOT / "tools" / "emote_catalog" / "merge_catalog.py"
FRESH_CANDIDATES = ROOT / "data" / "emote_reconciliation_candidates.json"
FRESH_AUDIT = ROOT / "data" / "emote_reconciliation_status.json"


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").casefold() in {"1", "true", "yes", "on"}


def main() -> int:
    if not _truthy("EMOTE_RECONCILE_ENABLED"):
        raise SystemExit(
            "Refusing to start: set EMOTE_RECONCILE_ENABLED=true explicitly."
        )
    if os.environ.get("EMOTE_RECONCILE_CONFIRM") != "DEDICATED_TEST_ROOM":
        raise SystemExit(
            "Refusing to start: set EMOTE_RECONCILE_CONFIRM=DEDICATED_TEST_ROOM."
        )

    room_id = os.environ.get("EMOTE_RECONCILE_ROOM_ID", "").strip()
    token = os.environ.get("EMOTE_RECONCILE_BOT_TOKEN", "").strip()
    if not room_id or not token:
        raise SystemExit(
            "Set EMOTE_RECONCILE_ROOM_ID and EMOTE_RECONCILE_BOT_TOKEN "
            "through secure environment variables."
        )
    if room_id == os.environ.get("HIGHRISE_ROOM_ID", "").strip():
        raise SystemExit(
            "The reconciliation room must differ from HIGHRISE_ROOM_ID; "
            "production-room probing is blocked."
        )

    interval = max(
        900.0, float(os.environ.get("EMOTE_RECONCILE_INTERVAL_SECONDS", "86400"))
    )
    auto_merge = _truthy("EMOTE_RECONCILE_AUTO_MERGE")
    require_measured_duration = _truthy(
        "EMOTE_RECONCILE_REQUIRE_MEASURED_DURATION"
    )
    child_env = os.environ.copy()
    child_env.update(
        {
            # Every cycle also re-probes the existing runtime catalog
            # (config/emotes.json), not just freshly discovered source
            # candidates, and removes any entry Highrise now explicitly
            # rejects. Merging newly confirmed ids into that catalog is
            # opt-in: see EMOTE_RECONCILE_AUTO_MERGE in the module docstring.
            "EMOTE_CANDIDATES_PATH": str(FRESH_CANDIDATES),
            "EMOTE_VERIFY_CANDIDATES": str(FRESH_CANDIDATES),
            "EMOTE_VERIFY_AUDIT": str(FRESH_AUDIT),
            "EMOTE_VERIFY_EXISTING": "true",
            "EMOTE_VERIFY_PRUNE_INVALID": "true",
            "EMOTE_VERIFY_EXIT_AFTER_RUN": "true",
            "EMOTE_VERIFY_AUTO_BUY": "false",
            "EMOTE_VERIFY_REQUIRE_MEASURED_DURATION": (
                "true" if require_measured_duration else "false"
            ),
            "HIGHRISE_CATALOG_OUTPUT": str(FRESH_CANDIDATES),
            "EMOTE_MERGE_CANDIDATES_PATH": str(FRESH_CANDIDATES),
        }
    )

    while True:
        refresh = subprocess.run([sys.executable, str(REFRESH)], cwd=ROOT)
        if refresh.returncode == 0:
            probe = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "highrise",
                    "tools.emote_catalog.verify_emotes:EmoteVerifierBot",
                    room_id,
                    token,
                ],
                cwd=ROOT,
                env=child_env,
            )
            if probe.returncode:
                print(f"Live emote reconciliation exited with {probe.returncode}.")
            elif auto_merge:
                merge = subprocess.run(
                    [sys.executable, str(MERGE)], cwd=ROOT, env=child_env
                )
                if merge.returncode:
                    print(f"Auto-merge exited with {merge.returncode}.")
        else:
            print(f"Official catalog refresh exited with {refresh.returncode}.")
        print(f"Next emote reconciliation in {interval:g} seconds.")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())