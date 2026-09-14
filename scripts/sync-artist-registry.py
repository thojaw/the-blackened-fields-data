#!/usr/bin/env python3
"""
Matches a festival.json's artists against the repo-root artists.json global
registry, and (with --apply) merges registry data back into the festival and
adds any genuinely new artists to the registry.

No third-party dependencies (stdlib only), no network calls -- genre/country
enrichment for brand-new artists is still done by scripts/enrich-artists.mjs;
run that first if a new artist's festival entry has no genres/country yet.

Usage:
  python3 scripts/sync-artist-registry.py <festival.json> [--apply]

Options:
  --apply          Write changes. Default is a dry-run report only.
  --min-score=N    Similarity (0-1) below which a match is "needs
                    confirmation" instead of auto-accepted (default 0.92).

This script never reads or writes an artist's `id` field. It only ever
touches `globalId` (added when a confident match or a new registry entry is
found) and, for artists it matches, `description`/`genres`/`country` (copied
from the registry). See AGENTS.md 'Artist registry' for the id vs globalId
rule and the multi-show-per-artist case this preserves.

A registry entry's `links` are never populated or copied here -- festival.json
Artist entries have no `links` field of their own (a festival's links live in
its top-level `links[]` array, keyed by `artistId`), so there is nothing to
sync in either direction. Add/edit `links` on a registry entry directly, or
via `scripts/enrich-artists.mjs` run against `artists.json`.
"""
import argparse
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTISTS_JSON = os.path.join(REPO_ROOT, "artists.json")


# Letters that NFKD does not decompose into base+combining-mark (so a plain
# "strip combining marks" pass silently drops them instead of transliterating
# them) -- common in Icelandic/Nordic/German artist names in this dataset.
EXTRA_TRANSLIT = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "þ": "th", "Þ": "Th", "ð": "d", "Ð": "D", "ß": "ss",
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
})


def to_ascii(name):
    pre = name.translate(EXTRA_TRANSLIT)
    normalized = unicodedata.normalize("NFKD", pre)
    return normalized.encode("ascii", "ignore").decode("ascii")


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", to_ascii(name).lower()).strip("-")
    return slug or "artist"


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", " ", to_ascii(name).lower()).strip()


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def load_registry():
    if not os.path.exists(ARTISTS_JSON):
        return []
    with open(ARTISTS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(registry):
    with open(ARTISTS_JSON, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")


def unique_slug(base_slug, country, taken):
    if base_slug not in taken:
        return base_slug
    if country:
        candidate = f"{base_slug}-{country}"
        if candidate not in taken:
            return candidate
    n = 2
    while f"{base_slug}-{n}" in taken:
        n += 1
    return f"{base_slug}-{n}"


def match_registry(artist_name, registry, min_score):
    query = normalize_name(artist_name)
    best = None
    best_score = 0.0
    for entry in registry:
        score = similarity(query, normalize_name(entry["name"]))
        if score > best_score:
            best, best_score = entry, score
    if best is None:
        return None, 0.0
    if best_score >= 0.999:
        return best, best_score
    if best_score >= min_score:
        return best, best_score
    return None, best_score if best_score >= 0.6 else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("festival_file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-score", type=float, default=0.92)
    args = parser.parse_args()

    with open(args.festival_file, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)

    registry = load_registry()
    registry_by_id = {e["id"]: e for e in registry}
    taken_slugs = set(registry_by_id.keys())

    matched, needs_confirmation, new = [], [], []
    new_registry_entries = []

    for artist in data.get("artists", []):
        if artist.get("globalId") or artist["id"] in registry_by_id:
            continue  # already linked

        exact, score = match_registry(artist["name"], registry, args.min_score)
        if exact:
            matched.append((artist, exact, score))
        elif score >= 0.6:
            near, _ = match_registry(artist["name"], registry, 0.0)
            needs_confirmation.append((artist, near, score))
        else:
            slug = unique_slug(slugify(artist["name"]), artist.get("country"), taken_slugs)
            taken_slugs.add(slug)
            entry = {"id": slug, "name": artist["name"]}
            if artist.get("description"):
                entry["description"] = artist["description"]
            if artist.get("genres"):
                entry["genres"] = artist["genres"]
            if artist.get("country"):
                entry["country"] = artist["country"]
            new.append((artist, entry))
            new_registry_entries.append(entry)

    print(f"=== {args.festival_file} ===")
    print(f"{len(matched)} matched, {len(needs_confirmation)} need confirmation, {len(new)} new\n")

    for artist, entry, score in matched:
        print(f"  [matched]   {artist['name']} (id={artist['id']}) -> globalId={entry['id']} (score {score:.3f})")
    for artist, entry, score in needs_confirmation:
        suggestion = f" -- did you mean \"{entry['name']}\" ({entry['id']})?" if entry else ""
        print(f"  [confirm?]  {artist['name']} (id={artist['id']}), best score {score:.3f}{suggestion}")
    for artist, entry in new:
        print(f"  [new]       {artist['name']} (id={artist['id']}) -> globalId={entry['id']}")

    if not args.apply:
        print("\nDry run only -- pass --apply to write changes.")
        return

    for artist, entry, _score in matched:
        artist["globalId"] = entry["id"]
        for field in ("description", "genres", "country"):
            if entry.get(field) is not None:
                artist[field] = entry[field]

    for artist, entry in new:
        artist["globalId"] = entry["id"]

    registry.extend(new_registry_entries)
    if new_registry_entries:
        save_registry(registry)

    if matched or new:
        eol = "\r\n" if "\r\n" in raw else "\n"
        out = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", eol) + eol
        with open(args.festival_file, "w", encoding="utf-8") as f:
            f.write(out)

    print(f"\nApplied: {len(matched)} matched, {len(new)} new registry entries added.")
    if needs_confirmation:
        print(f"{len(needs_confirmation)} artist(s) still need manual confirmation -- not touched.")


if __name__ == "__main__":
    main()
