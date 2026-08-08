#!/usr/bin/env python3
"""
patch_clear_fix3.py

Fixes wrong element IDs in all previous patches.
Real wrapper: img-text-results  (with trailing 's')
Previous patches targeted: img-text-result / img-ocr-result  (neither exists)

Also ensures renderImgTextResults explicitly sets display:'' on img-text-results.
"""
import sys, shutil, re
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')
if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak6')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ─────────────────────────────────────────────────────────────────────────────
# 1. Replace clearImageScan with corrected version
# ─────────────────────────────────────────────────────────────────────────────
fn_start = html.find('function clearImageScan()')
if fn_start == -1:
    print("❌ clearImageScan not found"); sys.exit(1)

brace_open = html.find('{', fn_start)
depth, i = 0, brace_open
while i < len(html):
    if html[i] == '{': depth += 1
    elif html[i] == '}':
        depth -= 1
        if depth == 0: brace_close = i; break
    i += 1

NEW_CLEAR = r"""function clearImageScan() {
  // Reset JS state
  _verifyResults = [];
  _imgTextTracks = [];
  if (typeof _imgAlbumTracks !== 'undefined') _imgAlbumTracks = [];

  // Clear textarea
  const ta = document.getElementById('img-ocr-edit');
  if (ta) ta.value = '';

  // Remove suggestion/filter panels
  ['verify-corrections-summary', 'ocr-filter-badge'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });

  // Reset result count + track list
  const cnt = document.getElementById('img-text-result-count');
  if (cnt) cnt.textContent = '';
  const list = document.getElementById('img-text-result-list');
  if (list) list.innerHTML = '';

  // Reset verify status + button
  const status = document.getElementById('itunes-verify-status');
  if (status) { status.textContent = ''; status.style.display = 'none'; }
  const btn = document.getElementById('itunes-verify-btn');
  if (btn) { btn.disabled = false; btn.textContent = 'Verify via iTunes'; }

  // Hide the result wrapper (CORRECT ID: img-text-results)
  const wrap = document.getElementById('img-text-results');
  if (wrap) wrap.style.display = 'none';

  // Clear artist hint
  const hint = document.getElementById('img-artist-hint');
  if (hint) hint.value = '';

  toast('Cleared — drop a new image or click Scan', 'success');
}"""

html = html[:fn_start] + NEW_CLEAR + html[brace_close + 1:]
print("✅ clearImageScan() fixed with correct ID: img-text-results")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Fix runImageOCR — replace wrong IDs in the un-hide block we inserted
# ─────────────────────────────────────────────────────────────────────────────
OLD_UNHIDE_SCAN = (
    "  // Un-hide result wrapper if cleared\n"
    "  ['img-text-result','img-ocr-result'].forEach(function(id){\n"
    "    var el = document.getElementById(id);\n"
    "    if (el) el.style.display = '';\n"
    "  });\n"
)
NEW_UNHIDE_SCAN = (
    "  // Un-hide result wrapper if cleared\n"
    "  const _wrap = document.getElementById('img-text-results');\n"
    "  if (_wrap) _wrap.style.display = '';\n"
)
if OLD_UNHIDE_SCAN in html:
    html = html.replace(OLD_UNHIDE_SCAN, NEW_UNHIDE_SCAN, 1)
    print("✅ runImageOCR un-hide fixed")
else:
    # Inject fresh at start of runImageOCR body
    fn3 = html.find('async function runImageOCR(')
    if fn3 != -1:
        b3 = html.find('{', fn3)
        snippet = html[b3:b3+200]
        if 'img-text-results' not in snippet:
            html = html[:b3+1] + "\n  const _wrap = document.getElementById('img-text-results'); if(_wrap) _wrap.style.display='';\n" + html[b3+1:]
            print("✅ runImageOCR un-hide injected fresh")
        else:
            print("ℹ️  runImageOCR already has correct un-hide")
    else:
        print("⚠️  runImageOCR not found")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Fix renderImgTextResults — replace wrong IDs + ensure wrap is shown
# ─────────────────────────────────────────────────────────────────────────────
# Remove the bad un-hide blocks that target wrong IDs
BAD_UNHIDE1 = (
    "  // Un-hide result wrapper in case it was cleared\n"
    "  ['img-text-result','img-ocr-result'].forEach(function(id){\n"
    "    var el = document.getElementById(id);\n"
    "    if (el) { el.style.display = ''; delete el._clearedByReset; }\n"
    "  });\n"
)
if BAD_UNHIDE1 in html:
    html = html.replace(BAD_UNHIDE1, '', 1)
    print("✅ Removed bad un-hide block from renderImgTextResults")

BAD_UNHIDE2 = (
    "  // Un-hide result wrapper in case it was cleared\n"
    "  ['img-text-result','img-ocr-result'].forEach(function(id){\n"
    "    var el = document.getElementById(id);\n"
    "    if (el) { el.style.display = ''; }\n"
    "  });\n"
)
if BAD_UNHIDE2 in html:
    html = html.replace(BAD_UNHIDE2, '', 1)
    print("✅ Removed second bad un-hide block")

# Now ensure renderImgTextResults shows img-text-results before populating it
# Find the line:  const wrap = document.getElementById('img-text-results');
WRAP_LINE = "  const wrap = document.getElementById('img-text-results');"
if WRAP_LINE in html:
    html = html.replace(
        WRAP_LINE,
        WRAP_LINE + "\n  if (wrap) wrap.style.display = '';  // always show on scan",
        1
    )
    print("✅ renderImgTextResults now shows img-text-results on every call")
else:
    print("⚠️  Could not find wrap line in renderImgTextResults")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: fix correct element ID img-text-results' && git push && docker compose up -d --build")
