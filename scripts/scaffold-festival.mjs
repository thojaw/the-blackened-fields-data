#!/usr/bin/env node
// Mechanical assembly of a festival.json (or additions to one) from a small
// JSON "spec" file: downloads every artist image + the festival logo locally
// (this repo never references external image URLs -- see AGENTS.md), writes
// the festival.json, then chains the existing Python pipeline
// (sync-artist-registry.py --apply, enrich-artists.mjs for Spotify/social
// links, enrich-popularity.mjs for the popularity registry field,
// validate-artists.py --check-festivals, generate-index.py) so the whole
// thing lands in one already-consistent commit instead of a dozen manual
// steps. Popularity enrichment needs LASTFM_API_KEY, which most local dev
// environments won't have -- it fails soft and reports any still-unscored
// artist ids in needsManualReview.unscoredPopularity instead of erroring;
// see .claude/skills/festival-intake/SKILL.md for the follow-up.
//
// This script does NOT write descriptions, pick images, verify facts, or
// resolve genuine artist-identity collisions -- that's still a research/
// verification job for whoever (human or agent) builds the spec file. See
// .claude/skills/festival-intake/SKILL.md for the end-to-end procedure this
// script is one step of.
//
// Usage:
//   node scripts/scaffold-festival.mjs create <spec.json>
//   node scripts/scaffold-festival.mjs add-artists <festival.json> <spec.json>
//
// create spec.json shape:
//   {
//     "id": "dark-easter-metal-meeting-2027",   // required, "<slug>-<year>"
//     "name": "Dark Easter Metal Meeting",       // required
//     "year": 2027,                              // required
//     "folder": "dark-easter-metal-meeting",     // optional, default: id minus "-<year>"
//     "defaultLang": "en",                       // optional, default "en"
//     "visible": false,                          // optional, default true
//     "runningOrderExists": false,               // required
//     "utcOffsetHours": 1,                       // required
//     "festivalDays": ["2027-03-27", "2027-03-28"], // required
//     "stages": [{ "id": "s1", "name": "Backstage Werk" }],  // optional
//     "news": [],                                // optional, default []
//     "links": [{ "id": "l1", "label": "Website", "url": "https://..." }], // optional, default []
//     "logoUrl": "https://.../logo-source.jpg",  // optional; always downloaded + converted to logo.png
//     "artists": [ ...ArtistSpec ],              // required, see below
//     "translations": [{ "lang": "de", "artists": [...], "links": [...] }] // optional, passed through
//   }
//
// add-artists spec.json shape:
//   {
//     "artists": [ ...ArtistSpec ],
//     "translations": [{ "lang": "de", "artists": [...] }],  // optional, merged by lang
//     "runningOrderExists": true                              // optional override
//   }
//
// ArtistSpec:
//   {
//     "id": "emperor", "name": "Emperor",
//     "description": "...", "genres": ["Black Metal"], "country": "no",
//     "annotation": null, "dayDate": null, "startTime": null, "endTime": null,
//     "stageId": null, "replacedArtistId": null,
//     "imageUrl": "https://..."   // required source; downloaded locally, field is
//                                  // overwritten with the local filename ("aN.jpg")
//   }
//
// Never put a remote URL in the final festival.json's imageUrl -- every
// artist image and the logo are always downloaded and stored locally next
// to festival.json, matching every other festival in this repo.
//
// Known limitation: giving an ArtistSpec a local `id` that already equals
// an existing artists.json slug is treated as a confirmed identity claim,
// not a lookup -- sync-artist-registry.py resolves it immediately with no
// name-similarity check (see AGENTS.md's id-vs-globalId resolution rule;
// this is deliberate upstream behaviour, not something this script can or
// should second-guess). Only reuse an existing slug as a local id after
// you (or the calling skill) have already verified it's genuinely the same
// real-world act -- never guess a slug to "link up" an artist.

import { readFile, writeFile, mkdir, readdir, unlink } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const EXT_BY_CONTENT_TYPE = {
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/gif": "gif",
};

function pythonCmd() {
  for (const cmd of ["python3", "python", "py"]) {
    try {
      execFileSync(cmd, ["--version"], { stdio: "ignore" });
      return cmd;
    } catch {
      /* try next */
    }
  }
  throw new Error("No working Python interpreter found (tried python3, python, py).");
}

