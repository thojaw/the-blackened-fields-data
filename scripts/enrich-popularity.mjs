#!/usr/bin/env node
// Backfills Artist.popularity in the repo-root artists.json global registry
// by looking each artist up on Spotify (default) or Last.fm and bucketing
// a raw popularity signal into a 1-10 scale calibrated against well-known
// metal acts, not the general-population popularity the raw numbers would
// otherwise suggest. See AGENTS.md "Popularity" section.
//
// Usage:
//   node scripts/enrich-popularity.mjs artists.json [options]
//
// Options:
//   --source=spotify|lastfm   Which service to query (default: spotify)
//   --write                   Actually write changes back to the file (default: dry run, prints a report)
//   --force                   Re-lookup and overwrite artists that already have a popularity value
//   --preview=N               Only look up the first N artists that need it (handy for a quick test run)
//
// Env:
//   Spotify (source=spotify, the default) -- Client Credentials flow, no user login needed.
//   Free app: https://developer.spotify.com/dashboard -> Create app -> Settings.
//     SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET   preferred names
//     SPOTIFY_CLIENTID / SPOTIFY_SECRET           fallback, used only if the above are unset --
//                                                  matches this repo's GitHub Actions secret names,
//                                                  so a CI step can export those directly.
//   Last.fm (source=lastfm):
//     LASTFM_API_KEY     Required. Free key: https://www.last.fm/api/account/create
//
// Calibration:
//   Both sources are mapped onto 1-10 via a hand-set breakpoint table
//   (SPOTIFY_POPULARITY_THRESHOLDS / LASTFM_LISTENER_THRESHOLDS below), not
//   a continuous formula. A single log curve was tried first (for Last.fm)
//   and rejected: with a fixed step size per point, any two artists within
//   roughly the same factor of each other always land on the same integer
//   regardless of what tier boundary sits between them, while a huge, more
//   meaningful gap can compress into just 2-3 points of separation. A table
//   lets each boundary be placed deliberately, and it's directly editable
//   if a run's results don't match scene judgment (which is expected --
//   these are first-guess anchors, not measured constants; see AGENTS.md).
//
//   Spotify is preferred over Last.fm as the default source: Spotify's
//   `popularity` is recency-weighted (recent play volume, not "ever
//   scrobbled"), and Last.fm's user base skews toward an older
//   scrobbling habit that isn't representative of how most fans listen
//   today. Last.fm remains available via --source=lastfm as a fallback or
//   cross-check (e.g. for an act Spotify's search can't resolve).
//
//   An artist not found at all on the chosen source gets popularity 1
//   rather than being left unset -- per the brief, no streaming footprint
//   at all is itself the strongest signal of "least popular", not an
//   unknown to omit.
//
//   This is a blunt, single-source proxy either way, not a rigorous
//   metric -- see the "not_found" output for artists worth a manual
//   sanity check (name collisions with an artist in another genre, a
//   fast-rising act the source hasn't caught up to yet, etc.).

import { readFile, writeFile } from "node:fs/promises";

const USER_AGENT = "the-blackened-fields-data-enrichment/1.0 (+https://github.com/thojaw/the-blackened-fields-data)";
const LASTFM_URL = "https://ws.audioscrobbler.com/2.0/";
const SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token";
const SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search";
const REQUEST_DELAY_MS = 250;

function parseArgs(argv) {
  const args = { write: false, force: false, preview: undefined, source: "spotify", files: [] };
  for (const arg of argv) {
    if (arg === "--write") args.write = true;
    else if (arg === "--force") args.force = true;
    else if (arg.startsWith("--preview=")) args.preview = Number(arg.split("=")[1]);
    else if (arg.startsWith("--source=")) args.source = arg.split("=")[1];
    else args.files.push(arg);
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function bucket(value, thresholds) {
  const n = value ?? 0;
  for (const [min, score] of thresholds) {
    if (n >= min) return score;
  }
  return 1;
}

// [minListeners, score], checked highest-first. See "Calibration" above.
const LASTFM_LISTENER_THRESHOLDS = [
  [3_000_000, 10], // Metallica/Slayer/Iron Maiden-tier global headliners
  [1_200_000, 9],
  [500_000, 8], // established festival headliners (e.g. Testament, Helloween-scale)
  [180_000, 7],
  [60_000, 6],
  [20_000, 5],
  [6_000, 4],
  [1_500, 3],
  [300, 2],
  [0, 1], // no meaningful footprint / not found
];

// [minPopularity (0-100), score], checked highest-first. First-guess
// anchors, not measured -- sanity-check against a --preview run and tune
// these directly if real output doesn't match scene judgment (Spotify's
// popularity scale is famously compressed at the top: even global
// superstars rarely clear the high 80s/90s).
const SPOTIFY_POPULARITY_THRESHOLDS = [
  [80, 10], // Metallica/Slipknot-tier global crossover
  [65, 9],
  [55, 8], // established festival headliners (e.g. Testament, Helloween-scale)
  [45, 7],
  [35, 6],
  [25, 5],
  [18, 4],
  [12, 3],
  [6, 2],
  [0, 1], // no meaningful footprint / not found
];

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
  return { found: true, matchedName: data.artist?.name, raw: listeners };
}

async function spotifyGetToken(clientId, clientSecret) {
  const res = await fetch(SPOTIFY_TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
  });
  if (!res.ok) {
    throw new Error(`Spotify token request failed: ${res.status} ${await res.text()}`);
  }
  const data = await res.json();
  return data.access_token;
}

