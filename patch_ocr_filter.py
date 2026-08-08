#!/usr/bin/env python3
"""
patch_ocr_filter.py  —  Adds smart OCR line filtering to PlaylistManager.html

Changes:
  1. Adds _filterOCRLines() — strips noise, detects numbered tracklists
  2. Modifies renderImgTextResults() to call it before displaying
  3. Shows a filter summary badge (e.g. "22 tracks found, 30 lines removed")

Run:
    python3 patch_ocr_filter.py /home/era/playlist-server/PlaylistManager.html
"""

import sys, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak3')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

if '_filterOCRLines' in html:
    print("Already patched — nothing to do."); sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Add _filterOCRLines before renderImgTextResults
# ─────────────────────────────────────────────────────────────────────────────

FILTER_FN = r'''
// ── OCR line filter: strips noise, extracts numbered tracklists ──────────────
function _filterOCRLines(rawText) {
  const NUMBERED = /^(\d{1,2})\s*[\.\)\:\-]\s*(.+)/;

  // Noise patterns: catalog codes, label text, addresses, copyright, etc.
  const NOISE = [
    /^\s*$/,                                          // blank
    /^.{1,4}$/,                                       // too short (< 5 chars)
    /^[\d\s\.\-\|]+$/,                                // pure numbers/punctuation
    /\b(Ltd|Plc|Inc|LLC|GmbH|Corp)\b/i,              // company suffixes
    /\b(Records|Music Group|Entertainment|Publishing)\b/i,
    /\b(Street|Avenue|Road|Lane|SW\d|SE\d|NW\d|NE\d|High Street)\b/i,
    /\b(London|Dublin|Eire|Barnes|Distributed|Distribution)\b/i,
    /\(p\)\s*\d{4}|\(c\)\s*\d{4}|©\s*\d{4}/i,       // copyright year
    /\bBMG\b|\bSony\b|\bEMI\b|\bWarner\b|\bUniversal\b/i,
    /Made in|Manufactured|Printed in|All rights/i,
    /Design\s*[-–:]/i,                                // "Design - spin"
    /^(TCD|STAC|CAT|REF|LC|UPC|EAN|ISRC)\s*\d/i,    // catalog IDs
    /^\d{10,}$/,                                      // barcode numbers
    /^[A-Z]{2,6}\s+\d{3,}$/,                         // "TCD 2695" style
    /Also available|See also|Visit us|www\.|http/i,
    /This compilation|This album|All tracks/i,
    /Telstar|Chrysalis|Parlophone|Island|Atlantic|Columbia|Elektra/i,
    /Prospect Studios/i,
  ];

  const isNoise = line => NOISE.some(p => p.test(line));

  const raw = rawText.split('\n').map(l => l.trim());

  // ── Strategy 1: numbered tracklist ────────────────────────────────────────
  // Collect ALL lines that look like "1. Song - Artist"
  const numbered = [];
  for (const line of raw) {
    const m = line.match(NUMBERED);
    if (m) {
      const trackNum  = parseInt(m[1], 10);
      const trackText = m[2].trim();
      if (trackText.length > 3 && !isNoise(trackText)) {
        numbered.push({ num: trackNum, text: trackText });
      }
    }
  }

  // If we found 5+ numbered entries, trust it as a tracklist
  if (numbered.length >= 5) {
    // Sort by track number, deduplicate
    const seen = new Set();
    const deduped = numbered
      .sort((a, b) => a.num - b.num)
      .filter(({ text }) => {
        const key = text.toLowerCase().replace(/\s+/g, ' ');
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    return {
      lines:    deduped.map(t => t.text),
      strategy: 'numbered',
      removed:  raw.length - deduped.length,
    };
  }

  // ── Strategy 2: heuristic noise filter ───────────────────────────────────
  // Keep lines that look like songs: has a dash separator OR reasonable length
  const SONG_LIKE = /\s[-–]\s/;   // "TITLE - ARTIST" or "TITLE – ARTIST"

  const filtered = raw.filter(line => {
    if (!line || line.length < 5) return false;
    if (isNoise(line)) return false;
    return true;
  });

  // If many lines have dash-separator pattern, further filter to only those
  const dashLines = filtered.filter(l => SONG_LIKE.test(l));
  if (dashLines.length >= 5 && dashLines.length >= filtered.length * 0.4) {
    return {
      lines:    dashLines,
      strategy: 'dash-separator',
      removed:  raw.length - dashLines.length,
    };
  }

  return {
    lines:    filtered,
    strategy: 'noise-filter',
    removed:  raw.length - filtered.length,
  };
}

'''

