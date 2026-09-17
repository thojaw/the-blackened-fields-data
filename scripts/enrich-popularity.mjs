#!/usr/bin/env node
// Backfills Artist.popularity in the repo-root artists.json global registry
// by looking each artist up on Last.fm and bucketing their global listener
// count into a 1-10 scale calibrated against well-known metal acts (see
// "Calibration" below), not the general-population popularity Last.fm's raw
// numbers would otherwise suggest. See AGENTS.md "Popularity" section.
//
// Usage:
//   node scripts/enrich-popularity.mjs artists.json [options]
//
// Options:
//   --write            Actually write changes back to the file (default: dry run, prints a report)
//   --force            Re-lookup and overwrite artists that already have a popularity value
//   --preview=N        Only look up the first N artists that need it (handy for a quick test run)
//
// Env:
//   LASTFM_API_KEY     Required. Free key: https://www.last.fm/api/account/create
//
// Calibration:
//   Last.fm's "listeners" count (lifetime unique listeners, not monthly --
//   Last.fm doesn't expose a monthly figure -- but it's a stable, comparable
//   proxy across artists) is mapped onto 1-10 with:
//     score = round(2.117 * log10(listeners) - 4.35), clamped to [1, 10]
//   Fixed points this line passes through/near:
//     listeners <= 100        -> 1   (no meaningful footprint)
//     listeners ~= 1,000      -> 2
//     listeners ~= 10,000     -> 4
//     listeners ~= 100,000    -> 6
//     listeners ~= 1,000,000  -> 8
//     listeners ~= 6,000,000  -> 10  (Metallica-tier)
//   An artist Last.fm has no record of at all (0 listeners / not found) gets
//   popularity 1 rather than being left unset -- per the brief, no
//   streaming footprint at all is itself the strongest signal of "least
//   popular", not an unknown to omit.
//   This is a blunt, single-source proxy, not a rigorous metric -- see the
//   "not_found"/low-listener output for artists worth a manual sanity check
//   (a listeners count can lag a fast-rising act, or over-count a same-named
//   artist in another genre).

import { readFile, writeFile } from "node:fs/promises";

const USER_AGENT = "the-blackened-fields-data-enrichment/1.0 (+https://github.com/thojaw/the-blackened-fields-data)";
const LASTFM_URL = "https://ws.audioscrobbler.com/2.0/";
const REQUEST_DELAY_MS = 250;

function parseArgs(argv) {
  const args = { write: false, force: false, preview: undefined, files: [] };
  for (const arg of argv) {
    if (arg === "--write") args.write = true;
    else if (arg === "--force") args.force = true;
    else if (arg.startsWith("--preview=")) args.preview = Number(arg.split("=")[1]);
    else args.files.push(arg);
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function popularityFromListeners(listeners) {
  if (!listeners || listeners <= 100) return 1;
  const raw = Math.round(2.117 * Math.log10(listeners) - 4.35);
  return Math.min(10, Math.max(1, raw));
}

async function lastfmArtistInfo(name, apiKey) {
  const url = new URL(LASTFM_URL);
  url.searchParams.set("method", "artist.getinfo");
  url.searchParams.set("artist", name);
  url.searchParams.set("api_key", apiKey);
  url.searchParams.set("autocorrect", "1");
  url.searchParams.set("format", "json");

  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  const data = await res.json();
  if (data.error) return { found: false };

  const listeners = Number(data.artist?.stats?.listeners ?? 0);
  const mbName = data.artist?.name;
  return { found: true, listeners, mbName };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.files.length === 0) {
    console.error("Usage: node scripts/enrich-popularity.mjs artists.json [--write] [--force] [--preview=N]");
    process.exit(1);
  }
  const apiKey = process.env.LASTFM_API_KEY;
  if (!apiKey) {
    console.error("LASTFM_API_KEY env var is required. Free key: https://www.last.fm/api/account/create");
    process.exit(1);
  }

  for (const file of args.files) {
    console.log(`\n=== ${file} ===`);
    const raw = await readFile(file, "utf8");
    const data = JSON.parse(raw);
    if (!Array.isArray(data)) {
      console.error(`${file} is not a bare array -- this script only enriches the artists.json registry.`);
      continue;
    }

    let toProcess = data.filter((a) => args.force || typeof a.popularity !== "number");
    console.log(`${toProcess.length}/${data.length} artist(s) need lookup.`);

    if (args.preview !== undefined) {
      toProcess = toProcess.slice(0, args.preview);
      console.log(`--preview=${args.preview}: only looking up ${toProcess.length} artist(s).`);
    }

    let changed = 0;
    for (const artist of toProcess) {
      let result;
      try {
        result = await lastfmArtistInfo(artist.name, apiKey);
      } catch (err) {
        console.log(`  [error]     ${artist.name}: ${err.message}`);
        await sleep(REQUEST_DELAY_MS);
        continue;
      }

      if (!result.found) {
        console.log(`  [not found] ${artist.name} -> popularity=1 (no Last.fm record)`);
        if (args.write) {
          artist.popularity = 1;
          changed++;
        }
      } else {
        const score = popularityFromListeners(result.listeners);
        console.log(
          `  [matched]   ${artist.name} -> "${result.mbName}" listeners=${result.listeners} popularity=${score}`
        );
        if (args.write) {
          artist.popularity = score;
          changed++;
        }
      }

      await sleep(REQUEST_DELAY_MS);
    }

    if (args.write && changed > 0) {
      const eol = raw.includes("\r\n") ? "\r\n" : "\n";
      const out = JSON.stringify(data, null, 2).replace(/\n/g, eol) + eol;
      await writeFile(file, out, "utf8");
      console.log(`Wrote ${changed} update(s) to ${file}.`);
    } else if (args.write) {
      console.log("No changes to write.");
    } else {
      console.log("Dry run only -- pass --write to apply results.");
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
