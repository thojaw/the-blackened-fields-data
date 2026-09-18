---
name: festival-intake
description: Add a new festival to this repo from a source URL, or pull newly-announced artists into an already-added festival, end to end (research, images, registry sync, Spotify/streaming links, index regen, PR) with minimal back-and-forth. Use whenever the user gives a festival name + announcement URL and asks to add/scaffold/intake it, or asks to check/update an already-added festival for newly announced artists.
---

# Festival Intake

You are doing the mechanical+research work of turning a festival's own
announcement page into a valid `festival.json` (or new artists appended to
one), the way a careful human maintainer would — but without narrating every
step back to the user. Read `AGENTS.md` first if you haven't already; it's
the schema of record. `scripts/scaffold-festival.mjs` does every mechanical
step (image download, `festival.json` write, registry sync, Spotify/link
enrichment, validation, `index.json` regen) — your job is everything that
script deliberately does NOT do: reading the source page, verifying facts,
finding and verifying real images, and writing descriptions/translations.

## Operating principle: decide, don't ask

Default to making the same calls this skill documents below and reporting
the result, rather than pausing to ask the user procedural questions. Only
stop and ask when something is a genuine judgment call with real
consequences the user hasn't already implied an answer to — e.g. a name
collision the automated pipeline flagged (`needsManualReview` in the
script's output), or the festival's own identity being ambiguous (multiple
editions/years live on the same URL). Things you should NOT ask about:
whether to download images (always — see below), whether to run the
registry sync, whether to open a PR vs. push directly (always a PR, unless
told otherwise), which Python/Node binary to use, whether to write German
translations (always, dual-language is the default), whether to hunt down
a Spotify link for an artist the enrichment step skipped (always — it's not
optional), or whether a new festival should start `visible: false` (always
— see step 6).

## Mode 1: Add a new festival

Triggered by something like "add this festival: `<url>`, dates X–Y" or "the
Foo Fest 2028 lineup just dropped, add it."

1. **Fetch the source page.** Use a real browser tool (not just a text
   fetch) so you can pull exact `href`s for ticket/social links — text-only
   fetches paraphrase URLs. Extract: exact name, dates, venue, stage count
   (venues often describe their own stage history in prose — read it, don't
   guess), announced artists, and every social/ticket link with its real
   URL.

2. **Verify every artist fact you're about to write**, even ones you're
   confident about from training knowledge — this project has a real
   history of exactly this kind of error (an artist's home city was wrong
   from memory in one prior session; a genre-tag site copy turned out to be
   literal and correct after search-verification). One targeted web search
   per artist, minimum, cross-checking country/origin and formation
   context. Never write a fact you haven't checked this session.

3. **Find a real image for every artist — never a logo/wordmark.** Look at
   the band's own site, label/press page, Bandcamp, or a MusicBrainz
   `url-rels` lookup, and *view* the candidate image (screenshot or fetch)
   before accepting it — a site's `og:image` is frequently just a logo, not
   a photo, and this has bitten a real session (Towards the Sinister,
   Asphagor: first `og:image` hit for each was a logo, the real photo
   needed a second search). Prefer a photo whose source page/article text
   corroborates the artist's identity (name + at least one already-verified
   fact — genre, member, or label) so you're not vulnerable to a same-name,
   different-act mixup. This matters even more than it sounds: a real
   automated MusicBrainz lookup once matched the *wrong* same-named artist
   at a perfect confidence score. If you can't find a confident photo,
   leave that one artist for a follow-up rather than guessing.

4. **Find the official festival logo** (the festival's own uploaded
   logo/poster image, not a generic banner) the same way.

5. **Write a short factual bio per artist** (2–3 sentences: genre, origin,
   one or two notable career facts), in the style already in `artists.json`
   — neutral, standalone, not tied to this festival's stages/dates. **Always
   also write a German `translations` block** covering every artist bio (plus
   festival `news`/`links`/`events` text where applicable) — dual-language
   (`en`/`de`) is the default output of this skill, not an opt-in; only skip
   it if the user explicitly says English-only.

   **Before moving on, verify coverage is actually complete, don't just
   assume it from having written some translations:** count the artists in
   your spec's `artists[]` against the `id`s present in
   `translations[].find(t => t.lang === "de").artists[]` — every single
   artist needs a German entry, including the cancelled one if there is one
   (its `annotation` needs translating too, e.g. `"Cancelled."` →
   `"Abgesagt."`). Do the same for any `news`/`events` items and for any
   untyped (`type` absent) `links[]` entries, whose `label` is user-visible
   text. This is a real gap to actively check for, not a formality — it is
   easy to translate the artists you wrote bios for in one batch and forget
   one added later (e.g. a cancelled act, or one resolved from
   `needsManualReview`).

