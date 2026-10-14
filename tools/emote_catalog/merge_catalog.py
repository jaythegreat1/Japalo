"""
Stage 3 - Merge verified emotes into config/emotes.json.

Takes Stage 2's output (candidates.json entries with status == "verified" -
meaning the id was confirmed live AND a real duration_seconds was
measured) and appends the new ones onto the existing curated catalog,
skipping anything whose id is already present.

Also applies the removals Ammar reported directly (2026-09-23): "Hero
Entrance" (previously #67, id emote-hero) and "Headball" (previously #72,
id emote-headball) don't work, so they're dropped from the existing 75
before anything new is merged in.

IMPORTANT - read before running: emote numbers used by !emote/!emotelist/
!fav are just each entry's position in this file, not a stored id. Removing
two entries shifts every later emote's number down. Anyone who saved a
!fav slot pointing at a number above 67 will now point at a different
emote after this runs. There's no way to remove dead entries without that
side effect - just worth knowing before you announce the update.

Usage:
    python merge_catalog.py            # writes config/emotes.json
    python merge_catalog.py --dry-run  # report only, writes nothing
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EXISTING_CATALOG_PATH = ROOT / "config" / "emotes.json"
CANDIDATES_PATH = Path(
    os.environ.get(
        "EMOTE_MERGE_CANDIDATES_PATH",
        str(Path(__file__).parent / "data" / "candidates.json"),
    )
)

# Reported broken by Ammar on 2026-09-23.
REMOVE_IDS = {"emote-hero", "emote-headball"}


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    existing = json.loads(EXISTING_CATALOG_PATH.read_text(encoding="utf-8"))
    removed = [entry for entry in existing if entry["id"] in REMOVE_IDS]
    kept = [entry for entry in existing if entry["id"] not in REMOVE_IDS]
    for entry in removed:
        print(f"Removing (reported broken): {entry['name']} ({entry['id']})")
    missing = REMOVE_IDS - {entry["id"] for entry in removed}
    if missing:
        print(f"Note: {sorted(missing)} not found in the current catalog - already gone?")

    if not CANDIDATES_PATH.exists():
        print(
            f"\nNo candidates file at {CANDIDATES_PATH} - nothing new to add. "
            "Run fetch_catalog.py and verify_emotes.py first if you want more "
            "than the removal applied."
        )
        candidates: list[dict] = []
    else:
        candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))

    candidate_by_id = {
        candidate.get("catalog_item_id"): candidate
        for candidate in candidates
        if candidate.get("catalog_item_id") and candidate.get("name")
    }
    existing_ids = {entry["id"] for entry in kept}
    renamed_existing = 0
    kept_with_current_names = []
    for entry in kept:
        candidate = candidate_by_id.get(entry["id"])
        if candidate is not None and candidate["name"] != entry["name"]:
            entry = {**entry, "name": candidate["name"]}
            renamed_existing += 1
        kept_with_current_names.append(entry)
    kept = kept_with_current_names

    to_add = []
    placeholder_duration_count = 0
    skipped_by_status: dict[str, int] = {}
    skipped_duplicate = 0
    for candidate in candidates:
        if candidate.get("status") != "verified":
            status = candidate.get("status") or "missing_status"
            skipped_by_status[status] = skipped_by_status.get(status, 0) + 1
            continue
        catalog_id = candidate["catalog_item_id"]
        if catalog_id in existing_ids:
            skipped_duplicate += 1
            continue
        if candidate.get("duration_source") == "default_placeholder":
            placeholder_duration_count += 1
        to_add.append(
            {
                "name": candidate["name"],
                "id": catalog_id,
                "rarity": candidate["rarity"],
                "duration_seconds": candidate["duration_seconds"],
            }
        )
        existing_ids.add(catalog_id)

    merged = kept + to_add

    print(f"\nExisting entries kept: {len(kept)} (removed {len(removed)})")
    print(f"Existing names synchronized from Highrise: {renamed_existing}")
    print(f"New verified entries added: {len(to_add)}")
    if placeholder_duration_count:
        print(
            f"  (of which {placeholder_duration_count} used a placeholder "
            "duration_seconds - the id is confirmed real, the loop timing "
            "just hasn't been measured by eye yet; re-run verify_emotes.py "
            "with EMOTE_VERIFY_MEASURE_DURATION=true to refine those)"
        )
    for status, count in sorted(skipped_by_status.items()):
        print(f"Skipped ({status}): {count}")
    print(f"Skipped (id already in catalog): {skipped_duplicate}")
    print(f"Final catalog size: {len(merged)}")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    EXISTING_CATALOG_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {EXISTING_CATALOG_PATH}")

    # Self-check: reuse the bot's own loader/validator so a bad merge is
    # caught right here, not at bot startup.
    sys.path.insert(0, str(ROOT))
    from highrise_bot.emotes import load_catalog  # noqa: E402

    catalog = load_catalog(EXISTING_CATALOG_PATH)
    print(
        f"Validated: {len(catalog)} emotes load cleanly via "
        "highrise_bot.emotes.load_catalog()."
    )


if __name__ == "__main__":
    main()
