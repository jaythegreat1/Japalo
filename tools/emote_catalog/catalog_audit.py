"""Print an evidence-based audit of the current emote pipeline.

This command reports observed counts. It never pads the catalog toward a
target, changes config/emotes.json, or treats a missing field as proof.

Usage:
    python tools/emote_catalog/catalog_audit.py
    python tools/emote_catalog/catalog_audit.py --json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES_PATH = ROOT / "tools" / "emote_catalog" / "data" / "candidates.json"
RUNTIME_PATH = ROOT / "config" / "emotes.json"
AUDIT_PATH = ROOT / "data" / "emote_runtime_status.json"


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_report() -> dict:
    candidates = _load(CANDIDATES_PATH, [])
    runtime_catalog = _load(RUNTIME_PATH, [])
    runtime_audit = _load(AUDIT_PATH, {})
    audit_entries = runtime_audit.get("entries", [])

    statuses = Counter(str(entry.get("status", "needs_review")) for entry in candidates)
    release_states = Counter(
        str(entry.get("release_state", "unknown")) for entry in candidates
    )

    # Prefer the most recent live probe for runtime results. If no audit exists,
    # the configured runtime catalog is still reported as "configured", never
    # as live-verified.
    live_by_id = {
        entry.get("id"): entry
        for entry in audit_entries
        if entry.get("id")
    }
    live_verified = [
        entry
        for entry in audit_entries
        if entry.get("status") in {"verified", "id_confirmed"}
    ]
    rarity_counts = Counter(str(entry.get("rarity", "unknown")) for entry in live_verified)
    allowed_rarities = {"common", "none_", "uncommon", "rare", "epic"}

    report = {
        "total_discovered": len(candidates),
        "source_verified": sum(
            1 for entry in candidates if entry.get("source_check") == "verified"
        ),
        "verified_real_emotes": len(live_verified),
        "configured_runtime_emotes": len(runtime_catalog),
        "rare": rarity_counts.get("rare", 0),
        "epic": rarity_counts.get("epic", 0),
        "other_allowed_rarity": sum(
            count
            for rarity, count in rarity_counts.items()
            if rarity in allowed_rarities - {"rare", "epic"}
        ),
        "unreleased": sum(
            release_states[state] for state in ("unreleased", "removed")
        ),
        "future": release_states.get("future", 0),
        "historical": release_states.get("historical", 0),
        "preview": release_states.get("preview", 0),
        "unknown_release": release_states.get("unknown", 0),
        "invalid": statuses.get("id_invalid", 0),
        "requires_purchase": statuses.get("requires_purchase", 0),
        "needs_review": statuses.get("needs_review", 0)
        + statuses.get("pending_verification", 0)
        + statuses.get("id_confirmed", 0),
        "status_counts": dict(sorted(statuses.items())),
        "release_state_counts": dict(sorted(release_states.items())),
        "last_runtime_audit_at": runtime_audit.get("checked_at"),
        "runtime_audit_ids": len(live_by_id),
    }
    return report


def main() -> int:
    report = build_report()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    labels = (
        ("Total discovered", "total_discovered"),
        ("Source-verified records", "source_verified"),
        ("Verified real emotes", "verified_real_emotes"),
        ("Configured runtime emotes", "configured_runtime_emotes"),
        ("Rare", "rare"),
        ("Epic", "epic"),
        ("Other allowed rarity", "other_allowed_rarity"),
        ("Unreleased/removed", "unreleased"),
        ("Future", "future"),
        ("Historical", "historical"),
        ("Preview", "preview"),
        ("Unknown release state", "unknown_release"),
        ("Invalid", "invalid"),
        ("Requires purchase", "requires_purchase"),
        ("Needs review", "needs_review"),
    )
    print("Emote catalog audit")
    print("===================")
    for label, key in labels:
        print(f"{label}: {report[key]}")
    print(f"\nStatus counts: {report['status_counts']}")
    print(f"Release-state counts: {report['release_state_counts']}")
    if report["last_runtime_audit_at"]:
        print(f"Last runtime audit: {report['last_runtime_audit_at']}")
    else:
        print("Last runtime audit: none (run the live verifier in a test room)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())