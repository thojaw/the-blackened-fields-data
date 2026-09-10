#!/usr/bin/env python3
"""
Fails if any festival.json changed vs. a base ref without also bumping its
top-level "version" field.

Rationale: the app only computes/surfaces delta information (what changed
since a user last opened a festival) when "version" changes. Any edit to a
festival.json -- however small -- should therefore increment "version" at
least once per merged change, so client apps that cached the old version
detect the update. This is deliberately "any change counts", not a
schema-aware check of which fields are "meaningful": that's much simpler to
reason about and enforce than trying to special-case cosmetic edits.

No third-party dependencies (stdlib only), same conventions as
scripts/generate-index.py.

Usage:
  python3 scripts/check-version-bump.py [--base REF]

Options:
  --base REF   Git ref to diff against (default: origin/main). The check
               compares each changed festival.json against its content at
               the merge-base of REF and HEAD.

Exit status is non-zero if any changed festival.json did not bump version.
"""
import argparse
import json
import subprocess
import sys


def run(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def merge_base(base_ref):
    return run("merge-base", base_ref, "HEAD").strip()


def changed_festival_files(base_sha):
    out = run("diff", "--name-only", "--diff-filter=ACMR", base_sha, "HEAD")
    return [line for line in out.splitlines() if line.endswith("festival.json")]


def show(sha, path):
    """Return file content at sha, or None if the file doesn't exist there."""
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="Base ref to diff against (default: origin/main)")
    args = parser.parse_args()

    base_sha = merge_base(args.base)
    failures = []

    for path in changed_festival_files(base_sha):
        old_text = show(base_sha, path)
        if old_text is None:
            continue  # newly added festival.json -- no prior version to compare

        try:
            new_text = open(path, "r", encoding="utf-8").read()
        except FileNotFoundError:
            continue  # deleted festival.json

        if old_text == new_text:
            continue  # no textual change at all

        old_version = json.loads(old_text).get("version")
        new_version = json.loads(new_text).get("version")

        if not isinstance(new_version, int) or not isinstance(old_version, int) or new_version <= old_version:
            failures.append((path, old_version, new_version))

    if failures:
        print("The following festival.json files changed but did not bump \"version\":\n")
        for path, old_version, new_version in failures:
            print(f"  {path}: version {old_version!r} -> {new_version!r} (must strictly increase)")
        print("\nBump \"version\" (integer, +1 is simplest) in each file above so client apps detect the update.")
        return 1

    print("OK: every changed festival.json bumped its version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
