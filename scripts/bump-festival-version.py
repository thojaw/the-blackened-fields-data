#!/usr/bin/env python3
"""
Auto-increments the top-level "version" field of any festival.json that
changed vs. a base ref but didn't already bump it.

Rationale: the app only computes/surfaces delta information (what changed
since a user last opened a festival) when "version" changes. Any edit to a
festival.json -- however small -- should therefore increment "version" at
least once per merged change, so client apps that cached the old version
detect the update. Relying on whoever/whatever edits the file (human or an
agent) to remember this manually turned out not to be reliable in practice,
so CI does it automatically instead of just failing the check.

The bump is a surgical text substitution of the "version" line (the field
appears exactly once, at the top level, in every festival.json) rather than
a JSON round-trip, so it doesn't reformat/reorder the rest of the file.

No third-party dependencies (stdlib only), same conventions as
scripts/generate-index.py.

Usage:
  python3 scripts/bump-festival-version.py [--base REF]

Options:
  --base REF   Git ref to diff against (default: origin/main). Each changed
               festival.json is compared against its content at the
               merge-base of REF and HEAD.

Prints the path of every file it bumped (one per line) and exits 0. Exits
non-zero only on unexpected errors (e.g. malformed JSON).
"""
import argparse
import json
import re
import subprocess
import sys

VERSION_LINE_RE = re.compile(r'^(\s*"version"\s*:\s*)(\d+)(\s*,?\s*)$', re.MULTILINE)


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


def bump_version_text(text, new_version):
    return VERSION_LINE_RE.sub(rf"\g<1>{new_version}\g<3>", text, count=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="Base ref to diff against (default: origin/main)")
    args = parser.parse_args()

    base_sha = merge_base(args.base)
    bumped = []

    for path in changed_festival_files(base_sha):
        old_text = show(base_sha, path)
        if old_text is None:
            continue  # newly added festival.json -- no prior version to compare

        try:
            with open(path, "r", encoding="utf-8") as f:
                new_text = f.read()
        except FileNotFoundError:
            continue  # deleted festival.json

        if old_text == new_text:
            continue  # no textual change at all

        old_version = json.loads(old_text).get("version")
        new_version = json.loads(new_text).get("version")

        if not isinstance(old_version, int):
            continue  # nothing sane to bump from; leave for a human to sort out

        if isinstance(new_version, int) and new_version > old_version:
            continue  # already bumped (e.g. by hand, or a previous run of this script)

        bumped_text = bump_version_text(new_text, old_version + 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(bumped_text)
        bumped.append(path)

    for path in bumped:
        print(path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
