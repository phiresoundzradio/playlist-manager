#!/usr/bin/env python3
"""
patch_clear_fix2.py  —  Fixes the clear→rescan flow (robust version)
"""
import sys, re, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')
if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak5')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ─────────────────────────────────────────────────────────────────────────────
# 1. Replace clearImageScan body using regex (avoids unicode/whitespace issues)
# ─────────────────────────────────────────────────────────────────────────────
# Find function start
fn_start = html.find('function clearImageScan()')
if fn_start == -1:
    print("❌ clearImageScan not found at all — is patch_clear_and_hint.py applied?")
    sys.exit(1)

# Find the opening brace
brace_open = html.find('{', fn_start)

# Walk forward to find the matching closing brace
depth = 0
i = brace_open
while i < len(html):
    if html[i] == '{':
        depth += 1
    elif html[i] == '}':
        depth -= 1
        if depth == 0:
            brace_close = i
            break
    i += 1

OLD_BODY = html[fn_start : brace_close + 1]

NEW_BODY = r"""function clearImageScan() {
  // Reset JS state
  _verifyResults = [];
  _imgTextTracks = [];
  if (typeof _imgAlbumTracks !== 'undefined') _imgAlbumTracks = [];

  // Clear textarea
  const ta = document.getElementById('img-ocr-edit');
  if (ta) ta.value = '';

  // Remove suggestion/filter panels
  ['verify-corrections-summary','ocr-filter-badge'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });

  // Reset result count
  const cnt = document.getElementById('img-text-result-count');
  if (cnt) cnt.textContent = '';

  // Reset verify status + button
  const status = document.getElementById('itunes-verify-status');
  if (status) { status.textContent = ''; status.style.display = 'none'; }
  const btn = document.getElementById('itunes-verify-btn');
  if (btn) { btn.disabled = false; btn.textContent = 'Verify via iTunes'; }

  // Hide result wrapper — runImageOCR + renderImgTextResults will un-hide it on next scan
  ['img-text-result','img-ocr-result'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.style.display = 'none'; el._clearedByReset = true; }
  });

  // Clear artist hint
  const hint = document.getElementById('img-artist-hint');
  if (hint) hint.value = '';

  toast('Cleared — drop a new image or click Scan', 'success');
}"""

html = html[:fn_start] + NEW_BODY + html[brace_close + 1:]
print("✅ clearImageScan() replaced")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Patch renderImgTextResults to un-hide result container on every call
# ─────────────────────────────────────────────────────────────────────────────
UNHIDE_CODE = (
    "  // Un-hide result wrapper in case it was cleared\n"
    "  ['img-text-result','img-ocr-result'].forEach(function(id){\n"
    "    var el = document.getElementById(id);\n"
    "    if (el) { el.style.display = ''; delete el._clearedByReset; }\n"
    "  });\n"
)

FILTER_INJECT = "  // ── Apply OCR filter"
if FILTER_INJECT in html:
    html = html.replace(FILTER_INJECT, UNHIDE_CODE + FILTER_INJECT, 1)
    print("✅ renderImgTextResults: un-hide injected before OCR filter block")
else:
    # Fallback: inject at top of renderImgTextResults body
    fn2 = html.find('function renderImgTextResults(')
    if fn2 != -1:
        b2 = html.find('{', fn2)
        html = html[:b2+1] + '\n' + UNHIDE_CODE + html[b2+1:]
        print("✅ renderImgTextResults: un-hide injected (fallback)")
    else:
        print("⚠️  renderImgTextResults not found — add un-hide manually")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Patch runImageOCR to un-hide result container when scan starts
# ─────────────────────────────────────────────────────────────────────────────
fn3 = html.find('async function runImageOCR(')
if fn3 != -1:
    b3 = html.find('{', fn3)
    # Check we haven't already added it (from a previous run)
    snippet_after = html[b3:b3+300]
    if 'img-text-result' not in snippet_after:
        UNHIDE_SCAN = (
            "{\n"
            "  // Un-hide result wrapper if cleared\n"
            "  ['img-text-result','img-ocr-result'].forEach(function(id){\n"
            "    var el = document.getElementById(id);\n"
            "    if (el) el.style.display = '';\n"
            "  });\n"
        )
        html = html[:b3] + UNHIDE_SCAN + html[b3+1:]
        print("✅ runImageOCR: un-hide injected")
    else:
        print("ℹ️  runImageOCR already has un-hide — skipping")
else:
    print("⚠️  runImageOCR not found — skipping")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done — {TARGET} updated. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: fix clear->rescan flow' && git push && docker compose up -d --build")
