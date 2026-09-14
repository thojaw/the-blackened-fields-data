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
told otherwise), or which Python/Node binary to use.

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
   — neutral, standalone, not tied to this festival's stages/dates. Only
   write a German (or other) `translations` block if the user asked for
   dual-language, or the festival's own site already has other-language
   pages you're basing the intake on. Otherwise skip it — don't add
   translations nobody asked for.

6. **Decide `visible`.** Default `true`. Set `visible: false` only when the
   festival is clearly not lineup-complete yet (most artists still TBA, no
   running order) — matches the convention already used for exactly this
   case in this repo. Don't ask; just note the choice in your summary.

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

9. **Branch, commit, push, open a PR** (`gh pr create`) summarizing what was
   added — artist list, what's still pending (e.g. unresolved images), any
   `needsManualReview` items you handled or left open. Don't ask permission
   for the PR itself; opening a PR (not merging) is the expected end state
   of this workflow.

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

3. Run steps 2–5 of Mode 1 for the new artists only.

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

6. Same `needsManualReview` handling, branch/commit/push/PR as Mode 1. Title
   the PR/commit around what actually changed (e.g. "Add 6 newly-announced
   artists to Foo Fest 2028") rather than reusing the original add-festival
   title.

## Why the script won't do the research parts

`scripts/scaffold-festival.mjs`'s own header comment says this explicitly:
it downloads/converts/references images, writes the JSON, and chains the
registry-sync/enrich/validate/index pipeline — but it has no way to *find*
a correct image, verify a fact, or resolve a same-name identity collision.
Those are exactly the places this project's history shows real mistakes
happen (wrong city from memory, logo mistaken for a photo, MusicBrainz
matching an unrelated same-named act) — automating past them would just
make the mistakes silent instead of visible.
