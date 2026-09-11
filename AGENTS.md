In this repository, the only relevant files are festival schema files and images/media files. When asked to create or edit festival data, populate `festival.json` to match the schema below exactly — do not invent fields or top-level keys that aren't defined here.

## Machine-readable schema and querying

- `schema/festival.schema.json` is a formal JSON Schema (draft 2020-12) of the
  `FestivalData` shape described below — use it to validate a `festival.json`
  file, or as an unambiguous reference instead of the prose/example below.
- For *answering questions* about festival data (lineup lookups, schedules,
  time-window overlaps, cross-festival search, etc.), see
  `.claude/skills/festival-guide/SKILL.md` and its companion script
  `.claude/skills/festival-guide/scripts/query_festivals.py` (stdlib-only
  Python, runnable by any agent, not just Claude).
- `index.json` (repo root) is a generated summary of every `festival.json`
  in the repo — see "Multi-festival index" below. It is **not** hand-edited.
- `artists.json` (repo root) is a global, cross-festival artist registry —
  see "Artist registry" below. Unlike `index.json` it **is** meant to be
  edited directly (or via `scripts/sync-artist-registry.py`) as artists are
  added.

## Structure

`festival name/year`

> Example: `summer-breeze/2026`

## Files

### Required: `festival.json`
The full festival dataset for that year, matching the schema below.

### Optional: media files
Images referenced by `imageUrl` may live alongside `festival.json` in the same `festival name/year` folder (referenced by relative filename) or point to an externally hosted URL.

## Schema and further information

### Artist / Event data shape (conceptual)

```
Artist {
  id, name, imageUrl, description,
  dayDate?, startTime?, endTime?, annotation?,
  stageId?  -- references Stage.id; absent = implicit single stage
  genres?   -- string[], free-text genre labels, e.g. ["Heavy Metal", "Beatdown"]; not translated
  country?  -- ISO 3166-1 alpha-2 code, lowercase, e.g. "us", "de"; resolved to a display name client-side
  replacedArtistId?  -- Artist.id of a cancelled artist whose slot this artist has taken over
  globalId?  -- artists.json id giving this show a cross-festival identity; see "Artist registry" below
}

Event {
  id, title, dayDate (ISO date), startTime, endTime,
  stageId?  -- references Stage.id
  -- non-artist programming: ceremonies, workshops, tastings, aftershows
}

ExternalLink {
  id, label?, url,
  type?     -- absent = text link; "web" | "facebook" | "x" | "youtube" | "instagram"
            --   | "spotify" | "deezer" | "bandcamp" | "applemusic" | "soundcloud"
            --   | "tiktok" | "patreon" | "discord"
            -- when present: icon-only rendering (brand icon, or 🔗 for "web")
            -- when absent: text link rendering; label is required in this case
  artistId? -- absent = global link (Home screen); present = shown on that artist's detail page
}
```

**Link rendering rules:**
- `type` absent → text link; `label` is required and displayed as tappable text
- `type` present → icon-only; `label` is optional (used as accessibility label / tooltip only)
- Both global links (no `artistId`) and artist links (with `artistId`) follow the same rendering rule
- Home screen: text links in a card list, then a separate icon-only row for all typed global links
- Artist Detail: text links in a card list, then icon-only row for all typed artist links

**Cancellations and replacements:**
- When a booked artist cancels, keep their entry in `artists[]` rather than
  deleting it. Clear their schedule by setting `dayDate`, `startTime`, and
  `endTime` to `null`, and use `annotation` to say so in plain text (e.g.
  `"Cancelled."`) — this repo has no separate boolean cancellation flag, and
  nulled schedule fields alone are ambiguous with an artist that simply
  isn't scheduled yet (e.g. a "Surprise Show" placeholder), so the
  `annotation` text is what actually communicates the cancellation to users.
- Never reuse a cancelled artist's `id` for the act that replaces them in
  that slot — always give the replacement a new `id`. Ids anchor
  client-side per-artist state (e.g. favorites/"likes"); reusing an id
  would silently hand the replacement any state a user had attached to the
  cancelled act.
- If a new artist has taken over a cancelled artist's slot, set
  `replacedArtistId` on the *replacement* artist to the cancelled artist's
  `id`. This gives consuming apps a structured, language-independent way to
  detect and render the relationship (e.g. show "replaces X", grey out the
  cancelled artist) instead of relying on `annotation` text alone.
