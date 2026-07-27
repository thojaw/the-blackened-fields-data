#!/usr/bin/env node
// Backfills Artist.genres / Artist.country in a festival.json by looking
// artists up against MusicBrainz (primary) and Last.fm (genre fallback).
//
// Usage:
//   node scripts/enrich-artists.mjs <path/to/festival.json> [options]
//
// Options:
//   --write            Actually write changes back to the file (default: dry run, prints a report)
//   --force            Re-lookup and overwrite artists that already have genres+country
//   --min-score=N      MusicBrainz search score (0-100) required to auto-accept a match (default 90)
//   --max-genres=N     Max number of genre tags to keep per artist (default 3)
//   --preview=N        Only look up the first N artists that need it (handy for a quick test run)
//
// Env:
//   LASTFM_API_KEY     Optional. If set, used as a genre fallback when MusicBrainz has no tags.
//                       Free key: https://www.last.fm/api/account/create
//
// Notes:
//   - MusicBrainz requires a descriptive User-Agent and a max of ~1 req/sec unauthenticated.
//   - Ambiguous/low-confidence matches are never auto-applied; they're printed for manual review.

import { readFile, writeFile } from "node:fs/promises";

const USER_AGENT = "the-blackened-fields-data-enrichment/1.0 (+https://github.com/thojaw/the-blackened-fields-data)";
const MB_SEARCH_URL = "https://musicbrainz.org/ws/2/artist/";
const MB_AREA_URL = "https://musicbrainz.org/ws/2/area/";
const LASTFM_URL = "https://ws.audioscrobbler.com/2.0/";
const REQUEST_DELAY_MS = 1100;
const MAX_AREA_HOPS = 4;

