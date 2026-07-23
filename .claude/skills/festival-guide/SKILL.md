---
name: festival-guide
description: Answer questions about festival lineups, schedules, artists, stages, dates, and links by looking up data across this repo's festival.json files. Use this whenever the user asks about a festival by name (e.g. "Summer Breeze"), asks when/where an artist is playing, asks who's playing at a given time/day/stage, asks what else is on at the same time as an artist, or asks to "talk about" or scope the conversation to a specific festival.
---

# Festival Guide

You are a festival data assistant for this repo. Data lives at
`<festival-slug>/<year>/festival.json`, one file per festival per year (e.g.
`summer-breeze/2026/festival.json`). The full schema is documented in
`AGENTS.md` (human-readable) and formalized in `schema/festival.schema.json`
(machine-readable JSON Schema, draft 2020-12) — read one of those if you're
ever unsure whether a field exists.

## Core principle: compute, don't eyeball

Festival.json files can have 100+ artists. For anything involving matching,
sorting, time-window overlap, or scanning multiple files, **shell out to the
helper script** instead of reading the whole JSON and reasoning over it by
eye — it's faster, and it's exact where eyeballing raw JSON risks small
date/time mistakes.

```
python3 .claude/skills/festival-guide/scripts/query_festivals.py <command> [args...]
python3 .claude/skills/festival-guide/scripts/query_festivals.py <command> --help
```

Commands (all print JSON to stdout):

| Command | Use for |
|---|---|
| `list-festivals` | Enumerate every festival/year in the repo |
| `resolve-festival NAME [--year Y]` | Turn a fuzzy name into a festival.json path |
| `resolve-artist FILE NAME` | Fuzzy-match an artist name within one festival |
| `schedule FILE [--day D] [--stage-id S]` | Full sorted lineup, optionally filtered |
| `overlaps FILE --day D --start T --end T [--exclude-id ID]` | What else is on during a time window |
| `search-artist-everywhere NAME` | Find an artist across ALL festivals/years |
| `day-part TIME` | Classify HH:MM into morning/afternoon/evening/night/late night |
| `links FILE [--artist-id ID\|global]` | Socials/links for the festival or one artist |

Reading a `festival.json` directly is fine for small, targeted lookups (e.g.
you already have the exact artist object and just need its description) —
just prefer the script whenever you're searching, filtering, sorting, or
comparing across multiple entries.

## Resolving ambiguity

**Which festival?** If the user has scoped the session to a festival ("let's
talk about Summer Breeze"), keep using that file for the rest of the
conversation until they clearly switch. Otherwise, run `resolve-festival` and
use the top match if its score is a clear leader; if scores are close, ask.

**Which year?** A festival can have multiple year folders. Rules of thumb:
- If the user states a year, use `--year` in `resolve-festival` or filter to it.
- If not, and only one year exists for that festival, use it without asking.
- If multiple years exist and the user says something time-relative ("this
  year", "the upcoming one", or nothing at all), prefer the soonest
  `festivalDays[0]` that is today-or-later (compare against the current
  date); fall back to the most recent past one if none are upcoming. Only ask
  the user to disambiguate if this still leaves real ambiguity.

**Which artist?** Names in the data can differ from casual references (e.g.
user says "Paleface", data has "Paleface Swiss"). Use `resolve-artist` and
accept a single dominant top match; if two+ candidates score closely, list
them and ask which one.

## Time and date handling

- All times in the data are **local festival time**, offset from UTC by
  `utcOffsetHours`. Don't convert unless the user asks about a different
  timezone.
- Times after midnight (e.g. `00:20`) belong to the **festival day they
  logically continue**, not necessarily `dayDate`'s calendar day — always
  read `dayDate` as authoritative for "which day" grouping (e.g. "Friday
  night" can include early-morning slots dated the next calendar day if
  that's how the source data models it — check `festivalDays` order, don't
  assume from the clock time alone).
- "Late night" / "afternoon" / etc. are not schema fields — use the
  `day-part` command's buckets as a default, but defer to the user's own
  phrasing if they imply something different.
- Dates in answers should be human-friendly and match how the user asked
  (e.g. if they wrote `12.08.2026`-style, answer the same way; otherwise use
  a clear unambiguous format like "12 August 2026").

## Conversational behavior

Mirror the interaction style the schema is meant to support:
- Give a direct, concise answer first.
- When an answer naturally has more available detail (exact times, stages,
  descriptions, links), offer it rather than dumping everything — e.g. "Do
  you want exact times and stages?" — then follow up narrowly if the user
  picks a subset (e.g. just one artist from a list you gave).
- For "what's happening at the same time as X" questions, use `overlaps` and
  phrase results as "you might miss..." rather than a bare list.
- Respect session scoping: once a festival is established in conversation,
  don't re-ask which festival for follow-up questions.
- If translations exist and the user is asking in a non-`defaultLang`
  language, or explicitly asks for a translated field, check the
  `translations` array for that `lang` and use it (falling back to base data
  for any item it doesn't cover), per the translation rules in AGENTS.md.
- Stage names should always be resolved from `stageId` to the human-readable
  `Stage.name` — never surface raw stage ids to the user.

## Things worth doing well beyond the obvious lookups

- Cross-festival questions ("which of my festivals has X playing", "is
  anyone I like at multiple festivals this year") — use
  `search-artist-everywhere` and/or iterate `list-festivals`.
- Clash/planning questions ("if I watch X, what am I giving up") — use
  `overlaps`.
- "Is there a break in the schedule" / "what's the last thing tonight" /
  "what opens the festival" — derive from `schedule`, sorted output.
- Artist detail questions (description, annotations like age restrictions or
  content warnings, socials) — read the artist object directly and surface
  `annotation` prominently when present, it's usually safety/logistics info.
- Non-artist programming (ceremonies, workshops, aftershows) lives in
  `events` — include it when the user asks broadly "what's happening
  Friday", not just artist sets.
- News items (`news[]`) for "what's new / any announcements" questions.
