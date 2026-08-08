#!/usr/bin/env python3
"""
patch_clear_and_hint.py

Adds two features to the image OCR flow:
  1. Clear / Start Over button — resets everything so a new image can be scanned
  2. Artist Hint field — e.g. "Drake" so every track is searched as Drake + title
                         also handles "featured on" so Drake albums with features work

Run:
    python3 patch_clear_and_hint.py /home/era/playlist-server/PlaylistManager.html
"""

import sys, re, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')
if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

backup = TARGET.with_suffix('.html.bak4')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

if 'clearImageScan' in html:
    print("Already patched — nothing to do."); sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Add clearImageScan() JS function (before verifyOCRLines)
# ─────────────────────────────────────────────────────────────────────────────
CLEAR_FN = r'''
// ── Clear image scan and reset to start fresh ────────────────────────────────
function clearImageScan() {
  // Reset state
  _verifyResults = [];

  // Clear textarea
  const ta = document.getElementById('img-ocr-edit');
  if (ta) ta.value = '';

  // Remove suggestion panel
  const summary = document.getElementById('verify-corrections-summary');
  if (summary) summary.remove();

  // Remove filter badge
  const badge = document.getElementById('ocr-filter-badge');
  if (badge) badge.remove();

  // Reset result count
  const cnt = document.getElementById('img-text-result-count');
  if (cnt) cnt.textContent = '';

  // Reset verify status
  const status = document.getElementById('itunes-verify-status');
  if (status) { status.textContent = ''; status.style.display = 'none'; }

  // Reset verify button
  const btn = document.getElementById('itunes-verify-btn');
  if (btn) { btn.disabled = false; btn.textContent = 'Verify via iTunes'; }

  // Clear file input so same image can be re-selected
  const fileIn = document.getElementById('img-upload-input') ||
                 document.querySelector('input[type="file"][accept*="image"]');
  if (fileIn) fileIn.value = '';

  // Hide OCR result section if it has a wrapper
  const resultWrap = document.getElementById('img-text-result') ||
                     document.getElementById('img-ocr-result');
  if (resultWrap) resultWrap.style.display = 'none';

  // Clear artist hint
  const hint = document.getElementById('img-artist-hint');
  if (hint) hint.value = '';

  toast('Cleared — ready to scan a new image', 'success');
}

'''

# Insert before verifyOCRLines
ANCHOR = "async function verifyOCRLines() {"
idx = html.find(ANCHOR)
if idx == -1:
    print("❌ Cannot find verifyOCRLines — apply the OCR suggestion patch first")
    sys.exit(1)

html = html[:idx] + CLEAR_FN + html[idx:]
print("✅ clearImageScan() added")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Add artist hint input if not present
# ─────────────────────────────────────────────────────────────────────────────
if 'img-artist-hint' not in html:
    # Find the verify button in the HTML and insert the hint field above it
    VERIFY_BTN_PATTERNS = [
        'id="itunes-verify-btn"',
        "id='itunes-verify-btn'",
    ]
    vbtn_idx = -1
    for pat in VERIFY_BTN_PATTERNS:
        vbtn_idx = html.find(pat)
        if vbtn_idx != -1:
            break

    if vbtn_idx != -1:
        # Walk back to the opening < of the button tag
        tag_start = html.rfind('<', 0, vbtn_idx)
        HINT_HTML = (
            '<div style="margin-bottom:8px;">'
            '<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px;">'
            '🎤 Main artist / hint <span style="opacity:.6;">(optional — e.g. "Drake", "Bob Marley")</span>'
            '</label>'
            '<input id="img-artist-hint" type="text" '
            'placeholder="Artist name — leave blank for mixed-artist tracklists" '
            'style="width:100%;background:var(--surface3);border:1px solid var(--border);'
            'border-radius:5px;color:var(--text);padding:5px 9px;font-size:12px;'
            'font-family:inherit;outline:none;box-sizing:border-box;" '
            'onfocus="this.style.borderColor=\'var(--accent2)\'" '
            'onblur="this.style.borderColor=\'var(--border)\'" />'
            '</div>\n'
        )
        html = html[:tag_start] + HINT_HTML + html[tag_start:]
        print("✅ Artist hint input inserted above verify button")
    else:
        print("⚠️  Could not find verify button — artist hint input NOT inserted (add manually)")
