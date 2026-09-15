#!/usr/bin/env python3
"""
Mechanical assembly of a festival.json (or additions to one) from a small
JSON "spec" file: downloads every artist image + the festival logo locally
(this repo never references external image URLs -- see AGENTS.md), writes
the festival.json, then chains the existing Python pipeline
(sync-artist-registry.py --apply, validate-artists.py --check-festivals,
generate-index.py) so the whole thing lands in one already-consistent
commit instead of a dozen manual steps.

This script does NOT write descriptions, pick images, verify facts, or
resolve genuine artist-identity collisions -- that's still a research/
verification job for whoever (human or agent) builds the spec file. See
.claude/skills/festival-intake/SKILL.md for the end-to-end procedure this
script is one step of.

Everything here is stdlib-only (urllib.request for downloads, subprocess
for the pipeline) except converting a downloaded logo to PNG, which needs
Pillow (`pip install Pillow`) -- the Python standard library has no
image codecs of its own. This mirrors the original script's own on-demand
dependency (it shelled out to `npx --yes sharp-cli` for the same step).

Usage:
  python3 scripts/scaffold-festival.py create <spec.json>
  python3 scripts/scaffold-festival.py add-artists <festival.json> <spec.json>

create spec.json shape:
  {
    "id": "dark-easter-metal-meeting-2027",   // required, "<slug>-<year>"
    "name": "Dark Easter Metal Meeting",       // required
    "year": 2027,                              // required
    "folder": "dark-easter-metal-meeting",     // optional, default: id minus "-<year>"
    "defaultLang": "en",                       // optional, default "en"
    "visible": false,                          // optional, default true
    "runningOrderExists": false,               // required
    "utcOffsetHours": 1,                       // required
    "festivalDays": ["2027-03-27", "2027-03-28"], // required
    "stages": [{ "id": "s1", "name": "Backstage Werk" }],  // optional
    "news": [],                                // optional, default []
    "links": [{ "id": "l1", "label": "Website", "url": "https://..." }], // optional, default []
    "logoUrl": "https://.../logo-source.jpg",  // optional; always downloaded + converted to logo.png
    "artists": [ ...ArtistSpec ],              // required, see below
    "translations": [{ "lang": "de", "artists": [...], "links": [...] }] // optional, passed through
  }

add-artists spec.json shape:
  {
    "artists": [ ...ArtistSpec ],
    "translations": [{ "lang": "de", "artists": [...] }],  // optional, merged by lang
    "runningOrderExists": true                              // optional override
  }

ArtistSpec:
  {
    "id": "emperor", "name": "Emperor",
    "description": "...", "genres": ["Black Metal"], "country": "no",
    "annotation": null, "dayDate": null, "startTime": null, "endTime": null,
    "stageId": null, "replacedArtistId": null,
    "imageUrl": "https://..."   // required source; downloaded locally, field is
                                 // overwritten with the local filename ("aN.jpg")
  }

Never put a remote URL in the final festival.json's imageUrl -- every
artist image and the logo are always downloaded and stored locally next
to festival.json, matching every other festival in this repo.

Known limitation: giving an ArtistSpec a local `id` that already equals
an existing artists.json slug is treated as a confirmed identity claim,
not a lookup -- sync-artist-registry.py resolves it immediately with no
name-similarity check (see AGENTS.md's id-vs-globalId resolution rule;
this is deliberate upstream behaviour, not something this script can or
should second-guess). Only reuse an existing slug as a local id after
you (or the calling skill) have already verified it's genuinely the same
real-world act -- never guess a slug to "link up" an artist.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def convert_image_to_png(src_path, dest_path):
    try:
        from PIL import Image
    except ImportError as err:
        raise RuntimeError(
            "Converting the festival logo to PNG needs Pillow -- install it with `pip install Pillow` and re-run."
        ) from err
    with Image.open(src_path) as img:
        img.convert("RGBA").save(dest_path, "PNG")


def download_to(url, dest_no_ext, convert_to_png=False):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "the-blackened-fields-data-scaffold/1.0 (+https://github.com/thojaw/the-blackened-fields-data)"},
    )
    with urllib.request.urlopen(req) as res:
        content_type = (res.headers.get("Content-Type") or "").split(";")[0].strip()
        data = res.read()

    ext = EXT_BY_CONTENT_TYPE.get(content_type)
    if not ext:
        from_url = os.path.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".").lower()
        ext = from_url or "jpg"

    if convert_to_png and ext != "png":
        src_path = f"{dest_no_ext}.src.{ext}"
        with open(src_path, "wb") as f:
            f.write(data)
        convert_image_to_png(src_path, f"{dest_no_ext}.png")
        os.remove(src_path)
        return f"{os.path.basename(dest_no_ext)}.png"
    if convert_to_png and ext == "png":
        with open(f"{dest_no_ext}.png", "wb") as f:
            f.write(data)
        return f"{os.path.basename(dest_no_ext)}.png"

    with open(f"{dest_no_ext}.{ext}", "wb") as f:
        f.write(data)
    return f"{os.path.basename(dest_no_ext)}.{ext}"


def next_artist_index(folder):
    if not os.path.isdir(folder):
        return 1
    nums = []
    for name in os.listdir(folder):
        m = re.match(r"^a(\d+)\.\w+$", name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def download_artist_images(artists, folder):
    n = next_artist_index(folder)
    for artist in artists:
        image_url = artist.get("imageUrl")
        if not image_url or not re.match(r"^https?://", image_url):
            raise ValueError(f'Artist "{artist.get("name")}" ({artist.get("id")}) needs a remote imageUrl to download -- got: {image_url}')
        filename = download_to(image_url, os.path.join(folder, f"a{n}"))
        print(f"  downloaded image for {artist['name']} -> {filename}")
        artist["imageUrl"] = filename
        n += 1


def artist_from_spec(a):
    # Only ever writes fields the schema defines -- drop anything extra a
    # spec author left lying around (e.g. helper fields used during research).
    out = {
        "id": a["id"],
        "name": a["name"],
        "imageUrl": a.get("imageUrl"),
        "description": a.get("description"),
        "dayDate": a.get("dayDate"),
        "startTime": a.get("startTime"),
        "endTime": a.get("endTime"),
        "annotation": a.get("annotation"),
    }
    if a.get("stageId"):
        out["stageId"] = a["stageId"]
    if a.get("genres"):
        out["genres"] = a["genres"]
    if a.get("country"):
        out["country"] = a["country"]
    if a.get("replacedArtistId"):
        out["replacedArtistId"] = a["replacedArtistId"]
    if a.get("globalId"):
        out["globalId"] = a["globalId"]
    return out


def merge_translations(existing, incoming):
    by_lang = {t["lang"]: t for t in (existing or [])}
    for inc in incoming or []:
        t = by_lang.get(inc["lang"])
        if t is None:
            t = {"lang": inc["lang"]}
            by_lang[inc["lang"]] = t
        for key in ("artists", "news", "links", "events"):
            if inc.get(key):
                t[key] = (t.get(key) or []) + inc[key]
    merged = list(by_lang.values())
    return merged if merged else None


def write_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def run(args):
    print(f"  $ {' '.join(args)}")
    result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print("\n".join(f"  {line}" for line in output.strip().splitlines()))
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}")
    return result.stdout


def slugify(name):
    normalized = unicodedata.normalize("NFD", name)
    stripped = re.sub(r"[̀-ͯ]", "", normalized)
    slug = re.sub(r"[^a-z0-9]+", "-", stripped.lower())
    return slug.strip("-")


# Registers any artist that sync-artist-registry.py left in its "needs
# confirmation" bucket as a brand-new registry entry instead, mirroring
# exactly what --apply does for a genuinely-new artist. This repo's own
# genre-scoped naming makes real collisions rare (see AGENTS.md), and in
# practice the "confirm" bucket is almost always a same-name-different-
# band false positive from the fuzzy matcher, not a real duplicate -- but
# as a real safety check, it still refuses to touch an id that's already
# taken by a *different* artist name rather than silently overwriting it.
# `festival_artists` here must be the CURRENT festival.json entries (read
# after sync-artist-registry.py --apply already ran), not the original spec
# objects -- the python step writes globalId to the file, not back into our
# in-memory spec, and for an existing/multi-show festival the local `id`
# can legitimately differ from the resolved global identity.
def auto_register_unconfirmed(festival_artists):
    registry_path = os.path.join(REPO_ROOT, "artists.json")
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    by_id = {a["id"]: a for a in registry}

    added = []
    skipped = []
    resolved = {}  # local artist id -> final registry/global id
    for artist in festival_artists:
        # Resolution rule (AGENTS.md): globalId if present, else id itself if
        # it already looks like a registry slug, else no identity yet.
        global_id = artist.get("globalId") or artist["id"]
        if global_id in by_id:
            resolved[artist["id"]] = global_id
            continue  # already registered (matched, or id already is the slug)

        existing = next((a for a in registry if a["id"] == global_id), None)
        if existing and existing["name"] != artist["name"]:
            skipped.append({"id": global_id, "festivalArtist": artist["name"], "registryEntry": existing["name"]})
            continue  # leave unresolved -- don't enrich against someone else's entry

        # A brand-new entry needs a real slug id (AGENTS.md), not a bare
        # festival-local id like "a1" -- that only happens when no globalId was
        # given and the local id isn't already a registry-shaped slug.
        if not artist.get("globalId") and not existing:
            candidate = slugify(artist["name"])
            suffix = 2
            while candidate in by_id and by_id[candidate]["name"] != artist["name"]:
                candidate = f"{slugify(artist['name'])}-{suffix}"
                suffix += 1
            global_id = candidate
        resolved[artist["id"]] = global_id

        entry = {"id": global_id, "name": artist["name"], "description": artist.get("description")}
        if artist.get("genres"):
            entry["genres"] = artist["genres"]
        if artist.get("country"):
            entry["country"] = artist["country"]
        registry.append(entry)
        by_id[global_id] = entry
        added.append(global_id)

    if added:
        write_json(registry_path, registry)
    return added, skipped, resolved


# Runs enrich-artists.py (registry mode) against ONLY the ids we just
# touched, then merges just the `links` field back -- never genres/country,
# which this repo's hand-verified festival-context data should win over
# MusicBrainz's tag soup. Guards against MusicBrainz resolving the *wrong*
# same-named entity (this happened for real during development: MusicBrainz's
# top "Bianca" match was an unrelated German act) by comparing country
# before/after and discarding the whole enrichment for that artist -- not
# just the country field -- if it moved.
def enrich_links_safely(global_ids):
    registry_path = os.path.join(REPO_ROOT, "artists.json")
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    targets = [a for a in registry if a["id"] in global_ids]
    if not targets:
        return [], []

    before = {a["id"]: a.get("country") for a in targets}
    tmp_path = os.path.join(REPO_ROOT, ".scaffold-enrich-tmp.json")
    write_json(tmp_path, targets)

    try:
        run([sys.executable, "scripts/enrich-artists.py", tmp_path, "--write"])
    except Exception as err:  # noqa: BLE001 -- enrichment is best-effort here
        print(f"  enrich-artists.py failed, skipping link enrichment: {err}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return [], []

    with open(tmp_path, "r", encoding="utf-8") as f:
        enriched = json.load(f)
    os.remove(tmp_path)

    linked = []
    mismatched = []
    for e in enriched:
        before_country = before.get(e["id"])
        if before_country and e.get("country") and e["country"] != before_country:
            mismatched.append({"id": e["id"], "expected": before_country, "got": e["country"]})
            continue  # discard this artist's enrichment entirely -- likely wrong MusicBrainz entity
        if e.get("links"):
            target = next(a for a in registry if a["id"] == e["id"])
            target["links"] = e["links"]
            linked.append(e["id"])
    write_json(registry_path, registry)
    return linked, mismatched


def run_pipeline(festival_rel_path, touched_ids):
    py = sys.executable
    print("Syncing artist registry...")
    run([py, "scripts/sync-artist-registry.py", festival_rel_path, "--apply"])

    festival_path = os.path.join(REPO_ROOT, festival_rel_path)
    with open(festival_path, "r", encoding="utf-8") as f:
        festival = json.load(f)
    touched_festival_artists = [a for a in festival["artists"] if a["id"] in touched_ids]

    added, skipped, resolved = auto_register_unconfirmed(touched_festival_artists)
    if added:
        print(f"  auto-registered (was 'needs confirmation'): {', '.join(added)}")
    if skipped:
        print("  SKIPPED -- id collision with a DIFFERENT existing artist, needs manual review:")
        for s in skipped:
            print(f"    {s['id']}: festival has \"{s['festivalArtist']}\", registry already has \"{s['registryEntry']}\"")

    # Backfill globalId on the file for anything we just auto-registered
    # (already-matched artists were handled by sync-artist-registry.py itself).
    with open(festival_path, "r", encoding="utf-8") as f:
        festival = json.load(f)
    for a in festival["artists"]:
        if not a.get("globalId") and a["id"] in resolved and resolved[a["id"]] in added:
            a["globalId"] = resolved[a["id"]]
    write_json(festival_path, festival)

    global_ids = list(resolved.values())
    print("Enriching links (Spotify/Bandcamp/etc.)...")
    linked, mismatched = enrich_links_safely(global_ids)
    if linked:
        print(f"  linked: {', '.join(linked)}")
    if mismatched:
        print("  MISMATCH -- MusicBrainz likely resolved a different same-named entity, left unlinked:")
        for m in mismatched:
            print(f"    {m['id']}: expected country \"{m['expected']}\", MusicBrainz said \"{m['got']}\"")

    print("Validating...")
    run([py, "scripts/validate-artists.py", "--check-festivals"])

    print("Regenerating index.json...")
    run([py, "scripts/generate-index.py"])

    return skipped, mismatched


def cmd_create(spec_path):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    for req in ["id", "name", "year", "runningOrderExists", "utcOffsetHours", "festivalDays", "artists"]:
        if spec.get(req) is None:
            raise ValueError(f"spec is missing required field: {req}")

    folder_slug = spec.get("folder") or re.sub(rf"-{spec['year']}$", "", spec["id"])
    folder = os.path.join(REPO_ROOT, folder_slug, str(spec["year"]))
    os.makedirs(folder, exist_ok=True)

    print(f"Downloading {len(spec['artists'])} artist image(s)...")
    download_artist_images(spec["artists"], folder)

    if spec.get("logoUrl"):
        print("Downloading + converting logo...")
        download_to(spec["logoUrl"], os.path.join(folder, "logo"), convert_to_png=True)

    festival = {
        "id": spec["id"],
        "name": spec["name"],
        "version": 1,
        "year": spec["year"],
        "defaultLang": spec.get("defaultLang") or "en",
    }
    if spec.get("visible") is False:
        festival["visible"] = False
    festival["runningOrderExists"] = spec["runningOrderExists"]
    festival["utcOffsetHours"] = spec["utcOffsetHours"]
    festival["festivalDays"] = spec["festivalDays"]
    if spec.get("stages"):
        festival["stages"] = spec["stages"]
    festival["news"] = spec.get("news") or []
    festival["links"] = spec.get("links") or []
    festival["artists"] = [artist_from_spec(a) for a in spec["artists"]]
    if spec.get("translations"):
        festival["translations"] = spec["translations"]

    festival_rel_path = os.path.relpath(os.path.join(folder, "festival.json"), REPO_ROOT).replace(os.sep, "/")
    write_json(os.path.join(REPO_ROOT, festival_rel_path), festival)
    print(f"Wrote {festival_rel_path}")

    touched_ids = [a["id"] for a in spec["artists"]]
    skipped, mismatched = run_pipeline(festival_rel_path, touched_ids)

    print("\nDone.")
    print(json.dumps(
        {"festivalRelPath": festival_rel_path, "artists": touched_ids, "needsManualReview": {"registryIdCollisions": skipped, "linkMismatches": mismatched}},
        indent=2,
    ))


def cmd_add_artists(festival_arg_path, spec_path):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    if not spec.get("artists"):
        raise ValueError("spec.artists must be a non-empty array")

    festival_path = os.path.normpath(os.path.join(REPO_ROOT, festival_arg_path))
    folder = os.path.dirname(festival_path)
    with open(festival_path, "r", encoding="utf-8") as f:
        festival = json.load(f)

    existing_ids = {a["id"] for a in festival["artists"]}
    for a in spec["artists"]:
        if a["id"] in existing_ids:
            raise ValueError(f'Artist id "{a["id"]}" already exists in {festival_arg_path} -- pick a new local id')

    print(f"Downloading {len(spec['artists'])} artist image(s)...")
    download_artist_images(spec["artists"], folder)

    festival["artists"].extend(artist_from_spec(a) for a in spec["artists"])
    if spec.get("runningOrderExists") is not None:
        festival["runningOrderExists"] = spec["runningOrderExists"]
    festival["version"] = festival.get("version", 1) + 1
    merged = merge_translations(festival.get("translations"), spec.get("translations"))
    if merged:
        festival["translations"] = merged

    festival_rel_path = os.path.relpath(festival_path, REPO_ROOT).replace(os.sep, "/")
    write_json(festival_path, festival)
    print(f"Updated {festival_rel_path}")

    touched_ids = [a["id"] for a in spec["artists"]]
    skipped, mismatched = run_pipeline(festival_rel_path, touched_ids)

    print("\nDone.")
    print(json.dumps(
        {"festivalRelPath": festival_rel_path, "newArtists": touched_ids, "needsManualReview": {"registryIdCollisions": skipped, "linkMismatches": mismatched}},
        indent=2,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    create_p = subparsers.add_parser("create")
    create_p.add_argument("spec_path")

    add_p = subparsers.add_parser("add-artists")
    add_p.add_argument("festival_path")
    add_p.add_argument("spec_path")

    args = parser.parse_args()
    if args.mode == "create":
        cmd_create(args.spec_path)
    else:
        cmd_add_artists(args.festival_path, args.spec_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 -- mirror a top-level failure exit code
        print(err, file=sys.stderr)
        sys.exit(1)
