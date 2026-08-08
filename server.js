// playlist-server/server.js
// Node.js backend that scans your QNAP music library and serves the Playlist Manager HTML.
// Run via Docker (docker compose up) or directly with: node server.js

import express from 'express';
import cors from 'cors';
import { parseFile } from 'music-metadata';
import fs from 'fs/promises';
import path from 'path';
import { createReadStream } from 'fs';

const PORT      = process.env.PORT      || 3000;
const MUSIC_DIR = process.env.MUSIC_DIR || '/mnt/qnap';
const DATA_DIR  = process.env.DATA_DIR  || '/data';

const LIBRARY_FILE = path.join(DATA_DIR, 'library.json');
const AUDIO_EXTS   = new Set(['.mp3','.flac','.wav','.aac','.m4a','.ogg','.opus','.wma','.aiff','.alac']);

let library  = [];   // full indexed track array
let scanning = false;

// ── Startup: load cached library ─────────────────────────────────────────────
async function loadLibrary() {
  try {
    const raw = await fs.readFile(LIBRARY_FILE, 'utf8');
    library = JSON.parse(raw);
    console.log(`[startup] Loaded ${library.length} tracks from cache.`);
  } catch {
    library = [];
    console.log('[startup] No library cache — POST /api/scan to index your music folder.');
  }
}

async function saveLibrary() {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(LIBRARY_FILE, JSON.stringify(library));
}

// ── Recursive audio file walker ───────────────────────────────────────────────
async function* walkDir(dir) {
  let entries;
  try { entries = await fs.readdir(dir, { withFileTypes: true }); }
  catch (e) { console.warn(`[scan] Cannot read dir ${dir}: ${e.message}`); return; }

  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walkDir(full);
    } else if (AUDIO_EXTS.has(path.extname(entry.name).toLowerCase())) {
      yield full;
    }
  }
}

// ── Scan ──────────────────────────────────────────────────────────────────────
async function scanLibrary() {
  if (scanning) return;
  scanning = true;
  library  = [];
  let count = 0;

  console.log(`[scan] Starting scan of ${MUSIC_DIR} …`);

  for await (const filePath of walkDir(MUSIC_DIR)) {
    try {
      const meta = await parseFile(filePath, { skipCovers: true, duration: true });
      const c    = meta.common;
      const f    = meta.format;

      const durSec = Math.round(f.duration || 0);
      const durStr = durSec
        ? `${Math.floor(durSec / 60)}:${String(durSec % 60).padStart(2, '0')}`
        : '?';

      library.push({
        id:        `lib_${count}`,
        title:     c.title   || path.basename(filePath, path.extname(filePath)),
        artist:    (Array.isArray(c.artists) ? c.artists[0] : c.artist || c.albumartist || '').trim(),
        album:     c.album   || '',
        genre:     (Array.isArray(c.genre)   ? c.genre[0]   : c.genre  || '').trim(),
        duration:  durStr,
        bpm:       c.bpm     ? String(Math.round(c.bpm)) : '',
        key:       c.key     || '',
        file_path: filePath,
        source:    'library',
      });
      count++;
      if (count % 200 === 0) console.log(`[scan]   ${count} files scanned…`);
    } catch {
      // Skip files music-metadata can't parse
    }
  }

  await saveLibrary();
  scanning = false;
  console.log(`[scan] Done — ${library.length} tracks indexed.`);
}

// ── Suggestions scoring ───────────────────────────────────────────────────────
function score(track, artistSet, genreSet, keySet, bpmMin, bpmMax) {
  let s = 0;
  if (track.artist && artistSet.has(track.artist.toLowerCase())) s += 30;
  if (track.genre  && genreSet.has(track.genre.toLowerCase()))   s += 25;
  if (track.key    && keySet.has(track.key.toLowerCase()))        s += 15;
  const bpm = parseFloat(track.bpm);
  if (!isNaN(bpm) && bpmMin != null && bpm >= bpmMin && bpm <= bpmMax) s += 20;
  return s;
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();

// CORS: allow all origins (including file:// = null origin)
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: '10mb' }));

// Serve the Playlist Manager HTML at root
app.get('/', (req, res) => {
  res.sendFile(path.resolve('./PlaylistManager.html'));
});

// ── GET /api/health ───────────────────────────────────────────────────────────
app.get('/api/health', (req, res) => {
  res.json({
    status:    'ok',
    tracks:    library.length,
    scanning,
    music_dir: MUSIC_DIR,
  });
});

