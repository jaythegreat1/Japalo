"""
Stage 2 - Live verification / duration measurement.

This is a SEPARATE, standalone bot process - it does NOT touch the real
HighriseRoomBot in highrise_bot/bot.py, and it never runs automatically.
Run it yourself, ideally in a private/empty test room: it will visibly
trigger every "pending_verification" candidate from Stage 1, one at a time.

What it does, per candidate:
  1. Calls send_emote() with the catalog id. Highrise's own SDK raises a
     ResponseError (documented) when an emote id is rejected - so a
       candidate is only ever marked "id_confirmed" because Highrise itself
       accepted it, never guessed. Explicit invalid-ID responses are marked
       "id_invalid"; ambiguous failures become "needs_review" instead.
   2. A rejection whose message looks like an ownership/purchase lock is
      marked "requires_purchase", not "id_invalid". Optional auto-buy is
      disabled by default and guarded by a per-run purchase limit.
   3. Duration: WITH EMOTE_VERIFY_MEASURE_DURATION=true, after each confirmed
      emote it asks you (in the terminal) to press Enter the instant the
      animation visibly loops, and that elapsed time becomes
      duration_seconds ("measured"). Without it (the default), a confirmed
      id is immediately marked "verified" using a placeholder
      EMOTE_VERIFY_DEFAULT_DURATION (4.0s unless you set it) instead of
      staying stuck at "id_confirmed" forever - the emote id itself is
      already proven real by Highrise's own acceptance; duration only
      affects how tightly emote_loop.py times the repeat. Set
      EMOTE_VERIFY_REQUIRE_MEASURED_DURATION=true to go back to the old,
      strict behavior where an untimed id is never auto-merged.

Why the manual timing step is optional, not required: Highrise's API has
no "animation finished" event, so there is no automated way to measure a
loop precisely. That only affects loop-timing polish, not whether the
emote works - so id confirmation is enough to merge by default, and precise
timing can be filled in later, per-emote, whenever someone gets around to
watching it.

Progress is saved to candidates.json after every single item, so this is
safe to stop (Ctrl+C) and resume later - already-processed candidates
(anything not "pending_verification") are skipped on the next run.

Setup (mirrors main.py's env vars):
    export HIGHRISE_ROOM_ID=...         # use a private/empty test room
    export HIGHRISE_BOT_TOKEN=...
    export EMOTE_VERIFY_LIMIT=40                 # optional, default 40
    export EMOTE_VERIFY_MEASURE_DURATION=true    # optional, default false
    export EMOTE_VERIFY_DELAY_SECONDS=1.5        # optional, default 1.5
     export EMOTE_VERIFY_AUTO_BUY=false            # optional, default false
     export EMOTE_VERIFY_AUTO_BUY_LIMIT=0          # optional, default 0

Run:
    pip install highrise-bot-sdk
    python -m highrise tools.emote_catalog.verify_emotes:EmoteVerifierBot \
        "$HIGHRISE_ROOM_ID" "$HIGHRISE_BOT_TOKEN"

Re-run as many times as you like until nothing "pending_verification" is
left. By default a confirmed id becomes "verified" right away with a
placeholder duration (see EMOTE_VERIFY_DEFAULT_DURATION above) so
merge_catalog.py (Stage 3) can pick it up on the next run without anyone
timing it by hand. If you skip duration for an id during a
EMOTE_VERIFY_MEASURE_DURATION=true run (typing 's'), or you've set
EMOTE_VERIFY_REQUIRE_MEASURED_DURATION=true, it stays "id_confirmed"
instead, and merge_catalog.py will not pick it up until it is timed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from highrise import BaseBot, SessionMetadata

ROOT = Path(__file__).resolve().parent.parent.parent
RUNTIME_CATALOG_PATH = ROOT / "config" / "emotes.json"
CANDIDATES_PATH = Path(
    os.environ.get(
        "EMOTE_VERIFY_CANDIDATES",
        str(ROOT / "tools" / "emote_catalog" / "data" / "candidates.json"),
    )
)
AUDIT_PATH = Path(
    os.environ.get(
        "EMOTE_VERIFY_AUDIT",
        str(ROOT / "data" / "emote_runtime_status.json"),
    )
)
LIMIT = int(os.environ.get("EMOTE_VERIFY_LIMIT", "40"))
MEASURE_DURATION = (
    os.environ.get("EMOTE_VERIFY_MEASURE_DURATION", "false").casefold() == "true"
)
DELAY_SECONDS = float(os.environ.get("EMOTE_VERIFY_DELAY_SECONDS", "1.5"))
# An id Highrise itself accepted ("id_confirmed") used to sit there forever
# unless someone manually timed it, because merge_catalog.py (Stage 3) only
# merges "verified" entries. That made adding new emotes effectively require
# a human to watch and time every single one. duration_seconds only controls
# how long emote_loop.py waits before re-sending the same emote to keep a
# loop going - it is not required for the id to work, so a placeholder value
# is a safe default: the emote plays correctly, the loop just isn't
# frame-perfectly timed until someone measures the real duration later.
DEFAULT_DURATION_SECONDS = float(
    os.environ.get("EMOTE_VERIFY_DEFAULT_DURATION", "4.0")
)
# Set this to true to go back to the old strict behavior: a confirmed id
# without a real measured (or cross-checked) duration stays "id_confirmed"
# and is never auto-merged.
REQUIRE_MEASURED_DURATION = os.environ.get(
    "EMOTE_VERIFY_REQUIRE_MEASURED_DURATION", "false"
).casefold() in {"1", "true", "yes", "on"}
PURCHASE_REQUIRED_KEYWORDS = (
    # Best-guess wording, not confirmed Highrise wording. Tighten this list
    # after observing real rejection messages from the verifier.
    "own",
    "purchase",
    "buy",
    "insufficient",
    "afford",
    "wallet",
    "gold",
    "bubbles",
    "do not have",
    "don't have",
)
AUTO_BUY = os.environ.get("EMOTE_VERIFY_AUTO_BUY", "false").casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
AUTO_BUY_LIMIT = int(os.environ.get("EMOTE_VERIFY_AUTO_BUY_LIMIT", "0"))

# If this many consecutive candidates fail in a row, stop and say so rather
# than silently marking a whole run "id_invalid" - that pattern usually
# means a connection/auth problem, not that every single id is genuinely
# bad.
CONSECUTIVE_FAILURE_ABORT_THRESHOLD = int(
    os.environ.get("EMOTE_VERIFY_ABORT_THRESHOLD", "5")
)
VERIFY_EXISTING = os.environ.get("EMOTE_VERIFY_EXISTING", "false").casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
PRUNE_INVALID = os.environ.get("EMOTE_VERIFY_PRUNE_INVALID", "false").casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
EXIT_AFTER_RUN = os.environ.get("EMOTE_VERIFY_EXIT_AFTER_RUN", "false").casefold() in {
    "1",
    "true",
    "yes",
    "on",
}


def _load_candidates() -> list[dict]:
    if not CANDIDATES_PATH.exists():
        raise SystemExit(
            f"No candidates file at {CANDIDATES_PATH}. Run fetch_catalog.py "
            "(Stage 1) first."
        )
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_candidates(candidates: list[dict]) -> None:
    with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)


def _include_runtime_catalog(candidates: list[dict]) -> list[dict]:
    """Add the current runtime catalog to the same live probe queue.

    Discovery candidates prove official metadata; runtime entries prove that
    Highrise still accepts the animation. Keeping both in one queue makes a
    scheduled maintenance run able to detect removals and newly blocked IDs.
    """
    if not VERIFY_EXISTING or not RUNTIME_CATALOG_PATH.exists():
        return candidates

    with RUNTIME_CATALOG_PATH.open("r", encoding="utf-8") as handle:
        runtime_entries = json.load(handle)
    by_id = {entry.get("catalog_item_id"): entry for entry in candidates}
    for entry in runtime_entries:
        emote_id = entry.get("id")
        if not emote_id:
            continue
        candidate = by_id.get(emote_id)
        if candidate is None:
            candidate = {
                "name": entry["name"],
                "rarity": entry["rarity"],
                "catalog_item_id": emote_id,
                "duration_seconds": entry["duration_seconds"],
                "status": "pending_verification",
                "source": "runtime_catalog",
            }
            candidates.append(candidate)
            by_id[emote_id] = candidate
        else:
            candidate["source"] = "runtime_catalog"
            candidate["runtime_duration_seconds"] = entry["duration_seconds"]
            # A scheduled reconciliation must re-check existing runtime
            # entries even when their previous result was accepted or locked.
            candidate["status"] = "pending_verification"
            candidate["runtime_check"] = "not_checked"
            candidate.pop("note", None)
            candidate.pop("error_class", None)
    return candidates


def _save_audit(candidates: list[dict]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    audit = {
        "checked_at": now,
        "entries": [
            {
                "name": candidate.get("name"),
                "id": candidate.get("catalog_item_id"),
                "rarity": candidate.get("rarity"),
                "status": candidate.get("status"),
                "note": candidate.get("note"),
                "source": candidate.get("source", "discovery"),
                "source_check": candidate.get("source_check", "unknown"),
                "release_state": candidate.get("release_state", "unknown"),
                "runtime_check": candidate.get("runtime_check", "not_checked"),
                "error_class": candidate.get("error_class"),
            }
            for candidate in candidates
            if candidate.get("catalog_item_id")
        ],
    }
    AUDIT_PATH.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prune_invalid_runtime_entries(candidates: list[dict]) -> int:
    """Remove only IDs Highrise explicitly rejected from the runtime catalog.

    Purchase/ownership errors are intentionally retained: they identify a
    real item that this bot cannot currently use, not an invalid animation.
    """
    invalid_ids = {
        candidate["catalog_item_id"]
        for candidate in candidates
        if candidate.get("source") == "runtime_catalog"
        and candidate.get("status") == "id_invalid"
    }
    if not invalid_ids or not RUNTIME_CATALOG_PATH.exists():
        return 0

    with RUNTIME_CATALOG_PATH.open("r", encoding="utf-8") as handle:
        existing = json.load(handle)
    kept = [entry for entry in existing if entry.get("id") not in invalid_ids]
    removed = len(existing) - len(kept)
    if removed:
        RUNTIME_CATALOG_PATH.write_text(
            json.dumps(kept, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return removed


def _looks_purchase_related(message: str) -> bool:
    lowered = message.casefold()
    return any(
        re.search(rf"\b{re.escape(keyword)}\b", lowered)
        for keyword in PURCHASE_REQUIRED_KEYWORDS
    ) or "do not have" in lowered or "don't have" in lowered


def _looks_explicitly_invalid(message: str) -> bool:
    """Recognize only clear Highrise rejection wording.

    Unknown/network/auth failures must not become deletion signals. This
    conservative classifier is intentionally narrower than the purchase
    classifier and sends ambiguous errors to needs_review.
    """
    lowered = message.casefold()
    phrases = (
        "invalid emote",
        "invalid id",
        "emote does not exist",
        "emote not found",
        "item does not exist",
        "item not found",
        "unknown emote",
        "not a valid emote",
    )
    return any(phrase in lowered for phrase in phrases)


def _print_status_breakdown(candidates: list[dict]) -> None:
    statuses = (
        "verified",
        "id_confirmed",
        "requires_purchase",
        "id_invalid",
        "pending_verification",
    )
    counts = {status: 0 for status in statuses}
    for candidate in candidates:
        status = candidate.get("status")
        if status in counts:
            counts[status] += 1
    print("\nStatus breakdown:")
    for status in statuses:
        print(f"  {status}: {counts[status]}")


async def _ask_duration_seconds(name: str) -> float | None:
    """Blocking console prompt, run off the event loop via an executor so
    the bot connection stays alive while you watch the room."""
    loop = asyncio.get_event_loop()
    print(
        f"  Watching '{name}' loop in-room. Press Enter the instant it "
        "repeats (or type 's' + Enter to skip timing this one): ",
        end="",
        flush=True,
    )
    start = loop.time()
    answer = await loop.run_in_executor(None, sys.stdin.readline)
    elapsed = loop.time() - start
    if answer.strip().casefold() == "s":
        return None
    return round(elapsed, 6)


class EmoteVerifierBot(BaseBot):
    async def _try_send(
        self, catalog_id: str, my_id: str
    ) -> tuple[bool, Exception | None]:
        try:
            await self.highrise.send_emote(catalog_id, my_id)
        except Exception as error:
            return False, error
        return True, None

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        my_id = getattr(self.highrise, "my_id", None) or getattr(
            session_metadata, "user_id", None
        )
        if not my_id:
            raise SystemExit(
                "Could not determine the bot's own user id from this SDK "
                "version. Check self.highrise.my_id / SessionMetadata in "
                "your installed highrise-bot-sdk and adjust this line."
            )

        candidates = _include_runtime_catalog(_load_candidates())
        pending = [c for c in candidates if c.get("status") == "pending_verification"]
        print(
            f"{len(pending)} pending candidate(s); processing up to {LIMIT} "
            f"this run (measure_duration={MEASURE_DURATION})."
        )

        processed = 0
        consecutive_failures = 0
        purchases = 0
        for candidate in pending:
            if processed >= LIMIT:
                break

            catalog_id = candidate["catalog_item_id"]
            name = candidate["name"]

            ok, error = await self._try_send(catalog_id, my_id)
            if not ok:
                assert error is not None
                error_message = str(error)
                if _looks_purchase_related(error_message):
                    candidate["status"] = "requires_purchase"
                    candidate["runtime_check"] = "purchase_locked"
                    candidate["error_class"] = type(error).__name__
                    candidate["note"] = error_message
                    consecutive_failures = 0
                    print(
                        f"  [LOCKED] {name!r} ({catalog_id}) - "
                        f"{error_message}"
                    )

                    if AUTO_BUY and purchases < AUTO_BUY_LIMIT:
                        try:
                            buy_result = await self.highrise.buy_item(catalog_id)
                        except Exception as buy_error:
                            print(
                                f"      auto-buy failed for {name!r} "
                                f"({catalog_id}) - {buy_error}"
                            )
                        else:
                            if buy_result == "success":
                                purchases += 1
                                retry_ok, retry_error = await self._try_send(
                                    catalog_id, my_id
                                )
                                if retry_ok:
                                    candidate["status"] = "id_confirmed"
                                    candidate.pop("note", None)
                                    print(
                                        f"      auto-buy succeeded; "
                                        f"{name!r} accepted on retry."
                                    )
                                else:
                                    retry_message = str(retry_error)
                                    candidate["note"] = retry_message
                                    print(
                                        f"      auto-buy succeeded but retry "
                                        f"remains locked - {retry_message}"
                                    )
                            else:
                                print(
                                    f"      auto-buy did not complete for "
                                    f"{name!r}: {buy_result}"
                                )
                    processed += 1
                    _save_candidates(candidates)
                    await asyncio.sleep(DELAY_SECONDS)
                    continue

                candidate["error_class"] = type(error).__name__
                candidate["note"] = error_message
                if _looks_explicitly_invalid(error_message):
                    candidate["status"] = "id_invalid"
                    candidate["runtime_check"] = "rejected"
                    print(f"  [INVALID] {name!r} ({catalog_id}) - {error_message}")
                else:
                    candidate["status"] = "needs_review"
                    candidate["runtime_check"] = "unknown"
                    print(
                        f"  [REVIEW] {name!r} ({catalog_id}) - "
                        f"ambiguous runtime failure: {error_message}"
                    )
                processed += 1
                consecutive_failures += 1
                _save_candidates(candidates)
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT_THRESHOLD:
                    print(
                        f"\n{consecutive_failures} failures in a row - "
                        "stopping early in case this is a connection/auth "
                        "issue rather than genuinely bad ids. Check the "
                        "room/token and re-run."
                    )
                    _print_status_breakdown(candidates)
                    _save_audit(candidates)
                    if PRUNE_INVALID:
                        removed = _prune_invalid_runtime_entries(candidates)
                        print(f"Pruned {removed} explicitly invalid runtime emote(s).")
                    if EXIT_AFTER_RUN:
                        raise SystemExit(1)
                    return
                await asyncio.sleep(DELAY_SECONDS)
                continue

            consecutive_failures = 0
            candidate["status"] = "id_confirmed"
            candidate["runtime_check"] = "accepted"
            candidate.pop("error_class", None)
            print(f"  [OK] {name!r} ({catalog_id}) accepted by Highrise.")

            if candidate.get("source") != "runtime_catalog":
                measured: float | None = None
                if MEASURE_DURATION:
                    measured = await _ask_duration_seconds(name)
                    if measured is not None:
                        candidate["duration_seconds"] = measured
                        candidate["status"] = "verified"
                        candidate["duration_source"] = "measured"
                        print(f"      duration_seconds = {measured}")

                if measured is None:
                    if REQUIRE_MEASURED_DURATION:
                        print(
                            "      no measured duration and "
                            "EMOTE_VERIFY_REQUIRE_MEASURED_DURATION=true - "
                            "still id_confirmed, not yet 'verified'."
                        )
                    else:
                        candidate["duration_seconds"] = DEFAULT_DURATION_SECONDS
                        candidate["status"] = "verified"
                        candidate["duration_source"] = "default_placeholder"
                        print(
                            "      no duration measured - using placeholder "
                            f"duration_seconds = {DEFAULT_DURATION_SECONDS} "
                            "so this id can be merged now; re-run with "
                            "EMOTE_VERIFY_MEASURE_DURATION=true later to "
                            "replace it with a real timing."
                        )

            processed += 1
            _save_candidates(candidates)  # after every item - safe to Ctrl+C
            await asyncio.sleep(DELAY_SECONDS)

        remaining = len(pending) - processed
        print(f"\nProcessed {processed} candidate(s) this run.")
        if remaining > 0:
            print(f"{remaining} still pending - re-run to continue.")
        _print_status_breakdown(candidates)
        _save_audit(candidates)
        if PRUNE_INVALID:
            removed = _prune_invalid_runtime_entries(candidates)
            print(f"Pruned {removed} explicitly invalid runtime emote(s).")
        print("Done - stop this process (Ctrl+C) now.")
        if EXIT_AFTER_RUN:
            raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(
        "Run this via the highrise SDK launcher, not directly:\n"
        '  python -m highrise tools.emote_catalog.verify_emotes:EmoteVerifierBot '
        '"$HIGHRISE_ROOM_ID" "$HIGHRISE_BOT_TOKEN"'
    )