else:
    print("ℹ️  img-artist-hint already exists — skipping")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Add Clear button next to (or after) the verify button in the HTML
# ─────────────────────────────────────────────────────────────────────────────
# After inserting hint, the verify button position has shifted — find it again
VERIFY_BTN_PATTERNS = ['id="itunes-verify-btn"', "id='itunes-verify-btn'"]
vbtn_idx = -1
for pat in VERIFY_BTN_PATTERNS:
    vbtn_idx = html.find(pat)
    if vbtn_idx != -1:
        break

if vbtn_idx != -1:
    # Find the END of the verify button's closing tag
    close_tag = html.find('>', vbtn_idx)
    # Check if it's a self-closing or has inner text — find </button>
    btn_close = html.find('</button>', close_tag)
    if btn_close != -1:
        insert_after = btn_close + len('</button>')
    else:
        insert_after = close_tag + 1

    CLEAR_BTN_HTML = (
        '\n<button onclick="clearImageScan()" '
        'title="Clear scan and start over" '
        'style="margin-left:8px;background:none;border:1px solid var(--border);'
        'color:var(--muted);border-radius:5px;padding:5px 12px;font-size:12px;'
        'cursor:pointer;font-family:inherit;transition:all .15s;" '
        'onmouseover="this.style.borderColor=\'var(--text)\';this.style.color=\'var(--text)\'" '
        'onmouseout="this.style.borderColor=\'var(--border)\';this.style.color=\'var(--muted)\'">✕ Clear</button>'
    )
    html = html[:insert_after] + CLEAR_BTN_HTML + html[insert_after:]
    print("✅ Clear button added next to verify button")
else:
    print("⚠️  Could not find verify button — Clear button NOT inserted")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Update _itunesLookupWithCandidates to weight artist hint more intelligently
#    when the OCR line already contains "artist" info vs when hint is separate
# ─────────────────────────────────────────────────────────────────────────────
# The existing function already handles artistHint — we just need to make sure
# when hint is provided AND the line has a dash (parsed artist detected),
# the hint AUGMENTS rather than replaces the parsed artist for better matching.
# This is handled by checking if parsedArtist ≈ artistHint; if they differ,
# we try both combinations.

OLD_SEARCH_BLOCK = "    // ── Multi-strategy search ─────────────────────────────────────────────\n    async function iTunesSearch(term) {"
NEW_SEARCH_BLOCK = """    // ── Multi-strategy search ─────────────────────────────────────────────
    // If a global artist hint is set but OCR line has its own artist,
    // prefer the OCR-parsed artist but also try the hint as fallback
    const globalHint = artistHint.trim();
    if (globalHint && !parsedArtist) {
      parsedArtist = globalHint;
    } else if (globalHint && parsedArtist &&
               _strSim(_normStr(globalHint), _normStr(parsedArtist)) < 0.4) {
      // OCR artist and hint are different — could be a feature ("ft. Artist")
      // Keep OCR artist as primary, note hint for fallback
    }

    async function iTunesSearch(term) {"""

if OLD_SEARCH_BLOCK in html:
    html = html.replace(OLD_SEARCH_BLOCK, NEW_SEARCH_BLOCK, 1)
    print("✅ Artist hint logic updated in _itunesLookupWithCandidates")
else:
    print("ℹ️  Multi-strategy block not found — hint logic unchanged (non-critical)")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Add fallback search using globalHint if parsedArtist didn't work
# ─────────────────────────────────────────────────────────────────────────────
OLD_STRAT3 = "    // Strategy 3: full original string as fallback\n    if (!results.length && parsedArtist) {"
NEW_STRAT3 = """    // Strategy 3: try with global artist hint if different from parsed
    if (!results.length && globalHint && globalHint !== parsedArtist) {
      results = await iTunesSearch(`${parsedTitle} ${globalHint}`);
    }

    // Strategy 4: full original string as final fallback
    if (!results.length && parsedArtist) {"""

if OLD_STRAT3 in html:
    html = html.replace(OLD_STRAT3, NEW_STRAT3, 1)
    print("✅ Global hint fallback strategy added")
else:
    print("ℹ️  Strategy 3 block not found — skipping (non-critical)")

# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done — {TARGET} patched. Backup at {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: clear button + artist hint field' && git push && docker compose up -d --build")