// ── POST /api/scan ────────────────────────────────────────────────────────────
// Triggers an async rescan; responds immediately so the HTML doesn't hang.
app.post('/api/scan', (req, res) => {
  if (scanning) {
    return res.json({ message: 'Scan already in progress — check /api/health' });
  }
  res.json({ message: `Scan started on ${MUSIC_DIR} — POST /api/health to poll progress` });
  scanLibrary(); // fire-and-forget
});

// ── GET /api/scan/status ──────────────────────────────────────────────────────
app.get('/api/scan/status', (req, res) => {
  res.json({ scanning, indexed: library.length });
});

// ── GET /api/suggestions ──────────────────────────────────────────────────────
// Query params:
//   artists  – comma-separated artist names
//   genres   – comma-separated genre names
//   keys     – comma-separated musical keys
//   bpm_min  – number
//   bpm_max  – number
//   exclude  – "title|artist" pairs joined by "||"
//   limit    – max results (default 25)
app.get('/api/suggestions', (req, res) => {
  const artists  = (req.query.artists || '').split(',').filter(Boolean);
  const genres   = (req.query.genres  || '').split(',').filter(Boolean);
  const keys     = (req.query.keys    || '').split(',').filter(Boolean);
  const bpmMin   = req.query.bpm_min != null ? parseFloat(req.query.bpm_min) : null;
  const bpmMax   = req.query.bpm_max != null ? parseFloat(req.query.bpm_max) : null;
  const limit    = Math.min(parseInt(req.query.limit || '25', 10), 100);

  const artistSet = new Set(artists.map(a => a.toLowerCase()));
  const genreSet  = new Set(genres.map(g => g.toLowerCase()));
  const keySet    = new Set(keys.map(k => k.toLowerCase()));

  // Build exclude set from "title|artist||title|artist||…"
  const excludeSet = new Set(
    (req.query.exclude || '').split('||').filter(Boolean).map(s => s.toLowerCase())
  );

  const results = library
    .filter(t => {
      const k = `${(t.title || '').toLowerCase()}|${(t.artist || '').toLowerCase()}`;
      return !excludeSet.has(k);
    })
    .map(t => ({ ...t, _score: score(t, artistSet, genreSet, keySet, bpmMin, bpmMax) }))
    .filter(t => t._score > 0)
    .sort((a, b) => b._score - a._score)
    .slice(0, limit);

  res.json({ results, total_library: library.length });
});

// ── GET /api/library ──────────────────────────────────────────────────────────
// Returns the full library (useful for debugging / browsing)
app.get('/api/library', (req, res) => {
  const q     = (req.query.q || '').toLowerCase();
  const limit = Math.min(parseInt(req.query.limit || '100', 10), 2000);
  const page  = Math.max(parseInt(req.query.page || '0', 10), 0);

  let results = library;
  if (q) {
    results = library.filter(t =>
      (t.title  || '').toLowerCase().includes(q) ||
      (t.artist || '').toLowerCase().includes(q) ||
      (t.album  || '').toLowerCase().includes(q)
    );
  }

  res.json({
    total:   results.length,
    page,
    limit,
    results: results.slice(page * limit, page * limit + limit),
  });
});

// ── POST /api/tracks/sync ─────────────────────────────────────────────────────
// The HTML pushes its current playlist here (Settings → Push Playlist to Library)
app.post('/api/tracks/sync', async (req, res) => {
  const { tracks: incoming, playlist_tag } = req.body || {};
  if (!Array.isArray(incoming)) return res.status(400).json({ error: 'Expected { tracks: [] }' });

  const tag  = playlist_tag || `playlist_${Date.now()}`;
  const file = path.join(DATA_DIR, `${tag}.json`);

  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(file, JSON.stringify({
    synced: new Date().toISOString(),
    count:  incoming.length,
    tracks: incoming,
  }, null, 2));

  console.log(`[sync] Saved ${incoming.length} tracks → ${file}`);
  res.json({ synced: incoming.length, saved_as: tag });
});

// ── Boot ──────────────────────────────────────────────────────────────────────
loadLibrary().then(() => {
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`\nPlaylist Server is running:`);
    console.log(`  UI  →  http://0.0.0.0:${PORT}/`);
    console.log(`  API →  http://0.0.0.0:${PORT}/api/health`);
    console.log(`  Music: ${MUSIC_DIR}  |  Data: ${DATA_DIR}`);
    console.log(`\nTo index your library, POST to /api/scan or click "Scan Music Folder" in Settings.\n`);
  });
});
