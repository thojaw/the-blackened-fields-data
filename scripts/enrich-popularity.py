#!/usr/bin/env python3
"""
Backfills Artist.popularity in the repo-root artists.json global registry
by looking each artist up on Last.fm and bucketing their global listener
count into a 1-10 scale calibrated against well-known metal acts (see
"Calibration" below), not the general-population popularity Last.fm's raw
numbers would otherwise suggest. See AGENTS.md "Popularity" section.

No third-party dependencies (stdlib only): urllib.request in place of fetch.

Usage:
  python3 scripts/enrich-popularity.py artists.json [options]

Options:
  --write            Actually write changes back to the file (default: dry run, prints a report)
  --force            Re-lookup and overwrite artists that already have a popularity value
  --preview=N        Only look up the first N artists that need it (handy for a quick test run)

Env:
  LASTFM_API_KEY     Required. Free key: https://www.last.fm/api/account/create

A Spotify-based source (Spotify's 0-100 `popularity` field) was tried and
abandoned: for developer apps created since Spotify's late-2024 API
lockdown, `popularity` (and `followers`, `genres`) are silently stripped
from Artist objects returned by `/search` and `/artists/{id}` unless the
app has "Extended Quota Mode" approval, which Spotify only grants to
large-scale commercial apps -- not available to a self-serve app like
this one's. Confirmed live: a raw search response for "Metallica" came
back with no `popularity` key at all. Last.fm remains the only viable
automated source.

Calibration:
  Last.fm's "listeners" count (lifetime unique listeners, not monthly --
  Last.fm doesn't expose a monthly figure -- but it's a stable, comparable
  proxy across artists) is mapped onto 1-10 via the hand-set breakpoint
  table below (POPULARITY_THRESHOLDS), not a single continuous formula.
  A single log curve was tried first and rejected: with a fixed step size
  per point, any two artists within roughly the same factor of each other
  always land on the same integer regardless of what tier boundary sits
  between them, while a huge, meaningful gap (e.g. a genuinely unknown
  local act vs. an established touring act) can compress into just 2-3
  points of separation. A table lets each boundary be placed deliberately
  -- more resolution where most of a metal festival's actual lineup sits
  (thousands to low-hundred-thousands of listeners), less resolution
  above ~1M where everyone left is already headliner-caliber and finer
  distinctions stop being meaningful -- and it's directly editable if a
  run's results don't match scene judgment (which is expected; see below).
  An artist Last.fm has no record of at all (0 listeners / not found) gets
  popularity 1 rather than being left unset -- per the brief, no
  streaming footprint at all is itself the strongest signal of "least
  popular", not an unknown to omit.
  This is a blunt, single-source proxy, not a rigorous metric -- see the
  "not_found"/low-listener output for artists worth a manual sanity check
  (a listeners count can lag a fast-rising act, or over-count a same-named
  artist in another genre).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "the-blackened-fields-data-enrichment/1.0 (+https://github.com/thojaw/the-blackened-fields-data)"
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
REQUEST_DELAY_MS = 250

# [minListeners, score], checked highest-first; the first threshold a
# listener count meets or exceeds wins. See "Calibration" above for why
# this is a table rather than a formula. Tune freely -- if a run's output
# doesn't match scene judgment for a batch of artists, that's a sign these
# boundaries need adjusting, not that the artists are wrong.
POPULARITY_THRESHOLDS = [
    (3_000_000, 10),  # Metallica/Slayer/Iron Maiden-tier global headliners
    (1_200_000, 9),
    (500_000, 8),  # established festival headliners (e.g. Testament, Helloween-scale)
    (180_000, 7),
    (60_000, 6),
    (20_000, 5),
    (6_000, 4),
    (1_500, 3),
    (300, 2),
    (0, 1),  # no meaningful footprint / not found
]


def popularity_from_listeners(listeners):
    n = listeners or 0
    for min_listeners, score in POPULARITY_THRESHOLDS:
        if n >= min_listeners:
            return score
    return 1


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def lastfm_artist_info(name, api_key):
    params = urllib.parse.urlencode({
        "method": "artist.getinfo",
        "artist": name,
        "api_key": api_key,
        "autocorrect": "1",
        "format": "json",
    })
    req = urllib.request.Request(f"{LASTFM_URL}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as res:
        data = json.load(res)
    if data.get("error"):
        return {"found": False}

    listeners = int(((data.get("artist") or {}).get("stats") or {}).get("listeners") or 0)
    mb_name = (data.get("artist") or {}).get("name")
    return {"found": True, "listeners": listeners, "mbName": mb_name}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="artists.json path(s)")
    parser.add_argument("--write", action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--force", action="store_true", help="Re-lookup and overwrite artists that already have a popularity value")
    parser.add_argument("--preview", type=int, default=None)
    args = parser.parse_args()

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        print("LASTFM_API_KEY env var is required. Free key: https://www.last.fm/api/account/create", file=sys.stderr)
        sys.exit(1)

    for file in args.files:
        print(f"\n=== {file} ===")
        with open(file, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        if not isinstance(data, list):
            print(f"{file} is not a bare array -- this script only enriches the artists.json registry.", file=sys.stderr)
            continue

        to_process = [a for a in data if args.force or not is_number(a.get("popularity"))]
        print(f"{len(to_process)}/{len(data)} artist(s) need lookup.")

        if args.preview is not None:
            to_process = to_process[: args.preview]
            print(f"--preview={args.preview}: only looking up {len(to_process)} artist(s).")

        changed = 0
        for artist in to_process:
            try:
                result = lastfm_artist_info(artist["name"], api_key)
            except Exception as err:
                print(f"  [error]     {artist['name']}: {err}")
                time.sleep(REQUEST_DELAY_MS / 1000)
                continue

            if not result["found"]:
                print(f"  [not found] {artist['name']} -> popularity=1 (no Last.fm record)")
                if args.write:
                    artist["popularity"] = 1
                    changed += 1
            else:
                score = popularity_from_listeners(result["listeners"])
                print(
                    f"  [matched]   {artist['name']} -> \"{result['mbName']}\" "
                    f"listeners={result['listeners']} popularity={score}"
                )
                if args.write:
                    artist["popularity"] = score
                    changed += 1

            time.sleep(REQUEST_DELAY_MS / 1000)

        if args.write and changed > 0:
            eol = "\r\n" if "\r\n" in raw else "\n"
            out = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", eol) + eol
            with open(file, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Wrote {changed} update(s) to {file}.")
        elif args.write:
            print("No changes to write.")
        else:
            print("Dry run only -- pass --write to apply results.")


if __name__ == "__main__":
    main()
