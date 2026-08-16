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
import datetime as dt
import glob
import json
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEMA_VERSION = 1


def find_festival_files():
    """Yield (path, slug, folder_year) for every festival.json in the repo."""
    pattern = os.path.join(REPO_ROOT, "*", "*", "festival.json")
    for path in sorted(glob.glob(pattern)):
        parts = path.split(os.sep)
        slug, folder_year = parts[-3], parts[-2]
        yield path, slug, folder_year


def build_entry(path, slug):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    links = data.get("links", []) or []
    stages = data.get("stages", []) or []
    translations = data.get("translations", []) or []

    return {
        "id": data["id"],
        "slug": slug,
        "year": data["year"],
        "name": data["name"],
        "path": os.path.relpath(path, REPO_ROOT).replace(os.sep, "/"),
        "defaultLang": data["defaultLang"],
        "utcOffsetHours": data["utcOffsetHours"],
        "runningOrderExists": data["runningOrderExists"],
        "version": data["version"],
        "festivalDays": data.get("festivalDays", []),
        "isMultiStage": len(stages) > 1,
        "translationLangs": [t["lang"] for t in translations],
        "counts": {
            "artists": len(data.get("artists", []) or []),
            "stages": len(stages),
            "news": len(data.get("news", []) or []),
            "events": len(data.get("events", []) or []),
            "links": len(links),
            "globalLinks": sum(1 for link in links if not link.get("artistId")),
        },
    }


def build_index():
    entries = [build_entry(path, slug) for path, slug, _ in find_festival_files()]
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
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(index['festivals'])} festival(s) to {os.path.relpath(args.out, REPO_ROOT)}")


if __name__ == "__main__":
    main()
