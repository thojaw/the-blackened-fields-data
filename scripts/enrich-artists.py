#!/usr/bin/env python3
"""
Backfills Artist.genres / Artist.country in a festival.json, or
genres/country/links in the repo-root artists.json global registry, by
looking artists up against MusicBrainz (primary) and Last.fm (genre
fallback). Which mode runs is auto-detected from the file's shape: a
festival.json (an object with an `artists` array) vs. artists.json (a
bare array of registry entries).

No third-party dependencies (stdlib only, urllib.request for the HTTP
calls), same conventions as scripts/sync-artist-registry.py.

Usage:
  python3 scripts/enrich-artists.py <path/to/festival.json|artists.json> [options]

Options:
  --write            Actually write changes back to the file (default: dry run, prints a report)
  --force            Re-lookup and overwrite artists that already have genres+country(+links)
  --min-score=N      MusicBrainz search score (0-100) required to auto-accept a match (default 90)
  --max-genres=N     Max number of genre tags to keep per artist (default 3)
  --max-links=N      Max number of links to keep per artist, registry mode only (default 6)
  --preview=N        Only look up the first N artists that need it (handy for a quick test run)

Env:
  LASTFM_API_KEY     Optional. If set, used as a genre fallback when MusicBrainz has no tags.
                      Free key: https://www.last.fm/api/account/create

Notes:
  - MusicBrainz requires a descriptive User-Agent and a max of ~1 req/sec unauthenticated.
  - Ambiguous/low-confidence matches are never auto-applied; they're printed for manual review.
  - Links are only ever written in registry mode: festival.json's Artist has no `links`
    field of its own (a festival's links live in its top-level `links[]`, keyed by
    artistId) -- see AGENTS.md 'Artist registry'.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "the-blackened-fields-data-enrichment/1.0 (+https://github.com/thojaw/the-blackened-fields-data)"
MB_SEARCH_URL = "https://musicbrainz.org/ws/2/artist/"
MB_AREA_URL = "https://musicbrainz.org/ws/2/area/"
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
REQUEST_DELAY = 1.1
MAX_AREA_HOPS = 4
RETRYABLE_STATUSES = {429, 502, 503, 504}
MAX_RETRIES = 4

# Same type enum as festival.json's ExternalLink / artists.schema.json's
# RegistryLink. Classified by URL host rather than MusicBrainz's own
# relationship-type names, which don't map cleanly onto it (e.g. Spotify,
# Deezer, and Apple Music are all just "streaming music").
DOMAIN_LINK_TYPES = [
    (r"(^|\.)facebook\.com$", "facebook"),
    (r"(^|\.)(twitter|x)\.com$", "x"),
    (r"(^|\.)youtube\.com$", "youtube"),
    (r"(^|\.)instagram\.com$", "instagram"),
    (r"(^|\.)open\.spotify\.com$", "spotify"),
    (r"(^|\.)deezer\.com$", "deezer"),
    (r"\.bandcamp\.com$", "bandcamp"),
    (r"(^|\.)music\.apple\.com$", "applemusic"),
    (r"(^|\.)soundcloud\.com$", "soundcloud"),
    (r"(^|\.)tiktok\.com$", "tiktok"),
    (r"(^|\.)patreon\.com$", "patreon"),
    (r"(^|\.)discord\.(gg|com)$", "discord"),
]


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="festival.json / artists.json path(s)")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--min-score", type=float, default=90)
    parser.add_argument("--max-genres", type=int, default=3)
    parser.add_argument("--max-links", type=int, default=6)
    parser.add_argument("--preview", type=int, default=None)
    return parser.parse_args(argv)


# Serializes every MusicBrainz request (search + area walks alike) to
# respect the ~1 req/sec unauthenticated rate limit -- calls happen one
# artist at a time in this script, so a plain sleep-after-each-call is
# enough (no concurrent callers to queue behind).
def mb_fetch_json(url, label):
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
            time.sleep(REQUEST_DELAY)
            return data
        except urllib.error.HTTPError as err:
            if err.code not in RETRYABLE_STATUSES or attempt >= MAX_RETRIES:
                raise RuntimeError(f'MusicBrainz {err.code} for "{label}"') from err
            time.sleep(REQUEST_DELAY * (2**attempt))


def musicbrainz_lookup(name):
    params = {"query": f'artist:"{name}"', "fmt": "json", "limit": "5", "inc": "genres+tags"}
    url = f"{MB_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = mb_fetch_json(url, name)
    return data.get("artists") or []


def musicbrainz_url_relations(mbid):
    params = {"fmt": "json", "inc": "url-rels"}
    url = f"{MB_SEARCH_URL}{mbid}?{urllib.parse.urlencode(params)}"
    data = mb_fetch_json(url, f"relations:{mbid}")
    return data.get("relations") or []


def classify_link_url(url_str):
    try:
        host = urllib.parse.urlparse(url_str).hostname or ""
    except ValueError:
        return None
    host = re.sub(r"^www\.", "", host)
    for pattern, link_type in DOMAIN_LINK_TYPES:
        if re.search(pattern, host):
            return link_type
    return None


# Only keeps relations that resolve to one of our known link types, plus
# MusicBrainz's own "official homepage" relation (mapped to "web") -- other
# relation types (wikipedia, discogs, allmusic, songkick, lyrics sites, ...)
# aren't part of the RegistryLink type enum and are dropped rather than
# guessed at.
def pick_links(relations, max_links):
    seen = set()
    links = []
    for rel in relations:
        resource = (rel.get("url") or {}).get("resource")
        if not resource or resource in seen:
            continue

        domain_type = classify_link_url(resource)
        if domain_type:
            entry = {"url": resource, "type": domain_type}
        elif rel.get("type") == "official homepage":
            entry = {"url": resource, "type": "web", "label": "Website"}
        else:
            continue

        seen.add(resource)
        links.append(entry)
        if len(links) >= max_links:
            break
    return links


# MusicBrainz only sets Artist.country when `area` IS a Country entity.
# When the area is more specific (city/county/state, e.g. Jersey City ->
# Hudson County -> New Jersey), we have to walk the "part of" hierarchy
# ourselves to find an enclosing area with an ISO code.
def resolve_country_from_area(area_id, depth=0):
    if not area_id or depth > MAX_AREA_HOPS:
        return None

    params = {"fmt": "json", "inc": "area-rels"}
    url = f"{MB_AREA_URL}{area_id}?{urllib.parse.urlencode(params)}"
    area = mb_fetch_json(url, f"area:{area_id}")

    if area.get("iso-3166-1-codes"):
        return area["iso-3166-1-codes"][0].lower()
    if area.get("iso-3166-2-codes"):
        return area["iso-3166-2-codes"][0].split("-")[0].lower()

    parent_rel = next(
        (
            r
            for r in area.get("relations") or []
            if r.get("type") == "part of" and r.get("target-type") == "area" and r.get("direction") == "backward"
        ),
        None,
    )
    if not parent_rel:
        return None

    return resolve_country_from_area(parent_rel["area"]["id"], depth + 1)


def lastfm_top_tags(name, api_key):
    params = {
        "method": "artist.getTopTags",
        "artist": name,
        "api_key": api_key,
        "autocorrect": "1",
        "format": "json",
    }
    url = f"{LASTFM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return []
    tags = ((data.get("toptags") or {}).get("tag")) or []
    return [to_title_case(t["name"]) for t in tags if t.get("name")]


# MusicBrainz/Last.fm tags are lowercase free text ("post-metal"); the
# festival.json schema wants title case ("Post-Metal") with no lookup table.
def to_title_case(text):
    return re.sub(r"[^\s-]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:], text)


def pick_genres(mb_artist, max_genres):
    tags = mb_artist.get("genres") or mb_artist.get("tags") or []
    tags = sorted(tags, key=lambda t: t.get("count") or 0, reverse=True)
    return [to_title_case(t["name"]) for t in tags[:max_genres]]


def enrich_artist(artist, min_score, max_genres, max_links, lastfm_key, with_links):
    candidates = musicbrainz_lookup(artist["name"])
    if not candidates:
        return {"status": "not_found"}

    best = candidates[0]
    score = float(best.get("score") or 0)
    if score < min_score:
        return {
            "status": "ambiguous",
            "candidates": [{"name": c.get("name"), "score": c.get("score"), "country": c.get("country")} for c in candidates[:3]],
        }

    country = best["country"].lower() if best.get("country") else None
    if not country:
        area_id = (best.get("area") or {}).get("id") or (best.get("begin-area") or {}).get("id")
        country = resolve_country_from_area(area_id)

    genres = pick_genres(best, max_genres)

    if not genres and lastfm_key:
        time.sleep(REQUEST_DELAY)
        genres = lastfm_top_tags(artist["name"], lastfm_key)[:max_genres]

    links = None
    if with_links:
        relations = musicbrainz_url_relations(best["id"])
        links = pick_links(relations, max_links)

    return {
        "status": "matched",
        "mb_name": best.get("name"),
        "score": score,
        "country": country,
        "genres": genres,
        "links": links,
    }


def main():
    args = parse_args(sys.argv[1:])
    lastfm_key = os.environ.get("LASTFM_API_KEY")

    for file in args.files:
        print(f"\n=== {file} ===")
        with open(file, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)

        # artists.json (the global registry) is a bare array; festival.json is
        # an object with an `artists` array. Only the registry has a `links`
        # field to backfill -- see AGENTS.md 'Artist registry'.
        is_registry = isinstance(data, list)
        artists = data if is_registry else data["artists"]

        to_process = [
            a
            for a in artists
            if args.force
            or not a.get("country")
            or not a.get("genres")
            or (is_registry and not a.get("links"))
        ]

        print(f"{len(to_process)}/{len(artists)} artist(s) need lookup.")

        if args.preview is not None:
            to_process = to_process[: args.preview]
            print(f"--preview={args.preview}: only looking up {len(to_process)} artist(s).")

        changed = 0
        for artist in to_process:
            try:
                result = enrich_artist(
                    artist,
                    min_score=args.min_score,
                    max_genres=args.max_genres,
                    max_links=args.max_links,
                    lastfm_key=lastfm_key,
                    with_links=is_registry,
                )
            except Exception as err:  # noqa: BLE001 -- one bad artist shouldn't stop the batch
                print(f"  [error]     {artist['name']}: {err}")
                continue

            if result["status"] == "not_found":
                print(f"  [not found] {artist['name']}")
            elif result["status"] == "ambiguous":
                candidates_str = "; ".join(
                    f"{c['name']} (score {c['score']}, {c['country'] or '?'})" for c in result["candidates"]
                )
                print(f"  [ambiguous] {artist['name']} -- candidates: {candidates_str}")
            else:
                country_str = result["country"] or "-"
                genres_str = ", ".join(result["genres"]) if result["genres"] else "-"
                links_str = f" links=[{', '.join(l['type'] for l in result['links'] or [])}]" if is_registry else ""
                print(
                    f"  [matched]   {artist['name']} -> \"{result['mb_name']}\" (score {result['score']}) "
                    f"country={country_str} genres=[{genres_str}]{links_str}"
                )

                if args.write:
                    if result["country"]:
                        artist["country"] = result["country"]
                    if result["genres"]:
                        artist["genres"] = result["genres"]
                    if is_registry and result["links"]:
                        artist["links"] = result["links"]
                    changed += 1

        if args.write and changed > 0:
            eol = "\r\n" if "\r\n" in raw else "\n"
            out = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", eol) + eol
            with open(file, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Wrote {changed} update(s) to {file}.")
        elif args.write:
            print("No changes to write.")
        else:
            print("Dry run only -- pass --write to apply matched results.")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 -- mirror a top-level failure exit code
        print(err, file=sys.stderr)
        sys.exit(1)
