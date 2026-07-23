#!/usr/bin/env python3
"""
Deterministic query helper for festival.json data in this repo.

No third-party dependencies (stdlib only) so it runs anywhere Python 3.8+ runs.
This script does NOT interpret natural language — it exposes small, precise
subcommands. The calling agent/LLM is responsible for turning a user's
question into one of these calls (see ../SKILL.md for the mapping).

Repo layout assumed: <festival-slug>/<year>/festival.json

Run `query_festivals.py <command> --help` for per-command options.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
from difflib import SequenceMatcher

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def find_festival_files():
    """Yield (path, slug, year) for every festival.json in the repo."""
    pattern = os.path.join(REPO_ROOT, "*", "*", "festival.json")
    for path in sorted(glob.glob(pattern)):
        parts = path.split(os.sep)
        slug, year = parts[-3], parts[-2]
        yield path, slug, year


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def stage_name(data, stage_id):
    if not stage_id:
        return None
    for s in data.get("stages", []) or []:
        if s["id"] == stage_id:
            return s["name"]
    return stage_id


def to_minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def cmd_list_festivals(args):
    """List every known festival/year combination with basic identity info."""
    out = []
    for path, slug, year in find_festival_files():
        data = load(path)
        out.append({
            "slug": slug,
            "folderYear": year,
            "id": data.get("id"),
            "name": data.get("name"),
            "year": data.get("year"),
            "festivalDays": data.get("festivalDays"),
            "utcOffsetHours": data.get("utcOffsetHours"),
            "path": os.path.relpath(path, REPO_ROOT),
        })
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_resolve_festival(args):
    """
    Fuzzy-resolve a festival name (optionally + year) to a festival.json path.
    Prints ranked candidates as JSON; caller/LLM should disambiguate if the
    top matches are close, or if year is ambiguous (multiple years for the
    same festival and none/an unclear year was given by the user).
    """
    query = args.name.lower()
    candidates = []
    for path, slug, year in find_festival_files():
        data = load(path)
        name = data.get("name", "")
        score = max(similarity(query, name), similarity(query, slug.replace("-", " ")))
        if args.year and str(data.get("year")) == str(args.year):
            score += 0.5
        candidates.append({
            "score": round(score, 3),
            "slug": slug,
            "year": data.get("year"),
            "name": data.get("name"),
            "id": data.get("id"),
            "path": os.path.relpath(path, REPO_ROOT),
        })
    candidates.sort(key=lambda c: -c["score"])
    print(json.dumps(candidates[: args.limit], indent=2, ensure_ascii=False))


def cmd_resolve_artist(args):
    """
    Fuzzy-resolve an artist name within a given festival.json to one or more
    artist records. Prints ranked candidates with score, so the caller can
    decide whether the top match is confident enough or needs to ask the user.
    """
    data = load(args.file)
    query = args.name.lower()
    candidates = []
    for a in data.get("artists", []):
        score = similarity(query, a["name"])
        if query in a["name"].lower():
            score = max(score, 0.9)
        candidates.append({"score": round(score, 3), **a, "stageName": stage_name(data, a.get("stageId"))})
    candidates.sort(key=lambda c: -c["score"])
    print(json.dumps(candidates[: args.limit], indent=2, ensure_ascii=False))


def cmd_schedule(args):
    """
    Print the full schedule (artists + non-artist events) for a festival,
    optionally filtered to one dayDate (YYYY-MM-DD) and/or one stageId.
    Sorted by day then start time.
    """
    data = load(args.file)
    items = []
    for a in data.get("artists", []):
        if a.get("dayDate") and a.get("startTime"):
            items.append({
                "kind": "artist",
                "id": a["id"],
                "name": a["name"],
                "dayDate": a["dayDate"],
                "startTime": a["startTime"],
                "endTime": a.get("endTime"),
                "stageId": a.get("stageId"),
                "stageName": stage_name(data, a.get("stageId")),
                "annotation": a.get("annotation"),
            })
    for e in data.get("events", []) or []:
        items.append({
            "kind": "event",
            "id": e["id"],
            "name": e["title"],
            "dayDate": e["dayDate"],
            "startTime": e["startTime"],
            "endTime": e.get("endTime"),
            "stageId": e.get("stageId"),
            "stageName": stage_name(data, e.get("stageId")),
        })
    if args.day:
        items = [i for i in items if i["dayDate"] == args.day]
    if args.stage_id:
        items = [i for i in items if i["stageId"] == args.stage_id]
    items.sort(key=lambda i: (i["dayDate"], to_minutes(i["startTime"])))
    print(json.dumps(items, indent=2, ensure_ascii=False))


def cmd_overlaps(args):
    """
    Given a festival file + dayDate + startTime + endTime, list every other
    artist/event whose slot overlaps that window (any shared minutes count).
    Use this for 'what else is on at the same time as X' questions.
    """
    data = load(args.file)
    q_start, q_end = to_minutes(args.start), to_minutes(args.end)
    result = []
    for a in data.get("artists", []):
        if a.get("dayDate") != args.day or not a.get("startTime") or not a.get("endTime"):
            continue
        if args.exclude_id and a["id"] == args.exclude_id:
            continue
        s, e = to_minutes(a["startTime"]), to_minutes(a["endTime"])
        if s < q_end and e > q_start:
            result.append({
                "kind": "artist", "id": a["id"], "name": a["name"],
                "startTime": a["startTime"], "endTime": a["endTime"],
                "stageName": stage_name(data, a.get("stageId")),
            })
    for e in data.get("events", []) or []:
        if e["dayDate"] != args.day:
            continue
        s, en = to_minutes(e["startTime"]), to_minutes(e["endTime"])
        if s < q_end and en > q_start:
            result.append({
                "kind": "event", "id": e["id"], "name": e["title"],
                "startTime": e["startTime"], "endTime": e["endTime"],
                "stageName": stage_name(data, e.get("stageId")),
            })
    result.sort(key=lambda i: to_minutes(i["startTime"]))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_search_artist_everywhere(args):
    """
    Search an artist name across ALL festivals/years in the repo. Useful for
    'which festivals is X playing this year' or cross-festival lookups.
    """
    query = args.name.lower()
    results = []
    for path, slug, year in find_festival_files():
        data = load(path)
        for a in data.get("artists", []):
            score = similarity(query, a["name"])
            if query in a["name"].lower():
                score = max(score, 0.9)
            if score >= args.min_score:
                results.append({
                    "score": round(score, 3),
                    "festivalSlug": slug,
                    "festivalName": data.get("name"),
                    "festivalYear": data.get("year"),
                    "artist": a["name"],
                    "dayDate": a.get("dayDate"),
                    "startTime": a.get("startTime"),
                    "endTime": a.get("endTime"),
                    "stageName": stage_name(data, a.get("stageId")),
                })
    results.sort(key=lambda r: -r["score"])
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_day_part(args):
    """
    Classify a HH:MM time into a day-part bucket. Use to answer questions
    like 'who's playing Friday late night'. Bucket boundaries are a
    convention, not part of the schema — adjust with --late-night-start etc.
    if the user implies different boundaries.
    """
    minutes = to_minutes(args.time)
    buckets = [
        ("morning", 6 * 60, 12 * 60),
        ("afternoon", 12 * 60, 17 * 60),
        ("evening", 17 * 60, 21 * 60),
        ("night", 21 * 60, 24 * 60),
        ("late night", 0, 6 * 60),  # times after midnight, still "that night" in festival UX
    ]
    for label, start, end in buckets:
        if start <= minutes < end:
            print(json.dumps({"time": args.time, "bucket": label}))
            return
    print(json.dumps({"time": args.time, "bucket": None}))


def cmd_links(args):
    """List links for a festival, optionally filtered to one artistId (or 'global' for site-wide links only)."""
    data = load(args.file)
    links = data.get("links", [])
    if args.artist_id == "global":
        links = [l for l in links if not l.get("artistId")]
    elif args.artist_id:
        links = [l for l in links if l.get("artistId") == args.artist_id]
    print(json.dumps(links, indent=2, ensure_ascii=False))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list-festivals", help=cmd_list_festivals.__doc__)
    sp.set_defaults(func=cmd_list_festivals)

    sp = sub.add_parser("resolve-festival", help=cmd_resolve_festival.__doc__)
    sp.add_argument("name")
    sp.add_argument("--year")
    sp.add_argument("--limit", type=int, default=5)
    sp.set_defaults(func=cmd_resolve_festival)

    sp = sub.add_parser("resolve-artist", help=cmd_resolve_artist.__doc__)
    sp.add_argument("file", help="path to a festival.json")
    sp.add_argument("name")
    sp.add_argument("--limit", type=int, default=5)
    sp.set_defaults(func=cmd_resolve_artist)

    sp = sub.add_parser("schedule", help=cmd_schedule.__doc__)
    sp.add_argument("file")
    sp.add_argument("--day", help="ISO date, e.g. 2026-08-14")
    sp.add_argument("--stage-id")
    sp.set_defaults(func=cmd_schedule)

    sp = sub.add_parser("overlaps", help=cmd_overlaps.__doc__)
    sp.add_argument("file")
    sp.add_argument("--day", required=True)
    sp.add_argument("--start", required=True)
    sp.add_argument("--end", required=True)
    sp.add_argument("--exclude-id")
    sp.set_defaults(func=cmd_overlaps)

    sp = sub.add_parser("search-artist-everywhere", help=cmd_search_artist_everywhere.__doc__)
    sp.add_argument("name")
    sp.add_argument("--min-score", type=float, default=0.5)
    sp.set_defaults(func=cmd_search_artist_everywhere)

    sp = sub.add_parser("day-part", help=cmd_day_part.__doc__)
    sp.add_argument("time", help="HH:MM")
    sp.set_defaults(func=cmd_day_part)

    sp = sub.add_parser("links", help=cmd_links.__doc__)
    sp.add_argument("file")
    sp.add_argument("--artist-id", help="artist id, or 'global' for site-wide links only")
    sp.set_defaults(func=cmd_links)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
