#!/usr/bin/env python3
"""
Resolves Artist.imageUrl / Artist.imageFocus in festival.json from a
filename convention on locally-hosted image files, instead of hand-editing
the JSON every time an image is cropped differently.

Convention (see AGENTS.md 'Optional: media files'):
  <id>.<ext>     -- default, top-anchored crop (imageFocus absent)
  <id>-c.<ext>   -- center-anchored crop (imageFocus: "center")
  <id>-b.<ext>   -- bottom-anchored crop (imageFocus: "bottom")

For every artist whose imageUrl is a local relative filename (not an
external http(s) URL), this looks in the same folder as festival.json for
a file matching that convention and, if found, sets imageUrl/imageFocus to
match -- so renaming e.g. a12.jpg -> a12-c.jpg on disk is all that's
needed; nothing to change in festival.json by hand.

No third-party dependencies (stdlib only), same conventions as
scripts/generate-index.py.

Usage:
  python3 scripts/resolve-image-focus.py [festival.json ...] [--write]

With no paths given, scans every */*/festival.json in the repo.

Options:
  --write   Actually write changes back (default: dry run, prints a report)

Exits non-zero if any artist's local imageUrl doesn't resolve to a file on
disk and no convention variant matches either (a dangling reference -- this
404s in the app), or if multiple convention variants exist for the same id
(ambiguous -- delete the stale one), regardless of --write.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")
FOCUS_SUFFIXES = {"c": "center", "b": "bottom"}
EXTERNAL_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def find_festival_files():
    pattern = os.path.join(REPO_ROOT, "*", "*", "festival.json")
    return sorted(glob.glob(pattern))


def find_variants(folder, artist_id):
    """Return {suffix_or_None: filename} for every convention-matching file
    present on disk for this artist id (usually zero or one match)."""
    variants = {}
    for ext in IMAGE_EXTS:
        for suffix in (None, "c", "b"):
            name = f"{artist_id}-{suffix}.{ext}" if suffix else f"{artist_id}.{ext}"
            if os.path.isfile(os.path.join(folder, name)):
                variants[suffix] = name
    return variants


def resolve_festival(path, write):
    folder = os.path.dirname(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)

    changed = False
    problems = 0

    for artist in data.get("artists", []):
        url = artist.get("imageUrl")
        if not url or EXTERNAL_URL_RE.match(url):
            continue

        variants = find_variants(folder, artist["id"])

        if len(variants) > 1:
            names = sorted(variants.values())
            print(f"  [ambiguous] {artist['id']}: multiple candidate files {names} -- delete the stale one")
            problems += 1
            continue

        if not variants:
            if not os.path.isfile(os.path.join(folder, url)):
                print(f"  [missing]   {artist['id']}: imageUrl {url!r} has no file on disk")
                problems += 1
            continue

        [(suffix, filename)] = variants.items()
        wants_url = filename
        wants_focus = FOCUS_SUFFIXES.get(suffix)  # None means the key should be absent

        if artist.get("imageUrl") != wants_url or artist.get("imageFocus") != wants_focus:
            print(
                f"  [update]    {artist['id']}: imageUrl {artist.get('imageUrl')!r} -> {wants_url!r}, "
                f"imageFocus {artist.get('imageFocus')!r} -> {wants_focus!r}"
            )
            if write:
                artist["imageUrl"] = wants_url
                if wants_focus:
                    artist["imageFocus"] = wants_focus
                else:
                    artist.pop("imageFocus", None)
                changed = True

    if write and changed:
        eol = "\r\n" if "\r\n" in raw else "\n"
        out = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", eol) + eol
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"  Wrote changes to {os.path.relpath(path, REPO_ROOT)}")

    return changed, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="festival.json path(s); default: every festival in the repo")
    parser.add_argument("--write", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()

    files = [os.path.abspath(f) for f in args.files] if args.files else find_festival_files()

    total_changed = 0
    total_problems = 0
    for path in files:
        print(f"=== {os.path.relpath(path, REPO_ROOT)} ===")
        changed, problems = resolve_festival(path, args.write)
        total_changed += 1 if changed else 0
        total_problems += problems

    if not args.write:
        print("\nDry run only -- pass --write to apply.")

    if total_problems:
        print(f"\n{total_problems} problem(s) found.", file=sys.stderr)

    return 1 if total_problems else 0


if __name__ == "__main__":
    sys.exit(main())
