# the-blackened-fields-data

This repo has two parts:

1. **Raw festival data** — the actual lineup/schedule information.
2. **A Claude Skill** (`festival-guide`) that knows how to read and query it.

## 1. The data

Each festival/year lives in its own folder:

```
<festival-slug>/<year>/
  festival.json     # the full dataset for that year
  a1.jpg, a2.png...  # optional artist images, referenced by imageUrl
```

Example: `summer-breeze/2026/festival.json`.

`festival.json` holds the festival's identity (name, dates, UTC offset),
its stages, artists (with their set times), non-artist programming
(`events`: ceremonies, workshops, aftershows...), news, external links
(website/socials, either festival-wide or per-artist), and optional
per-language translations.

The exact shape is documented two ways:

- **`AGENTS.md`** — human-readable schema description with a full example,
  meant for whoever (human or agent) is creating or editing a `festival.json`.
- **`schema/festival.schema.json`** — the same schema formalized as a
  standard [JSON Schema](https://json-schema.org/) (draft 2020-12). Point
  any JSON Schema validator at a `festival.json` file with this to check it's
  well-formed — this part has nothing Claude-specific about it.

## 2. The `festival-guide` Skill

`.claude/skills/festival-guide/` packages up how to *answer questions* about
this data — lineup lookups, schedules, clashes, artist info — rather than
just how to write it.

It has two pieces:
- `SKILL.md` — instructions: how to resolve an ambiguous festival/year/artist
  name, how to handle festival-local time and midnight-crossing sets
  correctly, how to phrase answers (offer more detail rather than dumping
  everything, don't re-ask which festival once a conversation is scoped to
  one, etc).
- `scripts/query_festivals.py` — a small, dependency-free Python script that
  does the actual lookups precisely (fuzzy name matching, sorting, date/time
  math, cross-file scanning) instead of relying on an LLM to eyeball
  potentially 100+ artist entries of raw JSON.

### A few things it can do

- **Direct lookups**: "When is Summer Breeze starting?", "Where and when is
  [artist] playing?", resolving loose/partial names (e.g. "Paleface" →
  "Paleface Swiss") and picking the right year automatically if a festival
  has multiple.
- **Time-window questions**: "Who's playing Friday late night?", correctly
  handling sets that start after midnight (dated the *next* calendar day in
  the data but conceptually still "that night").
- **Clash / overlap detection**: "What else is on at the same time as
  [artist]?" / "If I watch X, what would I miss?" — computed from actual
  start/end times, not guessed.
- **Cross-festival search**: "Which festivals is [artist] playing?" across
  every `festival.json` in the repo, not just one.
- **Session scoping**: "Let's talk about Summer Breeze" sets context for the
  rest of the conversation — no need to repeat the festival name on every
  follow-up question.
- **Artist detail & links**: descriptions, safety/logistics annotations, and
  socials (Facebook, Spotify, Instagram, etc.), either festival-wide or for
  one artist.
- **Translations**: answers in a non-default language pull from the
  `translations` block where available, falling back to the base language
  otherwise.

## Integration — can I use this in the Claude app?

**Short answer: yes, with a caveat about where the data lives.**

- **Claude Code** (CLI, web, or an environment like this one) — works out of
  the box. Skills under `.claude/skills/` are auto-discovered whenever
  Claude Code is pointed at this repo, and the script reads the
  `festival.json` files directly off disk. Nothing to configure.
- **claude.ai / Claude Desktop (Skills feature)** — Agent Skills can be
  uploaded into a Project there too. Upload the `festival-guide` folder as a
  Skill, and also add the relevant `festival.json` file(s) as Project
  knowledge/files so Claude's code execution environment has something to
  query — that environment doesn't have this git repo checked out, so the
  data has to be supplied alongside the skill.
- **Claude Agent SDK / API** — Skills (and the JSON Schema, and the plain
  Python script) can be loaded the same way as with Claude Code, wired up in
  your own agent via the SDK's skills/tools support.
- **Other agentic tools** — nothing here is Claude-specific by design:
  `SKILL.md` is plain Markdown, `query_festivals.py` is dependency-free
  standard-library Python, and `festival.schema.json` is standard JSON
  Schema. Any tool that can read a Markdown file, shell out to Python, and
  validate against JSON Schema can use this, even without native "Skill"
  support.
