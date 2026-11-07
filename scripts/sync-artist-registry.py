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
  --min-score=N    Similarity (0-1) at or above which a match is
                    auto-accepted (default 0.92). Below it, an artist is only
                    flagged "needs confirmation" when its name is a plausible
                    spelling variant of a registry name (see
                    is_plausible_variant()); otherwise it is treated as new.

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


def compact_name(name):
    """normalize_name() minus spacing, a leading "the" and "and"/"&" --
    so "Soulgrinder"/"Soul Grinder" or "The Spirit"/"Spirit" compare equal."""
    n = normalize_name(name)
    n = re.sub(r"^the ", "", n)
    n = re.sub(r" and ", " ", f" {n} ").strip()
    return n.replace(" ", "")


def edit_distance(a, b):
    """Optimal-string-alignment distance: Levenshtein plus adjacent swaps,
    so a typo like "Fuenral" vs "Funeral" counts as one edit, not two."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def is_plausible_variant(name_a, name_b):
    """True if two different names could realistically be the same act
    spelled differently -- the only cases worth a manual "confirm?".

    A fuzzy ratio alone (difflib) flags pairs that merely share letters
    (Firespawn/Firtan, Drowned/Dethroned, Akhlys/Kataklysm), which drowns
    real candidates in noise. Instead, only these count:
      - equal after dropping spacing, a leading "the" and "and"
        (Soul Grinder/Soulgrinder, The Spirit/Spirit);
      - a small typo: at most 1 edit, or 1 per 8 characters for longer
        names, on names of 4+ characters (Aeternus/Aeternvs);
      - one name is the other plus extra whole words (Drowned /
        Drowned in Sorrow, Firewolf / Firewolf - Acoustic Set).
    """
    a, b = compact_name(name_a), compact_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter = min(len(a), len(b))
    allowed = max(1, max(len(a), len(b)) // 8)
    if shorter >= 4 and edit_distance(a, b) <= allowed:
        return True
    ta, tb = normalize_name(name_a).split(), normalize_name(name_b).split()
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len("".join(small)) >= 4 and len(small) < len(big):
        for i in range(len(big) - len(small) + 1):
            if big[i:i + len(small)] == small:
                return True
    return False


def match_registry(artist_name, registry, min_score):
    """Returns (entry, score, kind): kind is "matched" (auto-link), "confirm"
    (plausible spelling variant, needs a human), or None (treat as new)."""
    query = normalize_name(artist_name)
    best = None
    best_score = 0.0
    for entry in registry:
        score = similarity(query, normalize_name(entry["name"]))
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= min_score:
        return best, best_score, "matched"
    variants = [e for e in registry if is_plausible_variant(artist_name, e["name"])]
    if variants:
        near = max(variants, key=lambda e: similarity(query, normalize_name(e["name"])))
        return near, similarity(query, normalize_name(near["name"])), "confirm"
    return None, best_score, None


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

        entry, score, kind = match_registry(artist["name"], registry, args.min_score)
        if kind == "matched":
            matched.append((artist, entry, score))
        elif kind == "confirm":
            needs_confirmation.append((artist, entry, score))
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