# Insert before renderImgTextResults
RENDER_ANCHOR = "function renderImgTextResults("
idx = html.find(RENDER_ANCHOR)
if idx == -1:
    print("❌ Cannot find renderImgTextResults — check HTML"); sys.exit(1)

html = html[:idx] + FILTER_FN + html[idx:]
print("✅ _filterOCRLines inserted")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Patch renderImgTextResults to call _filterOCRLines
#    Find the first line that sets textarea value in that function
# ─────────────────────────────────────────────────────────────────────────────

# After inserting, re-find renderImgTextResults
RENDER_START = html.find("function renderImgTextResults(")
if RENDER_START == -1:
    print("❌ Cannot re-find renderImgTextResults"); sys.exit(1)

# Find the opening brace body start
brace_pos = html.find('{', RENDER_START)
# Find end of function (next top-level function at same indent — look for \nfunction or \nasync function)
import re
fn_body_end = re.search(r'\n(async\s+)?function\s+\w+', html[brace_pos:])
fn_body = html[brace_pos: brace_pos + (fn_body_end.start() if fn_body_end else 3000)]

# We need to inject the filter call at the START of the function body,
# replacing/wrapping the first use of rawText
# Safest approach: prepend filter call and replace rawText references

OLD_SIG = "function renderImgTextResults(rawText)"
NEW_SIG_BODY = """function renderImgTextResults(rawText) {
  // ── Apply OCR filter ──────────────────────────────────────────────────────
  const _ocrFiltered  = _filterOCRLines(rawText);
  const _filteredText = _ocrFiltered.lines.join('\\n');
  const _removedCount = _ocrFiltered.removed;
  const _strategy     = _ocrFiltered.strategy;
  rawText = _filteredText;   // swap in cleaned text for rest of function
"""

# Only replace if signature matches exactly
if OLD_SIG + ' {' in html:
    html = html.replace(OLD_SIG + ' {', NEW_SIG_BODY, 1)
    print("✅ renderImgTextResults patched (variant A)")
elif OLD_SIG + '{' in html:
    html = html.replace(OLD_SIG + '{', NEW_SIG_BODY, 1)
    print("✅ renderImgTextResults patched (variant B)")
else:
    print("⚠️  Could not patch renderImgTextResults signature — add manually:\n"
          "  At top of function body, add:\n"
          "    const _ocrFiltered = _filterOCRLines(rawText);\n"
          "    rawText = _ocrFiltered.lines.join('\\n');")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Inject filter summary badge after the result-count span update
#    Look for where the track count is set and append badge render call
# ─────────────────────────────────────────────────────────────────────────────

COUNT_ANCHOR = "img-text-result-count"  # the span we know exists
# Find the first assignment to that element inside renderImgTextResults
# We'll inject a badge update right after the count line
COUNT_PATTERN = re.compile(
    r"(document\.getElementById\('img-text-result-count'\)\.textContent\s*=\s*[^;]+;)"
)
match = COUNT_PATTERN.search(html, RENDER_START)
if match:
    badge_code = (
        match.group(0) +
        "\n  // Show filter summary\n"
        "  (function(){\n"
        "    let badge = document.getElementById('ocr-filter-badge');\n"
        "    if (!badge) {\n"
        "      badge = document.createElement('div');\n"
        "      badge.id = 'ocr-filter-badge';\n"
        "      badge.style.cssText = 'font-size:11px;color:var(--muted);margin-top:4px;';\n"
        "      const cnt = document.getElementById('img-text-result-count');\n"
        "      if (cnt && cnt.parentNode) cnt.parentNode.insertBefore(badge, cnt.nextSibling);\n"
        "    }\n"
        "    if (_removedCount > 0) {\n"
        "      const strat = _strategy === 'numbered' ? 'numbered-list mode'\n"
        "                   : _strategy === 'dash-separator' ? 'title–artist mode'\n"
        "                   : 'noise filter';\n"
        "      badge.textContent = `🧹 ${_removedCount} non-track lines removed (${strat})`;\n"
        "      badge.style.display = '';\n"
        "    } else {\n"
        "      badge.style.display = 'none';\n"
        "    }\n"
        "  })();"
    )
    html = html[:match.start()] + badge_code + html[match.end():]
    print("✅ Filter summary badge injected")
else:
    print("⚠️  Could not find result-count line — badge not injected (non-critical)")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done — {TARGET} patched. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: smart tracklist filter strips noise lines' && git push && docker compose up -d --build")
