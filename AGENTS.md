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

## Multi-festival index (`index.json`)

`index.json` at the repo root is a **generated** summary of every
`festival.json` in the repo, one entry per festival/year. It duplicates
each festival's identity/header fields (name, date range, language, etc.)
and adds cheap aggregate counts (artist count, stage count, ...), so a
multi-festival picker/UI can list and sort festivals without loading every
full `festival.json`.

- Formal shape: `schema/festival-index.schema.json` (JSON Schema, draft
  2020-12).
- Regenerated by `scripts/generate-index.py` (stdlib-only Python, rebuilds
  all entries from scratch every run — there are too few festivals for
  incremental updates to be worth the complexity):
  ```
  python3 scripts/generate-index.py
  ```
- **Do not hand-edit `index.json`.** A GitHub Actions workflow
  (`.github/workflows/update-festival-index.yml`) regenerates and commits
  it automatically whenever a pull request against `main` touches any
  `festival.json`. If you edit a `festival.json` locally, re-run the script
  yourself to keep `index.json` in sync (CI will also catch it on the PR).

### `FestivalIndexEntry` shape (conceptual)

```
FestivalIndexEntry {
  id, slug, year, name, path,        -- identity + path to the source festival.json
  defaultLang, utcOffsetHours, runningOrderExists, version,
  festivalDays[],   -- full copy of the source festivalDays; first/last = date range
  isMultiStage,     -- true if stages.length > 1
  translationLangs[],  -- BCP 47 langs with a translations[] entry, e.g. ["de"]
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
      "festivalDays": [
        "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"
      ],
      "isMultiStage": true,
      "translationLangs": ["de"],
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