async function downloadTo(url, destNoExt, { convertToPng = false } = {}) {
  const res = await fetch(url, {
    headers: { "User-Agent": "the-blackened-fields-data-scaffold/1.0 (+https://github.com/thojaw/the-blackened-fields-data)" },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status}) for ${url}`);
  const contentType = (res.headers.get("content-type") || "").split(";")[0].trim();
  let ext = EXT_BY_CONTENT_TYPE[contentType];
  if (!ext) {
    const fromUrl = path.extname(new URL(url).pathname).replace(".", "").toLowerCase();
    ext = fromUrl || "jpg";
  }
  const buf = Buffer.from(await res.arrayBuffer());

  if (convertToPng && ext !== "png") {
    const srcPath = `${destNoExt}.src.${ext}`;
    await writeFile(srcPath, buf);
    execFileSync("npx", ["--yes", "sharp-cli", "-i", srcPath, "-o", `${destNoExt}.png`], { stdio: "inherit", shell: process.platform === "win32" });
    await unlink(srcPath);
    return `${path.basename(destNoExt)}.png`;
  }
  if (convertToPng && ext === "png") {
    await writeFile(`${destNoExt}.png`, buf);
    return `${path.basename(destNoExt)}.png`;
  }
  await writeFile(`${destNoExt}.${ext}`, buf);
  return `${path.basename(destNoExt)}.${ext}`;
}

async function nextArtistIndex(folder) {
  if (!existsSync(folder)) return 1;
  const files = await readdir(folder);
  const nums = files
    .map((f) => f.match(/^a(\d+)\.\w+$/))
    .filter(Boolean)
    .map((m) => Number(m[1]));
  return nums.length ? Math.max(...nums) + 1 : 1;
}

async function downloadArtistImages(artists, folder) {
  let n = await nextArtistIndex(folder);
  for (const artist of artists) {
    if (!artist.imageUrl || !/^https?:\/\//.test(artist.imageUrl)) {
      throw new Error(`Artist "${artist.name}" (${artist.id}) needs a remote imageUrl to download -- got: ${artist.imageUrl}`);
    }
    const filename = await downloadTo(artist.imageUrl, path.join(folder, `a${n}`));
    console.log(`  downloaded image for ${artist.name} -> ${filename}`);
    artist.imageUrl = filename;
    n++;
  }
}

function artistFromSpec(a) {
  // Only ever writes fields the schema defines -- drop anything extra a
  // spec author left lying around (e.g. helper fields used during research).
  const out = {
    id: a.id,
    name: a.name,
    imageUrl: a.imageUrl,
    description: a.description,
    dayDate: a.dayDate ?? null,
    startTime: a.startTime ?? null,
    endTime: a.endTime ?? null,
    annotation: a.annotation ?? null,
  };
  if (a.stageId) out.stageId = a.stageId;
  if (a.genres?.length) out.genres = a.genres;
  if (a.country) out.country = a.country;
  if (a.replacedArtistId) out.replacedArtistId = a.replacedArtistId;
  if (a.globalId) out.globalId = a.globalId;
  return out;
}

function mergeTranslations(existing, incoming) {
  const byLang = new Map((existing || []).map((t) => [t.lang, t]));
  for (const inc of incoming || []) {
    let t = byLang.get(inc.lang);
    if (!t) {
      t = { lang: inc.lang };
      byLang.set(inc.lang, t);
    }
    for (const key of ["artists", "news", "links", "events"]) {
      if (inc[key]?.length) t[key] = [...(t[key] || []), ...inc[key]];
    }
  }
  const merged = [...byLang.values()];
  return merged.length ? merged : undefined;
}

async function writeJson(filePath, data) {
  await writeFile(filePath, JSON.stringify(data, null, 2) + "\n", "utf8");
}

function run(cmd, args, opts = {}) {
  console.log(`  $ ${cmd} ${args.join(" ")}`);
  const out = execFileSync(cmd, args, { cwd: REPO_ROOT, encoding: "utf8", ...opts });
  if (out?.trim()) console.log(out.trim().replace(/^/gm, "  "));
  return out;
}

// Registers any artist that sync-artist-registry.py left in its "needs
// confirmation" bucket as a brand-new registry entry instead, mirroring
// exactly what --apply does for a genuinely-new artist. This repo's own
// genre-scoped naming makes real collisions rare (see AGENTS.md), and in
// practice the "confirm" bucket is almost always a same-name-different-
// band false positive from the fuzzy matcher, not a real duplicate -- but
// as a real safety check, it still refuses to touch an id that's already
// taken by a *different* artist name rather than silently overwriting it.
// `festivalArtists` here must be the CURRENT festival.json entries (read
// after sync-artist-registry.py --apply already ran), not the original spec
// objects -- the python step writes globalId to the file, not back into our
// in-memory spec, and for an existing/multi-show festival the local `id`
// can legitimately differ from the resolved global identity.
function slugify(name) {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

async function autoRegisterUnconfirmed(festivalArtists) {
  const registryPath = path.join(REPO_ROOT, "artists.json");
  const registry = JSON.parse(await readFile(registryPath, "utf8"));
  const byId = new Map(registry.map((a) => [a.id, a]));

  const added = [];
  const skipped = [];
  const resolved = new Map(); // local artist id -> final registry/global id
  for (const artist of festivalArtists) {
    // Resolution rule (AGENTS.md): globalId if present, else id itself if
    // it already looks like a registry slug, else no identity yet.
    let globalId = artist.globalId || artist.id;
    if (byId.has(globalId)) {
      resolved.set(artist.id, globalId);
      continue; // already registered (matched, or id already is the slug)
    }

    const existing = registry.find((a) => a.id === globalId);
    if (existing && existing.name !== artist.name) {
      skipped.push({ id: globalId, festivalArtist: artist.name, registryEntry: existing.name });
      continue; // leave unresolved -- don't enrich against someone else's entry
    }

    // A brand-new entry needs a real slug id (AGENTS.md), not a bare
    // festival-local id like "a1" -- that only happens when no globalId was
    // given and the local id isn't already a registry-shaped slug.
    if (!artist.globalId && !existing) {
      let candidate = slugify(artist.name);
      let suffix = 2;
      while (byId.has(candidate) && byId.get(candidate).name !== artist.name) {
        candidate = `${slugify(artist.name)}-${suffix++}`;
      }
      globalId = candidate;
    }
    resolved.set(artist.id, globalId);

    const entry = { id: globalId, name: artist.name, description: artist.description };
    if (artist.genres?.length) entry.genres = artist.genres;
    if (artist.country) entry.country = artist.country;
    registry.push(entry);
    byId.set(globalId, entry);
    added.push(globalId);
  }

  if (added.length) await writeJson(registryPath, registry);
  return { added, skipped, resolved };
}

// Runs enrich-artists.mjs (registry mode) against ONLY the ids we just
// touched, then merges just the `links` field back -- never genres/country,
// which this repo's hand-verified festival-context data should win over
// MusicBrainz's tag soup. Guards against MusicBrainz resolving the *wrong*
// same-named entity (this happened for real during development: MusicBrainz's
// top "Bianca" match was an unrelated German act) by comparing country
// before/after and discarding the whole enrichment for that artist -- not
// just the country field -- if it moved.
async function enrichLinksSafely(globalIds) {
  const registryPath = path.join(REPO_ROOT, "artists.json");
  const registry = JSON.parse(await readFile(registryPath, "utf8"));
  const targets = registry.filter((a) => globalIds.includes(a.id));
  if (!targets.length) return { linked: [], mismatched: [] };

  const before = new Map(targets.map((a) => [a.id, a.country]));
  const tmpPath = path.join(REPO_ROOT, ".scaffold-enrich-tmp.json");
  await writeJson(tmpPath, targets);

  try {
    run("node", ["scripts/enrich-artists.mjs", tmpPath, "--write"]);
  } catch (err) {
    console.warn(`  enrich-artists.mjs failed, skipping link enrichment: ${err.message}`);
    await unlink(tmpPath).catch(() => {});
    return { linked: [], mismatched: [] };
  }

  const enriched = JSON.parse(await readFile(tmpPath, "utf8"));
  await unlink(tmpPath);

  const linked = [];
  const mismatched = [];
  for (const e of enriched) {
    const beforeCountry = before.get(e.id);
    if (beforeCountry && e.country && e.country !== beforeCountry) {
      mismatched.push({ id: e.id, expected: beforeCountry, got: e.country });
      continue; // discard this artist's enrichment entirely -- likely wrong MusicBrainz entity
    }
    if (e.links?.length) {
      const target = registry.find((a) => a.id === e.id);
      target.links = e.links;
      linked.push(e.id);
    }
  }
  await writeJson(registryPath, registry);
  return { linked, mismatched };
}

// Runs enrich-popularity.mjs (registry mode) against ONLY the ids we just
// touched, so newly scaffolded artists don't silently sit at
// popularity: null forever -- the app's tiering UI treats a missing value
// as the *lowest* possible score, which mis-tiers well-known acts (see
// docs/history.md, 2026-09-18). Needs LASTFM_API_KEY, which most local dev
// environments won't have -- that's expected, not an error: this fails soft
// and the caller (cmdCreate/cmdAddArtists) reports which ids are still
// unscored so the intake PR can call it out and a follow-up run of the
// "Enrich artist popularity" GitHub Actions workflow (workflow_dispatch on
// main, uses the repo's LASTFM_API_KEY secret) can backfill them later.
async function enrichPopularitySafely(globalIds) {
  const registryPath = path.join(REPO_ROOT, "artists.json");
  const registry = JSON.parse(await readFile(registryPath, "utf8"));
  const targets = registry.filter((a) => globalIds.includes(a.id) && typeof a.popularity !== "number");
  if (!targets.length) return { scored: [], unscored: [] };

  const tmpPath = path.join(REPO_ROOT, ".scaffold-popularity-tmp.json");
  await writeJson(tmpPath, targets);

  try {
    run("node", ["scripts/enrich-popularity.mjs", tmpPath, "--write"]);
  } catch (err) {
    console.warn(`  enrich-popularity.mjs failed/unavailable, leaving popularity unset: ${err.message}`);
    await unlink(tmpPath).catch(() => {});
    return { scored: [], unscored: targets.map((a) => a.id) };
  }

  const enriched = JSON.parse(await readFile(tmpPath, "utf8"));
  await unlink(tmpPath);

  const scored = [];
  const unscored = [];
  for (const e of enriched) {
    if (typeof e.popularity === "number") {
      const target = registry.find((a) => a.id === e.id);
      target.popularity = e.popularity;
      scored.push(e.id);
    } else {
      unscored.push(e.id);
    }
  }
  await writeJson(registryPath, registry);
  return { scored, unscored };
}

async function runPipeline(festivalRelPath, touchedIds) {
  const py = pythonCmd();
  console.log("Syncing artist registry...");
  run(py, ["scripts/sync-artist-registry.py", festivalRelPath, "--apply"]);

  const festivalPath = path.join(REPO_ROOT, festivalRelPath);
  let festival = JSON.parse(await readFile(festivalPath, "utf8"));
  const touchedFestivalArtists = festival.artists.filter((a) => touchedIds.includes(a.id));

  const { added: autoAdded, skipped, resolved } = await autoRegisterUnconfirmed(touchedFestivalArtists);
  if (autoAdded.length) console.log(`  auto-registered (was 'needs confirmation'): ${autoAdded.join(", ")}`);
  if (skipped.length) {
    console.warn("  SKIPPED -- id collision with a DIFFERENT existing artist, needs manual review:");
    for (const s of skipped) console.warn(`    ${s.id}: festival has "${s.festivalArtist}", registry already has "${s.registryEntry}"`);
  }

  // Backfill globalId on the file for anything we just auto-registered
  // (already-matched artists were handled by sync-artist-registry.py itself).
  festival = JSON.parse(await readFile(festivalPath, "utf8"));
  for (const a of festival.artists) {
    if (!a.globalId && resolved.has(a.id) && autoAdded.includes(resolved.get(a.id))) {
      a.globalId = resolved.get(a.id);
    }
  }
  await writeJson(festivalPath, festival);

  const globalIds = [...resolved.values()];
  console.log("Enriching links (Spotify/Bandcamp/etc.)...");
  const { linked, mismatched } = await enrichLinksSafely(globalIds);
  if (linked.length) console.log(`  linked: ${linked.join(", ")}`);
  if (mismatched.length) {
    console.warn("  MISMATCH -- MusicBrainz likely resolved a different same-named entity, left unlinked:");
    for (const m of mismatched) console.warn(`    ${m.id}: expected country "${m.expected}", MusicBrainz said "${m.got}"`);
  }

  console.log("Enriching popularity (Last.fm)...");
  const { scored, unscored } = await enrichPopularitySafely(globalIds);
  if (scored.length) console.log(`  scored: ${scored.join(", ")}`);
  if (unscored.length) {
    console.warn("  UNSCORED -- LASTFM_API_KEY missing/failed locally, popularity left null:");
    for (const id of unscored) console.warn(`    ${id}`);
  }

  console.log("Validating...");
  run(py, ["scripts/validate-artists.py", "--check-festivals"]);

  console.log("Regenerating index.json...");
  run(py, ["scripts/generate-index.py"]);

  return { skipped, mismatched, unscored };
}

async function cmdCreate(specPath) {
  const spec = JSON.parse(await readFile(specPath, "utf8"));
  for (const req of ["id", "name", "year", "runningOrderExists", "utcOffsetHours", "festivalDays", "artists"]) {
    if (spec[req] === undefined) throw new Error(`spec is missing required field: ${req}`);
  }

  const folderSlug = spec.folder || spec.id.replace(new RegExp(`-${spec.year}$`), "");
  const folder = path.join(REPO_ROOT, folderSlug, String(spec.year));
  await mkdir(folder, { recursive: true });

  console.log(`Downloading ${spec.artists.length} artist image(s)...`);
  await downloadArtistImages(spec.artists, folder);

  if (spec.logoUrl) {
    console.log("Downloading + converting logo...");
    await downloadTo(spec.logoUrl, path.join(folder, "logo"), { convertToPng: true });
  }

  const festival = {
    id: spec.id,
    name: spec.name,
    version: 1,
    year: spec.year,
    defaultLang: spec.defaultLang || "en",
    ...(spec.visible === false ? { visible: false } : {}),
    runningOrderExists: spec.runningOrderExists,
    utcOffsetHours: spec.utcOffsetHours,
    festivalDays: spec.festivalDays,
    ...(spec.stages?.length ? { stages: spec.stages } : {}),
    news: spec.news || [],
    links: spec.links || [],
    artists: spec.artists.map(artistFromSpec),
    ...(spec.translations?.length ? { translations: spec.translations } : {}),
  };

  const festivalRelPath = path
    .relative(REPO_ROOT, path.join(folder, "festival.json"))
    .split(path.sep)
    .join("/");
  await writeJson(path.join(REPO_ROOT, festivalRelPath), festival);
  console.log(`Wrote ${festivalRelPath}`);

  const { skipped, mismatched, unscored } = await runPipeline(festivalRelPath, spec.artists.map((a) => a.id));

  console.log("\nDone.");
  console.log(JSON.stringify({ festivalRelPath, artists: spec.artists.map((a) => a.id), needsManualReview: { registryIdCollisions: skipped, linkMismatches: mismatched, unscoredPopularity: unscored } }, null, 2));
}

async function cmdAddArtists(festivalArgPath, specPath) {
  const spec = JSON.parse(await readFile(specPath, "utf8"));
  if (!spec.artists?.length) throw new Error("spec.artists must be a non-empty array");

  const festivalPath = path.resolve(REPO_ROOT, festivalArgPath);
  const folder = path.dirname(festivalPath);
  const festival = JSON.parse(await readFile(festivalPath, "utf8"));

  const existingIds = new Set(festival.artists.map((a) => a.id));
  for (const a of spec.artists) {
    if (existingIds.has(a.id)) throw new Error(`Artist id "${a.id}" already exists in ${festivalArgPath} -- pick a new local id`);
  }

  console.log(`Downloading ${spec.artists.length} artist image(s)...`);
  await downloadArtistImages(spec.artists, folder);

  festival.artists.push(...spec.artists.map(artistFromSpec));
  if (spec.runningOrderExists !== undefined) festival.runningOrderExists = spec.runningOrderExists;
  festival.version = (festival.version || 1) + 1;
  const merged = mergeTranslations(festival.translations, spec.translations);
  if (merged) festival.translations = merged;

  const festivalRelPath = path.relative(REPO_ROOT, festivalPath).split(path.sep).join("/");
  await writeJson(festivalPath, festival);
  console.log(`Updated ${festivalRelPath}`);

  const { skipped, mismatched, unscored } = await runPipeline(festivalRelPath, spec.artists.map((a) => a.id));

  console.log("\nDone.");
  console.log(JSON.stringify({ festivalRelPath, newArtists: spec.artists.map((a) => a.id), needsManualReview: { registryIdCollisions: skipped, linkMismatches: mismatched, unscoredPopularity: unscored } }, null, 2));
}

async function main() {
  const [mode, ...args] = process.argv.slice(2);
  if (mode === "create" && args.length === 1) {
    await cmdCreate(args[0]);
  } else if (mode === "add-artists" && args.length === 2) {
    await cmdAddArtists(args[0], args[1]);
  } else {
    console.error("Usage:\n  node scripts/scaffold-festival.mjs create <spec.json>\n  node scripts/scaffold-festival.mjs add-artists <festival.json> <spec.json>");
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