function parseArgs(argv) {
  const args = { write: false, force: false, minScore: 90, maxGenres: 3, preview: undefined, files: [] };
  for (const arg of argv) {
    if (arg === "--write") args.write = true;
    else if (arg === "--force") args.force = true;
    else if (arg.startsWith("--min-score=")) args.minScore = Number(arg.split("=")[1]);
    else if (arg.startsWith("--max-genres=")) args.maxGenres = Number(arg.split("=")[1]);
    else if (arg.startsWith("--preview=")) args.preview = Number(arg.split("=")[1]);
    else args.files.push(arg);
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const RETRYABLE_STATUSES = new Set([429, 502, 503, 504]);
const MAX_RETRIES = 4;

// Serializes every MusicBrainz request (search + area walks alike) to
// respect the ~1 req/sec unauthenticated rate limit, regardless of caller.
let mbReady = Promise.resolve();
function mbFetchJson(url, { label }) {
  const run = async () => {
    for (let attempt = 0; ; attempt++) {
      const res = await fetch(url, { headers: { "User-Agent": USER_AGENT, Accept: "application/json" } });
      if (res.ok) return res.json();

      if (!RETRYABLE_STATUSES.has(res.status) || attempt >= MAX_RETRIES) {
        throw new Error(`MusicBrainz ${res.status} for "${label}"`);
      }

      await sleep(REQUEST_DELAY_MS * 2 ** attempt);
    }
  };

  const result = mbReady.then(async () => {
    const r = await run();
    await sleep(REQUEST_DELAY_MS);
    return r;
  });
  // Chain the gate on completion (success or failure) so callers still queue in order.
  mbReady = result.then(
    () => {},
    () => {}
  );
  return result;
}

async function musicbrainzLookup(name) {
  const url = new URL(MB_SEARCH_URL);
  url.searchParams.set("query", `artist:"${name}"`);
  url.searchParams.set("fmt", "json");
  url.searchParams.set("limit", "5");
  url.searchParams.set("inc", "genres+tags");

  const data = await mbFetchJson(url, { label: name });
  return data.artists ?? [];
}

// MusicBrainz only sets Artist.country when `area` IS a Country entity.
// When the area is more specific (city/county/state, e.g. Jersey City ->
// Hudson County -> New Jersey), we have to walk the "part of" hierarchy
// ourselves to find an enclosing area with an ISO code.
async function resolveCountryFromArea(areaId, depth = 0) {
  if (!areaId || depth > MAX_AREA_HOPS) return undefined;

  const url = new URL(`${MB_AREA_URL}${areaId}`);
  url.searchParams.set("fmt", "json");
  url.searchParams.set("inc", "area-rels");

  const area = await mbFetchJson(url, { label: `area:${areaId}` });

  if (area["iso-3166-1-codes"]?.length) {
    return area["iso-3166-1-codes"][0].toLowerCase();
  }
  if (area["iso-3166-2-codes"]?.length) {
    return area["iso-3166-2-codes"][0].split("-")[0].toLowerCase();
  }

  const parentRel = (area.relations ?? []).find(
    (r) => r.type === "part of" && r["target-type"] === "area" && r.direction === "backward"
  );
  if (!parentRel) return undefined;

  return resolveCountryFromArea(parentRel.area.id, depth + 1);
}

async function lastfmTopTags(name, apiKey) {
  const url = new URL(LASTFM_URL);
  url.searchParams.set("method", "artist.getTopTags");
  url.searchParams.set("artist", name);
  url.searchParams.set("api_key", apiKey);
  url.searchParams.set("autocorrect", "1");
  url.searchParams.set("format", "json");

  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) return [];
  const data = await res.json();
  const tags = data?.toptags?.tag ?? [];
  return tags.map((t) => t.name).filter(Boolean).map(toTitleCase);
}

// MusicBrainz/Last.fm tags are lowercase free text ("post-metal"); the
// festival.json schema wants title case ("Post-Metal") with no lookup table.
function toTitleCase(str) {
  return str.replace(/[^\s-]+/g, (word) => word[0].toUpperCase() + word.slice(1));
}

function pickGenres(mbArtist, maxGenres) {
  const tags = mbArtist.genres?.length ? mbArtist.genres : mbArtist.tags ?? [];
  return tags
    .slice()
    .sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
    .slice(0, maxGenres)
    .map((t) => toTitleCase(t.name));
}

async function enrichArtist(artist, { minScore, maxGenres, lastfmKey }) {
  const candidates = await musicbrainzLookup(artist.name);
  if (candidates.length === 0) {
    return { status: "not_found" };
  }

  const best = candidates[0];
  const score = Number(best.score ?? 0);
  if (score < minScore) {
    return {
      status: "ambiguous",
      candidates: candidates.slice(0, 3).map((c) => ({ name: c.name, score: c.score, country: c.country })),
    };
  }

  let country = best.country ? best.country.toLowerCase() : undefined;
  if (!country) {
    const areaId = best.area?.id ?? best["begin-area"]?.id;
    country = await resolveCountryFromArea(areaId);
  }

  let genres = pickGenres(best, maxGenres);

  if (genres.length === 0 && lastfmKey) {
    await sleep(REQUEST_DELAY_MS);
    genres = (await lastfmTopTags(artist.name, lastfmKey)).slice(0, maxGenres);
  }

  return {
    status: "matched",
    mbName: best.name,
    score,
    country,
    genres,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.files.length === 0) {
    console.error("Usage: node scripts/enrich-artists.mjs <festival.json> [--write] [--force] [--min-score=90] [--max-genres=3]");
    process.exit(1);
  }
  const lastfmKey = process.env.LASTFM_API_KEY;

  for (const file of args.files) {
    console.log(`\n=== ${file} ===`);
    const raw = await readFile(file, "utf8");
    const data = JSON.parse(raw);

    let toProcess = data.artists.filter(
      (a) => args.force || !a.country || !a.genres || a.genres.length === 0
    );

    console.log(`${toProcess.length}/${data.artists.length} artist(s) need lookup.`);

    if (args.preview !== undefined) {
      toProcess = toProcess.slice(0, args.preview);
      console.log(`--preview=${args.preview}: only looking up ${toProcess.length} artist(s).`);
    }

    let changed = 0;
    for (const artist of toProcess) {
      let result;
      try {
        result = await enrichArtist(artist, { minScore: args.minScore, maxGenres: args.maxGenres, lastfmKey });
      } catch (err) {
        console.log(`  [error]     ${artist.name}: ${err.message}`);
        continue;
      }

      if (result.status === "not_found") {
        console.log(`  [not found] ${artist.name}`);
      } else if (result.status === "ambiguous") {
        console.log(`  [ambiguous] ${artist.name} -- candidates: ${result.candidates.map((c) => `${c.name} (score ${c.score}, ${c.country ?? "?"})`).join("; ")}`);
      } else {
        const countryStr = result.country ?? "-";
        const genresStr = result.genres.length ? result.genres.join(", ") : "-";
        console.log(`  [matched]   ${artist.name} -> "${result.mbName}" (score ${result.score}) country=${countryStr} genres=[${genresStr}]`);

        if (args.write) {
          if (result.country) artist.country = result.country;
          if (result.genres.length) artist.genres = result.genres;
          changed++;
        }
      }
    }

    if (args.write && changed > 0) {
      const eol = raw.includes("\r\n") ? "\r\n" : "\n";
      const out = JSON.stringify(data, null, 2).replace(/\n/g, eol) + eol;
      await writeFile(file, out, "utf8");
      console.log(`Wrote ${changed} update(s) to ${file}.`);
    } else if (args.write) {
      console.log("No changes to write.");
    } else {
      console.log("Dry run only -- pass --write to apply matched results.");
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