- `replacedArtistId` must reference another `Artist.id` present in the same
  `artists[]` array. This is not enforced by the JSON Schema, which cannot
  express cross-field id references — the same caveat already applies to
  `stageId`/`artistId` references elsewhere in this document.

  ```json
  {
    "id": "a16",
    "name": "Imperium Dekadenz",
    "dayDate": null, "startTime": null, "endTime": null,
    "annotation": "Cancelled."
  },
  {
    "id": "a21",
    "name": "Irem",
    "dayDate": "2026-09-05", "startTime": "17:45", "endTime": "18:35",
    "annotation": "Short-notice replacement for the cancelled Imperium Dekadenz.",
    "replacedArtistId": "a16"
  }
  ```

```
ArtistTranslation   { id, description }
NewsTranslation     { id, title, body }
LinkTranslation     { id, label?, url? }   -- at least one of label/url must be present
EventTranslation    { id, title }

Translation {
  lang (BCP 47, e.g. "de"),
  artists?: ArtistTranslation[],
  news?: NewsTranslation[],
  links?: LinkTranslation[],
  events?: EventTranslation[]
}

Stage {
  id     -- e.g. "s1", "s2"
  name   -- display string, e.g. "Main Stage", "T-Stage"
}

FestivalData {
  id,     -- globally unique slug across all festivals/years, e.g. "summer-breeze-2026"
          --   used to namespace client-side data (e.g. favorites) per festival
  name,   -- display name, e.g. "Summer Breeze"
  version, year, defaultLang, runningOrderExists, utcOffsetHours,
  visible?,        -- boolean, defaults to true when absent; false hides this
                    --   festival from index.json / pickers without deleting it
  festivalDays[],  -- ISO dates covered by the festival
  artists[], news[], links[],
  events?[],      -- non-artist programming
  stages?[],      -- absent or length <= 1 = single-stage (isMultiStage = false)
  translations?[]
}
```

**Translation rules:**
- Base data is always written in the language indicated by `defaultLang` (currently `"en"`).
- A `translations` entry for a language does not need to cover every item — any untranslated item falls back to the base data value.
- Artist `name` and `imageUrl` are never translated (proper nouns; language-neutral).
- Artist `genres` and `country` are never translated (genre labels are language-neutral tags; `country` is a code resolved to a display name client-side).
- Link `url` may be overridden to point to a language-specific page; `label` may be overridden independently.
- Link `type` and `artistId` are never translated.

---

Example data (illustrative — trimmed to a few entries per array; a real `festival.json` has one entry per actual artist/news item/link/etc.):

```json
{
  "id": "berserkr-fest-2026",
  "name": "Berserkr Fest",
  "version": 2,
  "year": 2026,
  "defaultLang": "en",
  "runningOrderExists": true,
  "utcOffsetHours": 2,
  "festivalDays": ["2026-07-10", "2026-07-11", "2026-07-12"],
  "stages": [
    { "id": "s1", "name": "Main Stage" },
    { "id": "s2", "name": "Alterna Stage" }
  ],
  "news": [
    {
      "id": "n1",
      "title": "Tickets on sale",
      "body": "Three-day passes and single-day tickets are available now.",
      "date": "2026-02-15"
    }
  ],
  "links": [
    { "id": "l1", "label": "Website", "url": "https://example.org/" },
    { "id": "l2", "label": "Tickets", "url": "https://example.org/tickets" },
    {
      "id": "l3", "label": "Instagram",
      "url": "https://instagram.com/example", "type": "instagram"
    },
    {
      "id": "la1", "label": "Spotify",
      "url": "https://open.spotify.com/artist/example",
      "type": "spotify", "artistId": "a1"
    }
  ],
  "artists": [
    {
      "id": "a1",
      "name": "Berserkr",
      "imageUrl": "a1.png",
      "description": "Thunderous Norwegian folk-metal quartet drawing on saga poetry and battle-march drum patterns.",
      "stageId": "s2",
      "dayDate": "2026-07-12",
      "startTime": "17:00",
      "endTime": "18:00",
      "annotation": null,
      "genres": ["Folk Metal"],
      "country": "no"
    },
    {
      "id": "a2",
      "name": "Frost Giants",
      "imageUrl": "a2.png",
      "description": "Six-piece pagan-folk ensemble. Nyckelharpa, frame drums, throat-singing and a stage built around a forge anvil.",
      "stageId": "s1",
      "dayDate": "2026-07-10",
      "startTime": "21:00",
      "endTime": "23:00",
      "annotation": "Ear protection strongly advised for front-row positions.",
      "genres": ["Pagan Folk", "World Music"],
      "country": "se"
    }
  ],
  "events": [
    {
      "id": "e1",
      "title": "Opening Ceremony",
      "stageId": "s1",
      "dayDate": "2026-07-10",
      "startTime": "14:00",
      "endTime": "14:20"
    }
  ],
  "translations": [
    {
      "lang": "de",
      "artists": [
        {
          "id": "a2",
          "description": "Sechsköpfiges Pagan-Folk-Ensemble. Nyckelharpa, Rahmentrommeln, Obertongesang und eine Bühne rund um einen Schmiedeamboss.",
          "annotation": "Gehörschutz für Frontrow-Positionen dringend empfohlen."
        }
      ],
      "news": [
        {
          "id": "n1",
          "title": "Tickets im Verkauf",
          "body": "Drei-Tages-Pässe und Einzeltageskarten sind jetzt erhältlich."
        }
      ],
      "links": [
        { "id": "l3", "label": "Instagram" }
      ],
      "events": [
        { "id": "e1", "title": "Eröffnungszeremonie" }
      ]
    }
  ]
}
```

