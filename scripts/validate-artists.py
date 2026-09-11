#!/usr/bin/env python3
"""
Validates the repo-root artists.json global artist registry.

Stdlib-only Python (no jsonschema dependency), matching schema/artists.schema.json
structurally: required fields, id pattern, country pattern, genres shape, and
id uniqueness.

Usage:
  python3 scripts/validate-artists.py [--check-festivals]

Options:
  --check-festivals   Also scan every festival.json for Artist.globalId
                       values and report any that don't resolve to an
                       artists.json id.

Exits non-zero if any error is found.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTISTS_JSON = os.path.join(REPO_ROOT, "artists.json")

ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COUNTRY_PATTERN = re.compile(r"^[a-z]{2}$")
ALLOWED_FIELDS = {"id", "name", "description", "genres", "country"}


def validate_registry():
    errors = []
    if not os.path.exists(ARTISTS_JSON):
        errors.append(f"{ARTISTS_JSON} does not exist")
        return errors, []

    with open(ARTISTS_JSON, "r", encoding="utf-8") as f:
        try:
            registry = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"artists.json is not valid JSON: {e}")
            return errors, []

    if not isinstance(registry, list):
        errors.append("artists.json must be a JSON array at the root")
        return errors, []

    seen_ids = set()
    for i, entry in enumerate(registry):
        where = f"artists.json[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: entry is not an object")
            continue

        extra = set(entry.keys()) - ALLOWED_FIELDS
        if extra:
            errors.append(f"{where}: unknown field(s) {sorted(extra)}")

        for required in ("id", "name"):
            if required not in entry:
                errors.append(f"{where}: missing required field '{required}'")

        entry_id = entry.get("id")
        if isinstance(entry_id, str):
            if not ID_PATTERN.match(entry_id):
                errors.append(f"{where}: id '{entry_id}' does not match {ID_PATTERN.pattern}")
            if entry_id in seen_ids:
                errors.append(f"{where}: duplicate id '{entry_id}'")
            seen_ids.add(entry_id)
        elif entry_id is not None:
            errors.append(f"{where}: id must be a string")

        country = entry.get("country")
        if country is not None and not (isinstance(country, str) and COUNTRY_PATTERN.match(country)):
            errors.append(f"{where}: country '{country}' does not match {COUNTRY_PATTERN.pattern}")

        genres = entry.get("genres")
        if genres is not None:
            if not isinstance(genres, list) or not all(isinstance(g, str) for g in genres):
                errors.append(f"{where}: genres must be an array of strings")

        description = entry.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{where}: description must be a string")

    return errors, registry


def check_festivals(registry_ids):
    errors = []
    pattern = os.path.join(REPO_ROOT, "*", "*", "festival.json")
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rel = os.path.relpath(path, REPO_ROOT)
        for artist in data.get("artists", []) or []:
            global_id = artist.get("globalId")
            if global_id and global_id not in registry_ids:
                errors.append(
                    f"{rel}: artist '{artist.get('name')}' (id={artist.get('id')}) "
                    f"has globalId '{global_id}' not found in artists.json"
                )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-festivals", action="store_true")
    args = parser.parse_args()

    errors, registry = validate_registry()

    if args.check_festivals and not errors:
        registry_ids = {e["id"] for e in registry if isinstance(e, dict) and "id" in e}
        errors.extend(check_festivals(registry_ids))

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"\n{len(errors)} error(s) found.", file=sys.stderr)
        sys.exit(1)

    print(f"artists.json OK ({len(registry)} artist(s)).")


if __name__ == "__main__":
    main()