async function spotifySearchArtist(name, token) {
  const url = new URL(SPOTIFY_SEARCH_URL);
  url.searchParams.set("q", `artist:"${name}"`);
  url.searchParams.set("type", "artist");
  url.searchParams.set("limit", "5");

  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });

  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After") ?? 1);
    await sleep((retryAfter + 1) * 1000);
    return spotifySearchArtist(name, token);
  }
  if (!res.ok) {
    throw new Error(`Spotify search failed: ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  const items = data.artists?.items ?? [];
  if (items.length === 0) return { found: false };

  // Prefer a case-insensitive exact name match over Spotify's own result
  // ordering, which can rank a bigger same-named artist in another genre
  // above the one actually being looked up.
  const exact = items.find((a) => a.name?.toLowerCase() === name.toLowerCase());
  const best = exact ?? items[0];

  return { found: true, matchedName: best.name, raw: best.popularity };
}

async function lookupArtist(name, source, ctx) {
  if (source === "lastfm") return lastfmArtistInfo(name, ctx.lastfmKey);
  return spotifySearchArtist(name, ctx.spotifyToken);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.files.length === 0) {
    console.error(
      "Usage: node scripts/enrich-popularity.mjs artists.json [--source=spotify|lastfm] [--write] [--force] [--preview=N]"
    );
    process.exit(1);
  }
  if (args.source !== "spotify" && args.source !== "lastfm") {
    console.error(`Unknown --source=${args.source} (expected "spotify" or "lastfm")`);
    process.exit(1);
  }

  const ctx = {};
  if (args.source === "lastfm") {
    ctx.lastfmKey = process.env.LASTFM_API_KEY;
    if (!ctx.lastfmKey) {
      console.error("LASTFM_API_KEY env var is required for --source=lastfm. Free key: https://www.last.fm/api/account/create");
      process.exit(1);
    }
  } else {
    const clientId = process.env.SPOTIFY_CLIENT_ID ?? process.env.SPOTIFY_CLIENTID;
    const clientSecret = process.env.SPOTIFY_CLIENT_SECRET ?? process.env.SPOTIFY_SECRET;
    if (!clientId || !clientSecret) {
      console.error(
        "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET (or SPOTIFY_CLIENTID/SPOTIFY_SECRET) env vars are required for --source=spotify. Free app: https://developer.spotify.com/dashboard"
      );
      process.exit(1);
    }
    ctx.spotifyToken = await spotifyGetToken(clientId, clientSecret);
  }

  const thresholds = args.source === "lastfm" ? LASTFM_LISTENER_THRESHOLDS : SPOTIFY_POPULARITY_THRESHOLDS;
  const rawLabel = args.source === "lastfm" ? "listeners" : "popularity(raw)";

  for (const file of args.files) {
    console.log(`\n=== ${file} (source=${args.source}) ===`);
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
        result = await lookupArtist(artist.name, args.source, ctx);
      } catch (err) {
        console.log(`  [error]     ${artist.name}: ${err.message}`);
        await sleep(REQUEST_DELAY_MS);
        continue;
      }

      if (!result.found) {
        console.log(`  [not found] ${artist.name} -> popularity=1 (no ${args.source} record)`);
        if (args.write) {
          artist.popularity = 1;
          changed++;
        }
      } else {
        const score = bucket(result.raw, thresholds);
        console.log(`  [matched]   ${artist.name} -> "${result.matchedName}" ${rawLabel}=${result.raw} popularity=${score}`);
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