---

## Artist registry (`artists.json`)

`artists.json` at the repo root is a flat, de-duplicated registry of artists
across every festival, keyed by a permanent slug id — separate from, and
never overwriting, each festival's own local `Artist.id` values.

- Formal shape: `schema/artists.schema.json` (JSON Schema, draft 2020-12).
- One entry per unique artist:
  ```json
  {
    "id": "drekka-sjor",
    "name": "Drekka Sjór",
    "description": "Icelandic post-rock with rune-based song titles and an obsession for nine-minute crescendos.",
    "genres": ["Post-Rock"],
    "country": "is"
  }
  ```
  `id` is a permanent kebab-case slug derived from `name` (diacritics
  stripped, lowercased, e.g. `"Drekka Sjór"` → `"drekka-sjor"`) — it never
  changes once assigned. `description`/`genres`/`country` follow the exact
  same conventions as their `festival.json` `Artist` counterparts.
  `imageUrl` is deliberately not part of this registry — images stay
  festival-local since per-event photos can differ.
- **Slug collisions** (rare — this dataset stays within genre boundaries
  where duplicate act names are practically nonexistent): if a computed slug
  already belongs to a different artist, disambiguate by appending a short
  suffix — prefer the country code (`"novelists"` vs `"novelists-fr"`),
  falling back to `-2`, `-3`, ... otherwise.

### `id` vs `globalId`

`festival.json`'s `Artist` gained one new optional field, `globalId`, that
links a festival-local artist entry to its `artists.json` registry entry:

- `id` keeps meaning exactly what it always has: local to that
  `festival.json`, anchors client-side per-artist state (favorites), and is
  **never** reused or changed once published.
- `globalId` (optional) is the cross-festival identity. When present, it
  must match an `artists.json` id.
- **Resolution rule:** an artist's global identity is `globalId` if present,
  otherwise `id` itself if `id` already looks like a registry slug;
  otherwise it has no established global identity yet.
- For a **brand-new** festival, if an artist plays exactly one show, you can
  just use the registry slug directly as its `id` and skip `globalId`
  entirely — one field, no duplication.
- For an **existing, already-published** festival, or **any artist with more
  than one show in the same festival**, keep the local `aN`-style id(s) and
  set `globalId` on each to link them — this is required, not optional, in
  those two cases, since changing a live `id` would break locally- and
  Firebase-stored user state.

**Multiple shows, one artist:** an act can appear as more than one
`artists[]` entry in the same festival — a regular set, an acoustic set, a
surprise extra show — each with its own `id`, schedule, description, and
image, but the same `globalId`:

```json
{ "id": "a13", "name": "Firewolf", "globalId": "firewolf", ... },
{ "id": "a47", "name": "Firewolf - Acoustic Set", "globalId": "firewolf", ... },
{ "id": "a94", "name": "Firewolf - Extra Show", "globalId": "firewolf", ... }
```

Cross-festival tooling should treat entries sharing a `globalId` as the same
underlying artist rather than three unrelated hits.

### Workflow: adding artists to a festival

1. For each new artist, look it up in `artists.json` by normalized name
   (case/diacritic-insensitive). `scripts/sync-artist-registry.py
   <festival.json>` automates this — run it dry (no `--apply`) first to see
   matched / needs-confirmation / new buckets.
2. **High-confidence match** → reuse the registry entry: copy its
   `description`/`genres`/`country` into the festival artist object and set
   `globalId` to the registry id (`--apply` does this).
