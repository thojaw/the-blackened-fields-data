#!/usr/bin/env python3
"""
Regenerates the repo-root index.json from every <slug>/<year>/festival.json
in the repo.

No third-party dependencies (stdlib only) so it runs anywhere Python 3.8+
runs, including from a GitHub Actions runner with no setup step.

Usage:
  python3 scripts/generate-index.py [--out PATH]

Options:
  --out PATH   Write to PATH instead of <repo-root>/index.json (handy for
               testing without touching the real file).

The index shape is documented in schema/festival-index.schema.json and in
AGENTS.md. Regeneration always rebuilds all entries from scratch (there's
too few festivals for incremental updates to be worth the complexity) --
this script is what CI runs whenever a festival.json changes.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTISTS_REGISTRY_PATH = os.path.join(REPO_ROOT, "artists.json")
SCHEMA_VERSION = 2
TOP_GENRES_LIMIT = 10

# Thresholds for the completeness/stars heuristic -- see AGENTS.md
# "Completeness / stars" for the reasoning behind these numbers and the
# content/schedule combination table below.
CONTENT_COMPLETE_THRESHOLD = 0.9  # >= this fraction of artists have imageUrl + description
SCHEDULE_FULL_THRESHOLD = 0.9  # >= this fraction of artists have startTime

# (contentLevel, scheduleLevel) -> stars. Content (lineup announced, pictures,
# descriptions, links) fills in early and independently of the schedule
# (running order, per-artist start times), which historically lands last --
# so a fully-announced, fully-pictured festival with no schedule yet caps at
# 3 stars rather than jumping straight to 5 once a single flag flips.
STARS_TABLE = {
    ("none", "none"): 1,
    ("none", "partial"): 1,
    ("none", "full"): 1,
    ("partial", "none"): 2,
    ("partial", "partial"): 3,
    ("partial", "full"): 3,
    ("complete", "none"): 3,
    ("complete", "partial"): 4,
    ("complete", "full"): 5,
}

# Thresholds for the lineup profile -- see AGENTS.md "Lineup profile". Artist
# popularity is the registry's 1 (local/niche) to 10 (world class) score.
LINEUP_TOP_N = 3  # "top" = mean popularity of the N most popular artists
LINEUP_TOP_STARS = 8.5  # top >= this -> "stars"
LINEUP_TOP_STRONG = 6.5  # top >= this -> "strong", else "modest"
LINEUP_CORE_MIN_POPULARITY = 5  # "core" = share of artists with popularity >= this
LINEUP_DISCOVERY_MAX_POPULARITY = 3  # "discovery" = share of artists with popularity <= this
LINEUP_DEPTH_UNDERGROUND = 0.8  # discovery share >= this -> "underground"
LINEUP_DEPTH_DEEP = 0.6  # core share >= this -> "deep"
LINEUP_DEPTH_SOLID = 0.45  # core share >= this -> "solid"
LINEUP_DEPTH_DISCOVERY = 0.4  # discovery share >= this -> "discovery", else "mixed"
LINEUP_LOW_CONFIDENCE_BELOW = 10  # fewer scored artists than this -> lowConfidence


def load_popularity_by_id():
    """Registry artist id -> popularity (only entries that have one)."""
    try:
        with open(ARTISTS_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        a["id"]: a["popularity"]
        for a in registry
        if isinstance(a.get("popularity"), int)
    }


def find_festival_files():
    """Yield (path, slug, folder_year) for every festival.json in the repo."""
    pattern = os.path.join(REPO_ROOT, "*", "*", "festival.json")
    for path in sorted(glob.glob(pattern)):
        parts = path.split(os.sep)
        slug, folder_year = parts[-3], parts[-2]
        yield path, slug, folder_year


def compute_completeness(data, artists):
    running_order_exists = bool(data.get("runningOrderExists"))
    n = len(artists)

    if n == 0:
        artist_info_coverage = 0.0
        schedule_coverage = 0.0
    else:
        artist_info_coverage = sum(
            1 for a in artists if a.get("imageUrl") and a.get("description")
        ) / n
        schedule_coverage = sum(1 for a in artists if a.get("startTime")) / n

    if n == 0:
        content_level = "none"
    elif artist_info_coverage >= CONTENT_COMPLETE_THRESHOLD:
        content_level = "complete"
    else:
        content_level = "partial"

    if not running_order_exists:
        schedule_level = "none"
    elif schedule_coverage >= SCHEDULE_FULL_THRESHOLD:
        schedule_level = "full"
    else:
        schedule_level = "partial"

    return {
        "stars": STARS_TABLE[(content_level, schedule_level)],
        "contentLevel": content_level,
        "scheduleLevel": schedule_level,
        "artistInfoCoverage": round(artist_info_coverage, 3),
        "scheduleCoverage": round(schedule_coverage, 3),
    }


def compute_lineup(artists, popularity_by_id):
    """Popularity profile of the lineup, or None if no artist has a score."""
    scores = sorted(
        (
            popularity_by_id[a["globalId"]]
            for a in artists
            if a.get("globalId") in popularity_by_id
        ),
        reverse=True,
    )
    n = len(scores)
    if n == 0:
        return None

    top_scores = scores[:LINEUP_TOP_N]
    headliners = sum(top_scores) / len(top_scores)
    core = sum(1 for p in scores if p >= LINEUP_CORE_MIN_POPULARITY) / n
    discovery = sum(1 for p in scores if p <= LINEUP_DISCOVERY_MAX_POPULARITY) / n

    if headliners >= LINEUP_TOP_STARS:
        top = "stars"
    elif headliners >= LINEUP_TOP_STRONG:
        top = "strong"
    else:
        top = "modest"

    if discovery >= LINEUP_DEPTH_UNDERGROUND:
        depth = "underground"
    elif core >= LINEUP_DEPTH_DEEP:
        depth = "deep"
    elif core >= LINEUP_DEPTH_SOLID:
        depth = "solid"
    elif discovery >= LINEUP_DEPTH_DISCOVERY:
        depth = "discovery"
    else:
        depth = "mixed"

    return {
        "top": top,
        "depth": depth,
        "headliners": round(headliners, 1),
        "core": round(core, 3),
        "discovery": round(discovery, 3),
        "scoredArtists": n,
        "lowConfidence": n < LINEUP_LOW_CONFIDENCE_BELOW,
    }


def build_entry(path, slug, popularity_by_id):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    links = data.get("links", []) or []
    stages = data.get("stages", []) or []
    translations = data.get("translations", []) or []
    artists = data.get("artists", []) or []

    genre_counts = collections.Counter()
    for artist in artists:
        for genre in artist.get("genres", []) or []:
            genre_counts[genre] += 1
    top_genres = dict(
        sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_GENRES_LIMIT]
    )

    entry = {
        "id": data["id"],
        "slug": slug,
        "year": data["year"],
        "name": data["name"],
        "path": os.path.relpath(path, REPO_ROOT).replace(os.sep, "/"),
        "defaultLang": data["defaultLang"],
        "utcOffsetHours": data["utcOffsetHours"],
        "runningOrderExists": data["runningOrderExists"],
        "version": data["version"],
        "visible": data.get("visible", True),
        "festivalDays": data.get("festivalDays", []),
        "isMultiStage": len(stages) > 1,
        "translationLangs": [t["lang"] for t in translations],
        "topGenres": top_genres,
        "completeness": compute_completeness(data, artists),
        "counts": {
            "artists": len(artists),
            "stages": len(stages),
            "news": len(data.get("news", []) or []),
            "events": len(data.get("events", []) or []),
            "links": len(links),
            "globalLinks": sum(1 for link in links if not link.get("artistId")),
        },
    }
    lineup = compute_lineup(artists, popularity_by_id)
    if lineup is not None:
        entry["lineup"] = lineup
    return entry


def build_index():
    popularity_by_id = load_popularity_by_id()
    entries = [build_entry(path, slug, popularity_by_id) for path, slug, _ in find_festival_files()]
    entries.sort(key=lambda e: (e["festivalDays"][0] if e["festivalDays"] else "", e["name"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "festivals": entries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "index.json"), help="Output path (default: <repo-root>/index.json)")
    args = parser.parse_args()

    index = build_index()

    # Keep the file byte-identical (including generatedAt) when nothing about
    # the festivals actually changed, so a re-run doesn't produce a spurious
    # commit -- generatedAt would otherwise differ on every run even when
    # rebuilt from unchanged festival.json files, and CI's "commit if
    # changed" check would then never see a genuinely empty diff.
    if os.path.exists(args.out):
        with open(args.out, "r", encoding="utf-8") as f:
            try:
                previous = json.load(f)
            except json.JSONDecodeError:
                previous = None
        if previous and previous.get("festivals") == index["festivals"] and previous.get("schemaVersion") == index["schemaVersion"]:
            index["generatedAt"] = previous["generatedAt"]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(index['festivals'])} festival(s) to {os.path.relpath(args.out, REPO_ROOT)}")


if __name__ == "__main__":
    main()
