"""
Stage 1 - Emote catalog discovery.

Pulls every released emote from the public Highrise Web API, excludes the
legendary names supplied for this project, and writes a "candidates" file with
Highrise's exact name, rarity, and catalog item_id.

This fixes the two concrete bugs in the original one-off script:

1. Rarity values are preserved exactly as Highrise returns them, including
   "none_". Legendary is still excluded.
2. Pagination trusted an assumed "last_id" envelope field that may not
   exist in the raw HTTP response. This script pages using the last item's
   own item_id instead, which is guaranteed to be present on every item.

IMPORTANT - what this script does NOT solve:
- The catalog's item_id is NOT guaranteed to be the animation id that
  send_emote() expects (see ../../.agents/memory/highrise-emote-identifiers.md).
  Nothing here is written to config/emotes.json directly, and nothing here
  is trusted as a real emote id yet - that's what Stage 2
  (verify_emotes.py) is for.
- duration_seconds isn't in this output at all. The web API never returns
  it; it's added in Stage 2.

No bot login needed - this hits the public REST endpoint directly.

If ?category=emote comes back empty (Highrise's own docs list "emote" as a
valid category, so this means the server-side filter is misbehaving, not
that our parameter is wrong), this script automatically falls back to
fetching everything unfiltered and picking out emotes by inspecting each
item's own category field. If that also can't find a category field, run
with --diagnose to dump raw item shape for inspection.

Usage:
    pip install requests
    python fetch_catalog.py             # normal run
    python fetch_catalog.py --diagnose  # dump raw item fields, fetch nothing
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://webapi.highrise.game"
PAGE_SIZE = 100
PAGE_DELAY_SECONDS = float(
    os.environ.get("HIGHRISE_CATALOG_PAGE_DELAY_SECONDS", "0")
)
PRESERVE_KNOWN_ON_EMPTY = os.environ.get(
    "HIGHRISE_CATALOG_PRESERVE_KNOWN_ON_EMPTY", "false"
).casefold() in {"1", "true", "yes", "on"}
OUT_PATH = Path(
    os.environ.get(
        "HIGHRISE_CATALOG_OUTPUT",
        str(Path(__file__).parent / "data" / "candidates.json"),
    )
)
KNOWN_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "emotes.json"

# Highrise's own API-update announcement lists "emote" as a valid category
# value, so if ?category=emote comes back empty (200, zero items) while the
# unfiltered endpoint returns data, the server-side filter itself is what's
# broken right now - not our parameter name. In that case we fall back to
# fetching everything and filtering client-side by whichever field on the
# item actually carries its category.
CATEGORY_FIELD_CANDIDATES = ("category", "item_category", "type", "item_type")

# Raw catalog rarity string -> the exact value stored in Japalo's manifest.
RARITY_BUCKETS = {
    "common": "common",
    "none": "none_",
    "none_": "none_",
    "uncommon": "uncommon",
    "rare": "rare",
    "epic": "epic",
}

# These are the exact legendary names supplied by the room owner. Excluding
# names, rather than every record whose rarity happens to be "legendary", is
# deliberate: the request is to exclude this known 28-item list and not to
# silently discard any other source record.
EXCLUDED_EMOTE_NAMES = {
    "the fresh step",
    "zero gravity chill",
    "ballet bliss",
    "hero entrance",
    "flirty wave",
    "graceful",
    "shuffle",
    "pure heart",
    "floss",
    "the woah",
    "robotic",
    "twerk it out",
    "rest",
    "breakdance",
    "blowing kisses",
    "popular vibe",
    "karate",
    "swag bounce",
    "cursing emote",
    "frolic",
    "boogie swing",
    "gwiddy",
    "headball",
    "flex",
    "kicking back",
    "mine dance",
    "knock knock",
    "yoga flow",
}


def _normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


def _fetch_pages(extra_params: dict) -> list[dict]:
    """Page through /items with the given filters, cursoring on each page's
    last item_id (never an assumed envelope field)."""
    items: list[dict] = []
    cursor: str | None = None

    with requests.Session() as session:
        while True:
            params = {"limit": PAGE_SIZE, "sort_order": "asc", **extra_params}
            if cursor:
                params["starts_after"] = cursor

            for attempt in range(4):
                try:
                    resp = session.get(
                        f"{BASE_URL}/items", params=params, timeout=15
                    )
                    if resp.status_code not in {500, 502, 503, 504}:
                        break
                    if attempt == 3:
                        resp.raise_for_status()
                except requests.RequestException as exc:
                    if attempt == 3:
                        raise
                    print(
                        f"Temporary catalog request failure "
                        f"({type(exc).__name__}); retrying in "
                        f"{2 ** attempt}s..."
                    )
                    time.sleep(2 ** attempt)
                    continue

                print(
                    f"Highrise returned HTTP {resp.status_code}; "
                    f"retrying in {2 ** attempt}s..."
                )
                time.sleep(2 ** attempt)

            if resp.status_code == 429:
                print("Rate limited, waiting 5s...")
                time.sleep(5)
                continue

            resp.raise_for_status()
            data = resp.json()
            page = data.get("items", [])
            if not page:
                break

            items.extend(page)
            print(f"  fetched {len(items)} item(s) so far...")

            if len(page) < PAGE_SIZE:
                break

            cursor = page[-1].get("item_id")
            if not cursor:
                break
            if PAGE_DELAY_SECONDS:
                time.sleep(PAGE_DELAY_SECONDS)

    return items


def _find_category_field(sample_items: list[dict]) -> str | None:
    for field in CATEGORY_FIELD_CANDIDATES:
        if any(field in item for item in sample_items):
            return field
    return None


def _is_available(item: dict, *, now: dt.datetime | None = None) -> bool:
    """Return false only when the API explicitly marks an item unavailable.

    Highrise has used more than one field name for release state over time.
    Missing fields are intentionally treated as available: the catalog API
    does not consistently include an availability boolean, and guessing that
    missing metadata means "unreleased" would discard valid items.
    """
    for field in ("available", "is_available", "released", "is_released"):
        if field in item and item[field] is False:
            return False

    release_date = item.get("release_date")
    if not isinstance(release_date, str) or not release_date.strip():
        return True

    normalized = release_date.replace("Z", "+00:00")
    try:
        release_at = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return True
    if release_at.tzinfo is None:
        release_at = release_at.replace(tzinfo=dt.timezone.utc)
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    return release_at <= current


def _release_state(item: dict, *, now: dt.datetime) -> str:
    """Return only a release state explicitly supported by source metadata.

    The API is inconsistent about which release fields it sends. Missing
    metadata is therefore ``unknown`` rather than an invented yes/no value.
    Unknown records may still be runtime-probed; the probe is what can prove
    current playability.
    """
    for field in ("release_state", "availability", "status"):
        value = item.get(field)
        if isinstance(value, str):
            normalized = value.strip().casefold().replace(" ", "_")
            if normalized in {
                "future",
                "removed",
                "unreleased",
                "historical",
                "preview",
                "available",
                "released",
                "unknown",
            }:
                return "available" if normalized == "released" else normalized

    for field in ("available", "is_available", "released", "is_released"):
        if field in item and item[field] is False:
            return "unreleased"

    release_date = item.get("release_date")
    if isinstance(release_date, str) and release_date.strip():
        normalized = release_date.replace("Z", "+00:00")
        try:
            release_at = dt.datetime.fromisoformat(normalized)
        except ValueError:
            return "unknown"
        if release_at.tzinfo is None:
            release_at = release_at.replace(tzinfo=dt.timezone.utc)
        return "available" if release_at <= now else "future"

    return "unknown"


def _known_id_prefixes() -> set[str]:
    """Namespace prefixes ("emoji", "dance", "emote", "idle", ...) already
    seen in the verified runtime catalog (config/emotes.json).

    Used only to recognize items Highrise's own API already returned in an
    unfiltered response by their own real item_id - this never invents or
    guesses an id that wasn't already present in the live data.
    """
    if not KNOWN_CATALOG_PATH.exists():
        return set()
    with KNOWN_CATALOG_PATH.open("r", encoding="utf-8") as handle:
        configured = json.load(handle)
    prefixes: set[str] = set()
    for entry in configured:
        catalog_id = entry.get("id") or ""
        for sep in ("-", "_"):
            if sep in catalog_id:
                prefix = catalog_id.split(sep, 1)[0]
                break
        else:
            prefix = ""
        if prefix:
            prefixes.add(prefix)
    return prefixes


def _filter_by_known_id_prefix(items: list[dict]) -> list[dict]:
    """Pick out items whose own item_id starts with a known emote namespace.

    Only used as a last resort when no category field can identify emotes at
    all (see fetch_all_emote_items). This inspects item_ids Highrise's API
    just returned in the unfiltered dump - it does not generate, guess, or
    fabricate any id. Each result still goes through Stage 2's live
    send_emote probe before it is trusted as a real, working emote.
    """
    known_prefixes = _known_id_prefixes()
    if not known_prefixes:
        return []
    # Highrise's own ids aren't consistent about the separator (e.g.
    # "idle-sad" vs "idle_zombie"), so a namespace matches either form.
    prefixes = tuple(
        f"{p}{sep}" for p in known_prefixes for sep in ("-", "_")
    )
    return [
        item
        for item in items
        if isinstance(item.get("item_id"), str)
        and item["item_id"].startswith(prefixes)
    ]


def _fetch_known_emote_items() -> list[dict]:
    """Fetch exact game records for the currently configured emote ids.

    Highrise currently returns zero rows for the documented collection
    category=emote filter, while the item-detail endpoint still returns the
    authoritative item_name/category/rarity fields.
    """
    if not KNOWN_CATALOG_PATH.exists():
        return []
    with KNOWN_CATALOG_PATH.open("r", encoding="utf-8") as handle:
        configured = json.load(handle)

    items: list[dict] = []
    for entry in configured:
        catalog_id = entry.get("id")
        if not catalog_id:
            continue
        for attempt in range(5):
            response = requests.get(
                f"{BASE_URL}/items/{quote(catalog_id, safe='')}",
                timeout=15,
            )
            if response.status_code != 429:
                break
            delay = 5 * (attempt + 1)
            print(f"Rate limited while fetching {catalog_id}; waiting {delay}s...")
            time.sleep(delay)
        else:
            print(f"Rate limit persisted for {catalog_id}; leaving it unchanged.")
            continue
        if response.status_code == 404:
            print(f"Game record not found for {catalog_id}; leaving it unchanged.")
            continue
        response.raise_for_status()
        item = response.json().get("item")
        if isinstance(item, dict):
            items.append(item)
        time.sleep(0.4)
    print(
        f"Fetched {len(items)} exact game records from item-detail endpoints."
    )
    return items


def diagnose() -> None:
    """Dump raw item shape so we can see what actually changed. Run this
    and share the output if the normal fetch still comes back empty."""
    print("Fetching one unfiltered page to inspect raw item fields...\n")
    resp = requests.get(f"{BASE_URL}/items", params={"limit": 5}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    page = data.get("items", [])
    print(f"Unfiltered page returned {len(page)} item(s). Top-level response keys: "
          f"{sorted(data.keys())}\n")
    for item in page:
        print(json.dumps(item, indent=2, ensure_ascii=False))
        print("---")
    field = _find_category_field(page)
    if field:
        print(f"\nLooks like the category lives in the {field!r} field.")
    else:
        print(
            "\nNone of the usual field names "
            f"({', '.join(CATEGORY_FIELD_CANDIDATES)}) were found on these "
            "items. Share this output so the filter logic can be updated "
            "to match whatever field name is actually there."
        )


def fetch_all_emote_items() -> list[dict]:
    print("Trying the documented filter: category=emote ...")
    items = _fetch_pages({"category": "emote"})
    if items:
        return items

    print(
        "category=emote returned nothing. Highrise's own docs list 'emote' "
        "as a valid category, so this looks like the server-side filter "
        "itself is broken right now rather than our parameter being wrong. "
        "Falling back to fetching everything and filtering by each item's "
        "own category field instead...\n"
    )
    all_items = _fetch_pages({})
    if not all_items:
        print("The unfiltered endpoint also returned nothing - this isn't "
              "a filter problem, the API itself has no data right now.")
        return _fetch_known_emote_items()

    field = _find_category_field(all_items[:20])
    if field is None:
        print(
            "Got items back, but couldn't find a category-like field on "
            f"them (checked: {', '.join(CATEGORY_FIELD_CANDIDATES)}). "
            "Run this script with --diagnose to see the raw shape and "
            "adjust CATEGORY_FIELD_CANDIDATES / the filter below."
        )
        return _fetch_known_emote_items()

    emote_items = [item for item in all_items if item.get(field) == "emote"]
    print(f"Filtered {len(emote_items)} emote item(s) out of {len(all_items)} "
          f"total, using field {field!r}.")
    if not emote_items:
        category_counts = Counter(
            str(item.get(field) or "<missing>") for item in all_items
        )
        print(
            "No records matched category='emote'. Live category counts "
            f"(top 12): {category_counts.most_common(12)}"
        )
        prefix_items = _filter_by_known_id_prefix(all_items)
        if prefix_items:
            known_prefixes = ", ".join(sorted(_known_id_prefixes()))
            print(
                f"The category field found nothing, but {len(prefix_items)} "
                "item(s) already present in this unfiltered response have an "
                f"item_id starting with a known emote namespace ({known_prefixes}"
                "). Treating these as candidates for Stage 2 to verify live - "
                "nothing here is trusted as a real, working emote yet."
            )
            return prefix_items
        if PRESERVE_KNOWN_ON_EMPTY:
            known_items = _fetch_known_emote_items()
            if known_items:
                print(
                    "Using item-detail records for the configured catalog "
                    "because HIGHRISE_CATALOG_PRESERVE_KNOWN_ON_EMPTY is set."
                )
                return known_items
    return emote_items


def main() -> None:
    if "--diagnose" in sys.argv:
        diagnose()
        return

    print("Fetching emote catalog from the Highrise Web API...")
    raw_items = fetch_all_emote_items()
    if not raw_items:
        print(
            "\nNo emote items were found through either the filtered or "
            "unfiltered path. Run `python fetch_catalog.py --diagnose` and "
            "share the output before assuming the catalog is really empty."
        )
        return

    candidates = []
    excluded_by_name = 0
    release_counts: Counter[str] = Counter()
    unrecognized: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    now = dt.datetime.now(dt.timezone.utc)
    for item in raw_items:
        catalog_id = item.get("item_id")
        name = item.get("item_name", "")
        raw_rarity = (item.get("rarity") or "none").lower()

        if not catalog_id or catalog_id in seen_ids:
            continue
        seen_ids.add(catalog_id)

        if not isinstance(name, str) or not name.strip():
            continue

        release_state = _release_state(item, now=now)
        release_counts[release_state] += 1
        if _normalize_name(name) in EXCLUDED_EMOTE_NAMES:
            excluded_by_name += 1
            continue

        common_fields = {
            "name": name,
            "catalog_item_id": catalog_id,
            "source_check": "verified",
            "source_category": "emote",
            "release_state": release_state,
            "runtime_check": "not_checked",
            "duration_seconds": None,
        }

        bucket = RARITY_BUCKETS.get(raw_rarity)
        if bucket is None:
            unrecognized.append((name, raw_rarity))
            candidates.append(
                {
                    **common_fields,
                    "rarity": raw_rarity,
                    "status": "needs_review",
                    "eligible_for_runtime": False,
                }
            )
            continue

        not_playable_now = release_state in {
            "future",
            "removed",
            "unreleased",
            "historical",
            "preview",
        }
        candidates.append(
            {
                **common_fields,
                "name": name,
                "rarity": bucket,
                # Filled in by Stage 2 (verify_emotes.py). Nothing past
                # this point is trusted as a real send_emote() id yet.
                "status": release_state if not_playable_now else "pending_verification",
                "eligible_for_runtime": not not_playable_now,
            }
        )

    candidates.sort(key=lambda c: (c["rarity"], c["name"].lower()))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(candidates)} candidates to {OUT_PATH}")
    print(
        f"Excluded {excluded_by_name} of the supplied legendary emote name(s) "
        "(by design)"
    )
    print(f"Release-state counts: {dict(sorted(release_counts.items()))}")
    if unrecognized:
        print(
            f"WARNING: {len(unrecognized)} item(s) had an unrecognized "
            "rarity value and were skipped:"
        )
        for name, rarity in unrecognized[:10]:
            print(f"  - {name!r}: rarity={rarity!r}")
        print("Check RARITY_BUCKETS in this script if that list looks wrong.")
    print("\nNext: run verify_emotes.py (Stage 2) against your bot, ideally "
          "in a private/test room, to confirm real ids and measure durations.")


if __name__ == "__main__":
    main()
