#!/usr/bin/env python3
"""
patch_clear_fix.py

Fixes clearImageScan() so the full scan → verify → import flow works
after clearing:
  - Stops hiding the result wrapper (renderImgTextResults shows it on next scan)
  - Resets all internal track state arrays
  - Ensures renderImgTextResults() always un-hides its container
  - Removes the file-input reset (causes browser quirks)

Run:
    python3 patch_clear_fix.py /home/era/playlist-server/PlaylistManager.html
"""

import sys, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')
if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak5')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ─────────────────────────────────────────────────────────────────────────────
# 1. Replace entire clearImageScan function with fixed version
# ─────────────────────────────────────────────────────────────────────────────
OLD_CLEAR = "// ── Clear image scan and reset to start fresh ────────────────────────────────\nfunction clearImageScan() {"
END_MARKER = "\n// ── OCR line filter:"   # function that follows

start = html.find(OLD_CLEAR)
end   = html.find(END_MARKER, start)

if start == -1 or end == -1:
    print("❌ Cannot find clearImageScan — is patch_clear_and_hint.py applied?")
    sys.exit(1)

NEW_CLEAR = r'''// ── Clear image scan and reset to start fresh ────────────────────────────────
function clearImageScan() {
  // Reset JS state
  _verifyResults   = [];
  _imgTextTracks   = [];
  if (typeof _imgAlbumTracks !== 'undefined') _imgAlbumTracks = [];

  // Clear textarea content (don't hide the wrapper — renderImgTextResults re-uses it)
  const ta = document.getElementById('img-ocr-edit');
  if (ta) ta.value = '';

  // Remove suggestion panel
  const summary = document.getElementById('verify-corrections-summary');
  if (summary) summary.remove();

  // Remove filter badge
  const badge = document.getElementById('ocr-filter-badge');
  if (badge) badge.remove();

  // Reset result count text
  const cnt = document.getElementById('img-text-result-count');
  if (cnt) cnt.textContent = '';

  // Reset verify status + button
  const status = document.getElementById('itunes-verify-status');
  if (status) { status.textContent = ''; status.style.display = 'none'; }
  const btn = document.getElementById('itunes-verify-btn');
  if (btn) { btn.disabled = false; btn.textContent = 'Verify via iTunes'; }

  // Hide the RESULT AREA but NOT the scan trigger area
  // We blank it out rather than display:none so the next scan can re-populate
  const resultWrap = document.getElementById('img-text-result') ||
                     document.getElementById('img-ocr-result');
  if (resultWrap) {
    // Clear inner content, keep wrapper visible so it re-populates on next scan
    // But hide it until there's something to show
    resultWrap.style.display = 'none';
    resultWrap._clearedByReset = true;   // flag so renderImgTextResults can re-show it
  }

  // Clear artist hint
  const hint = document.getElementById('img-artist-hint');
  if (hint) hint.value = '';

  // DO NOT reset file input — causes browser quirks; user simply picks a new file

  toast('Cleared — drop a new image or click Scan', 'success');
}

'''

html = html[:start] + NEW_CLEAR + html[end:]
print("✅ clearImageScan() replaced")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Patch renderImgTextResults to always un-hide its container
# ─────────────────────────────────────────────────────────────────────────────
# Find the filter injection we added earlier
FILTER_INJECT = "  // ── Apply OCR filter ──────────────────────────────────────────────────────\n  const _ocrFiltered"

if FILTER_INJECT in html:
    UNHIDE_CODE = (
        "  // ── Apply OCR filter ──────────────────────────────────────────────────────\n"
        "  // Re-show result wrapper if it was hidden by clearImageScan()\n"
        "  (function(){\n"
        "    const w = document.getElementById('img-text-result') ||\n"
        "              document.getElementById('img-ocr-result');\n"
        "    if (w) { w.style.display = ''; delete w._clearedByReset; }\n"
        "  })();\n"
        "  const _ocrFiltered"
    )
    html = html.replace(FILTER_INJECT, UNHIDE_CODE, 1)
    print("✅ renderImgTextResults now re-shows container on each call")
else:
    # Fallback: find the function and inject at top
    RENDER_FN = "function renderImgTextResults(rawText) {"
    idx = html.find(RENDER_FN)
    if idx != -1:
        brace = html.find('{', idx)
        UNHIDE = (
            "{\n"
            "  // Re-show result wrapper if cleared\n"
            "  (function(){\n"
            "    const w = document.getElementById('img-text-result') ||\n"
            "              document.getElementById('img-ocr-result');\n"
            "    if (w && w._clearedByReset) { w.style.display = ''; delete w._clearedByReset; }\n"
            "  })();\n"
        )
        html = html[:brace] + UNHIDE + html[brace+1:]
        print("✅ renderImgTextResults patched (fallback method)")
    else:
        print("⚠️  Could not patch renderImgTextResults — add unhide logic manually")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Also patch runImageOCR (the scan function) to un-hide the result area
#    in case renderImgTextResults isn't what shows it
# ─────────────────────────────────────────────────────────────────────────────
# Find runImageOCR and inject an unhide at the very start
RUN_OCR_FN = "async function runImageOCR("
idx = html.find(RUN_OCR_FN)
if idx != -1:
    brace = html.find('{', idx)
    UNHIDE_SCAN = (
        "{\n"
        "  // Un-hide result wrapper in case it was cleared\n"
        "  ['img-text-result','img-ocr-result'].forEach(id => {\n"
        "    const el = document.getElementById(id);\n"
        "    if (el) el.style.display = '';\n"
        "  });\n"
    )
    html = html[:brace] + UNHIDE_SCAN + html[brace+1:]
    print("✅ runImageOCR also un-hides result container on scan start")
else:
    print("⚠️  runImageOCR not found — skipping (non-critical)")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done — {TARGET} patched. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: fix clear→rescan flow' && git push && docker compose up -d --build")
