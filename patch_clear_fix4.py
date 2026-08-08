#!/usr/bin/env python3
"""
patch_clear_fix4.py

Comprehensive fix for the image import flow:

1. After scan completes → hide img-preview-text, show img-text-results only
2. clearImageScan() → hide both img-preview-text + img-text-results, show drop zone
3. Override clearImgPreview('text') to also reset state so Try Another works cleanly

Known element IDs (confirmed from HTML):
  img-preview-text     — image preview + scan button wrapper
  img-text-results     — track list + Import/Verify/Clear/Try Another buttons
  img-drop-text        — the drop zone (guessed; grep will verify)
  img-file-text        — file input
  img-ocr-btn-text     — scan button
"""
import sys, shutil, re
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')
if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak7')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ── Find the drop zone ID by scanning the HTML ────────────────────────────────
dz_match = re.search(r'id="(img-drop[^"]*text[^"]*|img-drop-text[^"]*)"', html)
DROP_ID = dz_match.group(1) if dz_match else 'img-drop-text'
print(f"ℹ️  Drop zone ID detected: {DROP_ID}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Replace clearImageScan with version that fully resets the UI
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

NEW_CLEAR = f"""function clearImageScan() {{
  // Reset JS state
  _verifyResults = [];
  _imgTextTracks = [];
  if (typeof _imgAlbumTracks !== 'undefined') _imgAlbumTracks = [];

  // Remove suggestion/filter panels
  ['verify-corrections-summary', 'ocr-filter-badge'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.remove();
  }});

  // Clear result content
  const cnt = document.getElementById('img-text-result-count');
  if (cnt) cnt.textContent = '';
  const list = document.getElementById('img-text-result-list');
  if (list) list.innerHTML = '';

  // Reset verify status + button
  const status = document.getElementById('itunes-verify-status');
  if (status) {{ status.textContent = ''; status.style.display = 'none'; }}
  const btn = document.getElementById('itunes-verify-btn');
  if (btn) {{ btn.disabled = false; btn.textContent = 'Verify Song Names'; }}

  // ── UI: hide results + preview, show drop zone ───────────────────────────
  const wrap = document.getElementById('img-text-results');
  if (wrap) wrap.style.display = 'none';

  const preview = document.getElementById('img-preview-text');
  if (preview) preview.style.display = 'none';

  // Show the drop zone so the user can load a new image
  const dropZone = document.getElementById('{DROP_ID}');
  if (dropZone) dropZone.style.display = '';

  // Clear the file input so the same file can be re-selected
  const fileIn = document.getElementById('img-file-text');
  if (fileIn) fileIn.value = '';

  // Also clear the preview image src
  const prevImg = document.getElementById('img-preview-img-text');
  if (prevImg) prevImg.src = '';

  // Clear artist hint
  const hint = document.getElementById('img-artist-hint');
  if (hint) hint.value = '';

  toast('Cleared — drop a new image or click to browse', 'success');
}}"""

html = html[:fn_start] + NEW_CLEAR + html[brace_close + 1:]
print("✅ clearImageScan() fully rewritten")

# ─────────────────────────────────────────────────────────────────────────────
# 2. After scan completes, hide the image preview + show results
#    Patch renderImgTextResults to swap preview→results
# ─────────────────────────────────────────────────────────────────────────────
WRAP_LINE = "  const wrap = document.getElementById('img-text-results');"
if WRAP_LINE in html:
    SHOW_RESULTS = (
        f"  const wrap = document.getElementById('img-text-results');\n"
        f"  if (wrap) wrap.style.display = '';  // show results\n"
        f"  // Hide image preview now that scan is done — keeps UI clean\n"
        f"  const _prev = document.getElementById('img-preview-text');\n"
        f"  if (_prev) _prev.style.display = 'none';\n"
        f"  // Also hide the drop zone\n"
        f"  const _dz = document.getElementById('{DROP_ID}');\n"
        f"  if (_dz) _dz.style.display = 'none';\n"
    )
    # Only replace the first occurrence (inside renderImgTextResults)
    html = html.replace(WRAP_LINE, SHOW_RESULTS, 1)
    print("✅ renderImgTextResults now hides preview + shows results after scan")
else:
    print("⚠️  Could not find wrap line in renderImgTextResults")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Hook clearImgPreview so "Try Another" also resets state + shows drop zone
#    Find the function and append our reset logic
# ─────────────────────────────────────────────────────────────────────────────
fn_cp = html.find('function clearImgPreview(')
if fn_cp != -1:
    b_open = html.find('{', fn_cp)
    depth2, j = 0, b_open
    while j < len(html):
        if html[j] == '{': depth2 += 1
        elif html[j] == '}':
            depth2 -= 1
            if depth2 == 0: b_close2 = j; break
        j += 1

    existing_body = html[b_open+1:b_close2]

    EXTRA = f"""
  // ── Extra reset when mode is 'text' ──────────────────────────────────────
  if (mode === 'text') {{
    // Reset state arrays
    _verifyResults = [];
    _imgTextTracks = [];

    // Hide results panel so drop zone is shown cleanly
    const _wrap = document.getElementById('img-text-results');
    if (_wrap) _wrap.style.display = 'none';

    // Clear result content
    const _cnt = document.getElementById('img-text-result-count');
    if (_cnt) _cnt.textContent = '';
    const _list = document.getElementById('img-text-result-list');
    if (_list) _list.innerHTML = '';

    // Remove suggestion/filter panels
    ['verify-corrections-summary','ocr-filter-badge'].forEach(function(id){{
      var el = document.getElementById(id); if(el) el.remove();
    }});

    // Show drop zone
    const _dz = document.getElementById('{DROP_ID}');
    if (_dz) _dz.style.display = '';
  }}
"""
    new_body = '{' + existing_body + EXTRA + '}'
    html = html[:b_open] + new_body + html[b_close2+1:]
    print("✅ clearImgPreview('text') now resets state + shows drop zone")
else:
    print("⚠️  clearImgPreview not found — Try Another reset not applied")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: fix image preview/results flow for rescan' && git push && docker compose up -d --build")