6. **Always set `visible: false`** when creating a new festival, regardless
   of how complete the lineup looks. This is deliberate, not a fallback for
   incomplete lineups: it lets developers review the intake in-app before it
   goes live to real users. Flipping it to `true` is a separate, explicit
   step the user (or a follow-up request) takes later — never do it as part
   of the initial intake. Note in your summary that it's hidden pending
   review.

7. **Assemble a spec file** (scratch dir, not committed) matching
   `scripts/scaffold-festival.mjs`'s documented `create` shape — read the
   comment header at the top of that file for the exact structure. Every
   artist's `imageUrl` is the **remote** URL you verified in step 3; the
   script downloads it and rewrites the field to a local filename. Same for
   `logoUrl`. Never hand-write a remote URL directly into a `festival.json`
   yourself — always go through the script so nothing skips the
   download-and-convert step.

8. **Run it:**
   ```
   node scripts/scaffold-festival.mjs create <spec.json>
   ```
   Read its JSON summary. If `needsManualReview.registryIdCollisions` or
   `.linkMismatches` is non-empty, resolve those specific artists by hand:
   disambiguate on MusicBrainz's own site search (`type:group`, filtered by
   country/genre) to find the correct entity, verify a candidate Spotify
   page's bio/tracklist against already-known facts before using it (this
   is exactly how a real MusicBrainz false-match was caught and fixed in
   development), then add the registry entry / link directly.

9. **Get a Spotify link for every artist — mandatory, not best-effort — and
   put it where the app actually reads it.** Spotify links drive the in-app
   embedded preview player, so a missing one is a missing feature, not just
   missing metadata. **The registry (`artists.json`) is not what the app
   renders per-artist.** AGENTS.md says this outright: registry `links` are
   "never copied to or from a festival's own `Artist`/`links[]` entries" —
   there is nothing that syncs them into a festival file. Every other
   festival in this repo with real Spotify data (`summer-breeze`,
   `breakout`, `valhalla-fest`) stores it as an entry in *that festival's
   own* top-level `links[]` array: `{ "id", "label": "Spotify", "url",
   "type": "spotify", "artistId": "<that artist's local id>" }` — one entry
   per artist, same array the festival's other typed social links live in.
   That is the entry the app's per-artist detail page actually consumes.
   Do both, they serve different purposes: keep the registry entry too (it's
   the cross-festival, reusable source of truth this step's research
   verifies), but **the festival.json `links[]` entry is the one that makes
   the preview player actually appear — never skip it, even when the
   registry link already exists.**

   Step 8's chained `enrich-artists.mjs artists.json --write` auto-adds a
   *registry* Spotify link via MusicBrainz when it finds a high-confidence
   match (score ≥ 90 by default) — it never touches festival.json. For
   every artist in this festival, after the registry has a Spotify link
   (auto-added or hand-added below), mirror that URL into a new
   `{ type: "spotify", artistId: ... }` entry in festival.json's own
   `links[]`, resolving the artist's registry identity via `globalId` if
   present, else its local `id` (AGENTS.md "id vs globalId" resolution
   rule) — don't assume the festival-local `id` always equals the registry
   key.

   For any artist still without a registry Spotify link — reported as
   low-confidence in the enrichment output, or simply skipped — search
   Spotify directly, verify the candidate artist page (bio/genre/
   discography) actually matches the act you researched in step 2 (this is
   exactly how a real same-name-artist false match was caught in
   development), add it to the registry entry, then add the matching
   `links[]` entry as above. Only treat "no Spotify presence" as acceptable
   after a real search failed to find one, and call it out explicitly in
   your summary — most acts worth booking have a Spotify presence, so a
   silent gap here is more likely a missed search than a genuine absence.

