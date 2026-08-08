#!/usr/bin/env python3
"""
patch_itunes_lookup.py  —  Improves _itunesLookupWithCandidates
- Parses "TITLE - ARTIST" format automatically
- Multi-strategy search (title+artist, title only, full string)
- Wider candidate pool (10 results)
- Better scoring when artist is known

Run on server:
    python3 patch_itunes_lookup.py /home/era/playlist-server/PlaylistManager.html
"""

import sys, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak2')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ── Find the existing function ────────────────────────────────────────────────
START_MARKER = "// ── NEW: iTunes lookup that always returns candidates (even below match threshold) ──\nasync function _itunesLookupWithCandidates("
END_MARKER   = "// ── Renders corrections + needs-review panel below textarea ──────────────────"

start = html.find(START_MARKER)
end   = html.find(END_MARKER)

if start == -1 or end == -1 or end < start:
    print("❌ Could not locate _itunesLookupWithCandidates — has the OCR patch been applied?")
    sys.exit(1)

NEW_FN = r'''// ── NEW: iTunes lookup that always returns candidates (even below match threshold) ──
async function _itunesLookupWithCandidates(query, artistHint = '') {
  try {
    // Strip leading track number  e.g. "1. " / "22. " / "3) "
    const clean = query.replace(/^[\d]+[\.\):\-]?\s*/, '').trim();
    if (!clean) return { best: null, candidates: [] };

    // Auto-detect "TITLE - ARTIST" or "TITLE – ARTIST" format in the OCR line
    const dashMatch = clean.match(/^(.+?)\s+[-–]\s+(.+)$/);
    let parsedTitle  = clean;
    let parsedArtist = artistHint;

    if (dashMatch) {
      parsedTitle  = dashMatch[1].trim();
      parsedArtist = dashMatch[2].trim();
    }

    // ── Multi-strategy search ─────────────────────────────────────────────
    async function iTunesSearch(term) {
      const url = `https://itunes.apple.com/search?term=${encodeURIComponent(term)}&media=music&entity=song&limit=10`;
      const r = await fetch(url);
      const d = await r.json();
      return d.results || [];
    }

    let results = [];

    // Strategy 1: title + detected/hinted artist (most specific)
    if (parsedArtist) {
      results = await iTunesSearch(`${parsedTitle} ${parsedArtist}`);
    }

    // Strategy 2: title alone if strategy 1 gave nothing
    if (!results.length) {
      results = await iTunesSearch(parsedTitle);
    }

    // Strategy 3: full original string as fallback
    if (!results.length && parsedArtist) {
      results = await iTunesSearch(clean);
    }

    if (!results.length) return { best: null, candidates: [] };

    // ── Score each result ─────────────────────────────────────────────────
    const scored = results.map(t => {
      const titleSim  = _strSim(_normStr(parsedTitle),  _normStr(t.trackName  || ''));
      const artistSim = parsedArtist
        ? _strSim(_normStr(parsedArtist), _normStr(t.artistName || ''))
        : 0;
      // Weighted: title is primary signal, artist is strong secondary
      const score = titleSim * 0.6 + artistSim * 0.4;
      return { t, score, titleSim, artistSim };
    }).sort((a, b) => b.score - a.score);

    const top = scored[0];
    // Accept best if title similarity is reasonable OR both title+artist are decent
    const isGoodMatch = top.titleSim >= 0.35 || (top.titleSim >= 0.25 && top.artistSim >= 0.5);
    const best = isGoodMatch
      ? { title: top.t.trackName, artist: top.t.artistName, album: top.t.collectionName || '' }
      : null;

    const candidates = scored.slice(0, 3).map(s => ({
      title:  s.t.trackName,
      artist: s.t.artistName,
      album:  s.t.collectionName || '',
      pct:    Math.round(s.score * 100),
    }));

    return { best, candidates };
  } catch(e) {
    return { best: null, candidates: [] };
  }
}

'''

html = html[:start] + NEW_FN + html[end:]
TARGET.write_text(html, encoding='utf-8')
print("✅ _itunesLookupWithCandidates updated")
print(f"\n✅ Done — {TARGET} patched. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: smarter title-artist parsing + wider iTunes search' && git push && docker compose up -d --build")