3. **Fuzzy/ambiguous match** → don't guess; ask for confirmation before
   linking (or add as new if you can confirm by other means, as this
   dataset's genre-scoped act names make real collisions very unlikely).
4. **No match** → create the artist first: look up genres/country (e.g. via
   `scripts/enrich-artists.mjs` against the festival file, or manually),
   write a short `description`, then let `sync-artist-registry.py --apply`
   slugify the name and append a new `artists.json` entry, setting
   `globalId` on the festival artist accordingly.
5. `scripts/validate-artists.py --check-festivals` checks `artists.json` for
   structural errors (duplicate/malformed ids) and that every `globalId`
   referenced from any `festival.json` actually resolves to a registry
   entry.

## Multi-festival index (`index.json`)

`index.json` at the repo root is a **generated** summary of every
`festival.json` in the repo, one entry per festival/year. It duplicates
each festival's identity/header fields (name, date range, language, etc.)
and adds cheap aggregate counts (artist count, stage count, ...), so a
multi-festival picker/UI can list and sort festivals without loading every
full `festival.json`.

- Formal shape: `schema/festival-index.schema.json` (JSON Schema, draft
  2020-12).
- Every festival gets an entry in `index.json` regardless of `visible` —
  the flag is carried through as-is rather than filtered out, so a
  consumer can show hidden/test festivals behind a developer or tester
  mode. Normal-mode UIs should filter out entries with `visible: false`
  client-side.
- Regenerated by `scripts/generate-index.py` (stdlib-only Python, rebuilds
  all entries from scratch every run — there are too few festivals for
  incremental updates to be worth the complexity):
  ```
  python3 scripts/generate-index.py
  ```
- **Do not hand-edit `index.json`.** A GitHub Actions workflow
  (`.github/workflows/sync-festival-data.yml`) regenerates and commits it
  automatically whenever a pull request against `main` touches any
  `festival.json`. If you edit a `festival.json` locally, re-run the script
  yourself to keep `index.json` in sync (CI will also catch it on the PR).

## Version field

- `version` (integer) must strictly increase whenever a `festival.json`
  changes, no matter how small the change (typo fix, image swap, whatever)
  — the client app only computes/surfaces delta information (what changed
  since a user last opened a festival) when `version` differs from its
  locally cached value, so a change that doesn't bump `version` is
  invisible to it. This is deliberately "any change bumps it" rather than
  a judgment call about which fields are meaningful: the latter needs
  schema-aware diffing to get right, and shipping a false negative (silently
  hiding a real update) is worse than the app doing one cheap, unnecessary
  delta computation.
- Automated by `scripts/bump-festival-version.py` (stdlib-only Python), run
  by the same `.github/workflows/sync-festival-data.yml` CI workflow
  described above (both the version bump and the `index.json` regen happen
  as steps of one job, one commit, one push — they used to be two separate
  workflows racing to push to the same PR branch, which caused rejected
  pushes; see git history if curious): it compares each changed file
  against its content on `main` and, if the text changed but `version`
  wasn't already bumped, increments `version` by 1. Newly added
  `festival.json` files are exempt (no prior version to compare against).
  Multiple changed files in one PR are each handled independently. This is
  automatic specifically because relying on whoever/whatever edits the file
  to remember the bump manually proved unreliable in practice — you don't
  need to bump `version` yourself; CI does it for you. You can still run it
  locally if useful:
  ```
  python3 scripts/bump-festival-version.py --base origin/main
  ```
- Exception: CI can't push to PRs from forks (no write access), so those
  need `version` bumped by hand before merging.

### `FestivalIndexEntry` shape (conceptual)

```
FestivalIndexEntry {
  id, slug, year, name, path,        -- identity + path to the source festival.json
  defaultLang, utcOffsetHours, runningOrderExists, version,
  visible,          -- carried over from the source festival.json (defaults to
                     --   true there); normal-mode UIs should filter out false,
                     --   a developer/tester mode may choose to show them
  festivalDays[],   -- full copy of the source festivalDays; first/last = date range
  isMultiStage,     -- true if stages.length > 1
  translationLangs[],  -- BCP 47 langs with a translations[] entry, e.g. ["de"]
  topGenres,        -- up to 10 most common artist genres, { genre: artistCount },
                     -- ordered by count descending then genre name
  counts: { artists, stages, news, events, links, globalLinks }
}

FestivalIndex {
  schemaVersion,  -- of this index shape, currently 1
  generatedAt,    -- UTC timestamp of the generation run
  festivals[]     -- sorted by soonest festivalDays[0], then name
}
```

### Example `index.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-08-16T20:39:32Z",
  "festivals": [
    {
      "id": "summer-breeze-2026",
      "slug": "summer-breeze",
      "year": 2026,
      "name": "Summer Breeze",
      "path": "summer-breeze/2026/festival.json",
      "defaultLang": "en",
      "utcOffsetHours": 2,
      "runningOrderExists": true,
      "version": 2,
      "visible": true,
      "festivalDays": [
        "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"
      ],
      "isMultiStage": true,
      "translationLangs": ["de"],
      "topGenres": {
        "Melodic Death Metal": 14,
        "Black Metal": 11
      },
      "counts": {
        "artists": 135,
        "stages": 4,
        "news": 1,
        "events": 14,
        "links": 619,
        "globalLinks": 0
      }
    }
  ]
}
```