10. **Check popularity coverage.** Step 8's chained pipeline also runs
    `enrich-popularity.mjs` against every artist it just registered, the same
    "safely against only the touched ids" pattern as the Spotify/link
    enrichment in step 9. It needs `LASTFM_API_KEY`, which most local/agent
    dev environments won't have — that's expected, not a failure to fix: the
    script fails soft and reports the still-`null` ids in the JSON summary's
    `needsManualReview.unscoredPopularity`. **Never leave those artists at
    `popularity: null` silently** — the app's tiering UI treats a missing
    value as the *lowest possible* score, which visibly mis-tiers a
    well-known act (this happened for real: HammerFall and Electric Callboy
    both landed in the smallest-font tier after an intake that predated this
    step — see `docs/history.md`, 2026-09-18). List every unscored id in your
    PR summary, and after the PR is merged to `main`, trigger the repo's
    "Enrich artist popularity" GitHub Actions workflow
    (`.github/workflows/enrich-popularity.yml`, `workflow_dispatch`, runs
    against the `LASTFM_API_KEY` repo secret) to backfill them — don't just
    leave the gap for someone else to notice later.

11. **Branch, commit, push, open a PR** (`gh pr create`) summarizing what was
    added — artist list, translation coverage, Spotify link coverage (and
    any artist left without one), popularity coverage (and any artist left
    unscored, per step 10), the `visible: false` review-pending state,
    what's still pending (e.g. unresolved images), any `needsManualReview`
    items you handled or left open. Re-run the coverage check from step 5
    one last time against the final written `festival.json` (not your
    in-memory spec) before writing this summary — that's the version that
    actually ships, and it may have gained artists (from
    `needsManualReview` fixes) since you last checked. Don't ask permission
    for the PR itself; opening a PR (not merging) is the expected end state
    of this workflow. Once the PR is merged, trigger the popularity-backfill
    workflow per step 10 if any artist was left unscored.

## Mode 2: Update an already-added festival

Triggered by "check `<festival folder>` for updates" or "the lineup grew,
pull in new artists."

1. Read the existing `festival.json`. Its own `links[]` should already have
   the source announcement URL (usually the one labeled "Website") — reuse
   it rather than asking the user for it again.

2. Re-fetch that URL the same way as step 1 of Mode 1. Diff the site's
   current artist list against `festival.json`'s existing `artists[]` by
   name (fuzzy-tolerant — a site sometimes changes casing/spacing). Anything
   not already present is new.

3. Run steps 2–5 of Mode 1 for the new artists only (fact verification,
   images, bios, **and their German translations** — new artists get the
   same dual-language treatment as a fresh intake). Do not touch the
   existing festival's `visible` flag here — Mode 2 assumes the festival was
   already reviewed and published; flipping visibility is a separate,
   explicit request, same as in Mode 1.

4. If the site now shows a running order (day/stage/time) where it
   previously said TBA — for *any* artist, old or new — collect that too;
   the update spec can set `dayDate`/`startTime`/`endTime`/`stageId` per
   artist and flip `runningOrderExists` to `true`. Existing artists' schedule
   fields aren't touched unless you're deliberately filling in a
   previously-null one from the newly-published running order.

5. Build the `add-artists` spec (see the script's header comment) and run:
   ```
   node scripts/scaffold-festival.mjs add-artists <festival.json> <spec.json>
   ```

6. Same `needsManualReview` handling, Spotify-link-coverage check (step 9 of
   Mode 1), and popularity-coverage check (step 10 of Mode 1, including
   triggering the backfill workflow post-merge for any unscored artist) as a
   fresh intake, then branch/commit/push/PR. Title the PR/commit around what
   actually changed (e.g. "Add 6 newly-announced artists to Foo Fest 2028")
   rather than reusing the original add-festival title.

## Why the script won't do the research parts

`scripts/scaffold-festival.mjs`'s own header comment says this explicitly:
it downloads/converts/references images, writes the JSON, and chains the
registry-sync/enrich/validate/index pipeline — but it has no way to *find*
a correct image, verify a fact, or resolve a same-name identity collision.
Those are exactly the places this project's history shows real mistakes
happen (wrong city from memory, logo mistaken for a photo, MusicBrainz
matching an unrelated same-named act) — automating past them would just
make the mistakes silent instead of visible.
