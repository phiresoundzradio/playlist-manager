#!/usr/bin/env python3
"""
apply_patch.py  —  Phire Soundz OCR Suggestion Patch
Run on the Mac mini:
    python3 apply_patch.py /home/era/playlist-server/PlaylistManager.html
"""

import sys, re, shutil
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/era/playlist-server/PlaylistManager.html')

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found"); sys.exit(1)

# ── Backup ────────────────────────────────────────────────────────────────────
backup = TARGET.with_suffix('.html.bak')
shutil.copy2(TARGET, backup)
print(f"Backup → {backup}")

html = TARGET.read_text(encoding='utf-8')

# ── Guard: already patched? ───────────────────────────────────────────────────
if '_itunesLookupWithCandidates' in html:
    print("Already patched — nothing to do."); sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Add state variable (after `let _imgAlbumTracks  = [];`)
# ─────────────────────────────────────────────────────────────────────────────
STATE_ANCHOR = "let _imgAlbumTracks  = [];   // tracks fetched for selected album"
STATE_INSERT = "\nlet _verifyResults   = [];   // per-line results from verifyOCRLines"

if STATE_ANCHOR in html:
    html = html.replace(STATE_ANCHOR, STATE_ANCHOR + STATE_INSERT, 1)
    print("✅ State variable added")
else:
    # Fallback: insert after _imgTextTracks line
    alt = "let _imgTextTracks   = [];"
    if alt in html:
        html = html.replace(alt, alt + "\nlet _verifyResults   = [];", 1)
        print("✅ State variable added (fallback position)")
    else:
        print("⚠️  Could not find anchor for state variable — add manually")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Replace verifyOCRLines function
# ─────────────────────────────────────────────────────────────────────────────
OLD_FUNC_START = "async function verifyOCRLines() {"
OLD_FUNC_NEXT  = "async function _itunesLookup("   # function immediately after

# Find the slice to replace
start_idx = html.find(OLD_FUNC_START)
end_idx   = html.find(OLD_FUNC_NEXT)

if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
    print("❌ Could not locate verifyOCRLines — check the HTML manually"); sys.exit(1)

NEW_VERIFY = r'''async function verifyOCRLines() {
  const ta = document.getElementById('img-ocr-edit');
  if (!ta) return;
  const lines = ta.value.split('\n').map(l => l.trim()).filter(l => l.length > 1);
  if (!lines.length) return;

  const btn    = document.getElementById('itunes-verify-btn');
  const status = document.getElementById('itunes-verify-status');
  btn.disabled = true;
  btn.textContent = '⏳ Verifying…';
  status.style.display = '';

  const artistHint = (document.getElementById('img-artist-hint')?.value || '').trim();
  _verifyResults = [];
  const corrected = [];
  let fixed = 0, unmatched = 0;
  const BATCH = 5;

  for (let i = 0; i < lines.length; i += BATCH) {
    const batch = lines.slice(i, i + BATCH);
    const results = await Promise.all(
      batch.map(line => _itunesLookupWithCandidates(line, artistHint))
    );
    results.forEach(({ best, candidates }, j) => {
      const lineIdx = i + j;
      const original = batch[j];
      if (best) {
        const correctedLine = `${best.title} - ${best.artist}`;
        corrected.push(correctedLine);
        _verifyResults.push({ lineIdx, original, corrected: correctedLine, matched: true, candidates });
        fixed++;
      } else {
        corrected.push(original);
        _verifyResults.push({ lineIdx, original, corrected: original, matched: false, candidates });
        unmatched++;
      }
    });
    status.textContent = `Verified ${Math.min(i + BATCH, lines.length)} / ${lines.length}…`;
    if (i + BATCH < lines.length) await new Promise(r => setTimeout(r, 200));
  }

  ta.value = corrected.join('\n');
  renderVerifySummary(fixed, unmatched);

  status.textContent = unmatched
    ? `Done — ${fixed} auto-corrected, ${unmatched} need review below`
    : `Done — ${fixed} of ${lines.length} names corrected via iTunes`;
  btn.disabled = false;
  btn.textContent = '✓ Re-verify';
  document.getElementById('img-text-result-count').textContent =
    `${corrected.length} tracks — ${fixed} corrected${unmatched ? `, ${unmatched} need review` : ''}`;
  toast(
    unmatched ? `${fixed} corrected · ${unmatched} need manual review` : `${fixed} song names corrected`,
    'success'
  );
}

// ── NEW: iTunes lookup that always returns candidates (even below match threshold) ──
async function _itunesLookupWithCandidates(query, artistHint = '') {
  try {
    const clean = query.replace(/^[\d]+[\.\):\-]?\s*/, '').trim();
    if (!clean) return { best: null, candidates: [] };
    const searchTerm = artistHint ? `${clean} ${artistHint}` : clean;
    const url = `https://itunes.apple.com/search?term=${encodeURIComponent(searchTerm)}&media=music&entity=song&limit=5`;
    const r = await fetch(url);
    const data = await r.json();
    let results = data.results || [];
    if (!results.length && artistHint) {
      const r2 = await fetch(`https://itunes.apple.com/search?term=${encodeURIComponent(clean)}&media=music&entity=song&limit=5`);
      const d2 = await r2.json();
      results = d2.results || [];
    }
    if (!results.length) return { best: null, candidates: [] };
    const scored = results.map(t => {
      const titleSim  = _strSim(clean, t.trackName);
      const artistSim = artistHint ? _strSim(artistHint, t.artistName) * 0.3 : 0;
      return { t, score: titleSim + artistSim, titleSim };
    }).sort((a, b) => b.score - a.score);
    const top = scored[0];
    const best = top.titleSim >= 0.3 ? { title: top.t.trackName, artist: top.t.artistName, album: top.t.collectionName || '' } : null;
    const candidates = scored.slice(0, 3).map(s => ({
      title: s.t.trackName, artist: s.t.artistName, album: s.t.collectionName || '',
      pct: Math.round((s.titleSim + (artistHint ? _strSim(artistHint, s.t.artistName) * 0.3 : 0)) * 100),
    }));
    return { best, candidates };
  } catch(e) { return { best: null, candidates: [] }; }
}

// ── Renders corrections + needs-review panel below textarea ──────────────────
function renderVerifySummary(fixed, unmatched) {
  const existing = document.getElementById('verify-corrections-summary');
  if (existing) existing.remove();
  const summary = document.createElement('div');
  summary.id = 'verify-corrections-summary';
  summary.style.cssText = 'margin-top:10px;border:1px solid var(--border);border-radius:8px;overflow:hidden;';
  const corrections = _verifyResults.filter(r => r.matched);
  const needsReview = _verifyResults.filter(r => !r.matched);
  let html = '';
  if (corrections.length) {
    html += `<div style="padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);background:var(--surface2);">✅ ${corrections.length} auto-corrected</div>
      <div style="max-height:140px;overflow-y:auto;">
        ${corrections.map(c => `<div style="padding:5px 10px;font-size:11px;border-bottom:1px solid var(--border-subtle);"><div style="color:var(--muted);text-decoration:line-through">${esc(c.original)}</div><div style="color:var(--green);margin-top:1px">✓ ${esc(c.corrected)}</div></div>`).join('')}
      </div>`;
  }
  if (needsReview.length) {
    html += `<div style="padding:8px 10px;font-size:11px;font-weight:600;color:#fbbf24;background:rgba(245,158,11,.06);border-top:${corrections.length?'1px solid var(--border)':'none'};border-bottom:1px solid var(--border);">⚠️ ${needsReview.length} couldn't be matched — pick a suggestion or keep as typed</div>
      <div id="verify-suggestions-list">${needsReview.map(r => _renderVerifySuggestItem(r)).join('')}</div>`;
  }
  if (!corrections.length && !needsReview.length) html = '<div style="padding:10px;font-size:12px;color:var(--muted);">No results.</div>';
  summary.innerHTML = html;
  const ta = document.getElementById('img-ocr-edit');
  ta.parentNode.insertBefore(summary, ta.nextSibling);
}

// ── Renders one unmatched row with candidate buttons + manual search ──────────
function _renderVerifySuggestItem(r) {
  const candidates = r.candidates || [];
  const candidatesHtml = candidates.length
    ? `<div style="font-size:10px;color:var(--muted);margin:6px 0 5px;">iTunes suggestions — click to accept:</div>
       <div class="vsug-cands">
         ${candidates.map(c => `<button class="vsug-cand-btn" onclick="acceptVerifySuggestion(${r.lineIdx}, '${c.title.replace(/\\/g,'\\\\').replace(/'/g,"\\'")} - ${c.artist.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')"><span class="vsug-cand-title">${esc(c.title)}</span><span class="vsug-cand-artist"> — ${esc(c.artist)}</span><span class="vsug-cand-pct">${c.pct}%</span></button>`).join('')}
       </div>`
    : `<div style="font-size:11px;color:var(--muted);margin:6px 0;">No iTunes suggestions — try searching below.</div>`;
  return `<div class="vsug-item" id="vsitem-${r.lineIdx}">
    <div class="vsug-original"><span class="vsug-ocr-badge">OCR</span> ${esc(r.original)}</div>
    ${candidatesHtml}
    <div class="vsug-search-row">
      <input class="vsug-search-inp" id="vsearch-${r.lineIdx}" placeholder="Search iTunes manually…" onkeydown="if(event.key==='Enter')searchVerifyLine(${r.lineIdx})" />
      <button class="vsug-btn-search" onclick="searchVerifyLine(${r.lineIdx})">Search</button>
      <button class="vsug-btn-keep" onclick="keepVerifyLine(${r.lineIdx})">Keep</button>
    </div>
  </div>`;
}

// ── Accept a suggestion → update textarea + dismiss row ──────────────────────
function acceptVerifySuggestion(lineIdx, correctedLine) {
  const ta = document.getElementById('img-ocr-edit');
  const lines = ta.value.split('\n');
  if (lineIdx < lines.length) lines[lineIdx] = correctedLine;
  ta.value = lines.join('\n');
  const item = document.getElementById(`vsitem-${lineIdx}`);
  if (item) {
    item.innerHTML = `<div style="font-size:11px;color:var(--green);padding:2px 0;">✓ ${esc(correctedLine)}</div>`;
    setTimeout(() => { item.style.transition='opacity .3s'; item.style.opacity='0'; setTimeout(()=>item.remove(),300); }, 1000);
  }
  toast(`Accepted: ${correctedLine}`, 'success');
}

// ── Dismiss a row without changing the line ──────────────────────────────────
function keepVerifyLine(lineIdx) {
  const item = document.getElementById(`vsitem-${lineIdx}`);
  if (!item) return;
  item.style.transition = 'opacity .25s'; item.style.opacity = '0';
  setTimeout(() => item.remove(), 250);
}

// ── Manual search for a specific unmatched line ──────────────────────────────
async function searchVerifyLine(lineIdx) {
  const inp = document.getElementById(`vsearch-${lineIdx}`);
  if (!inp) return;
  const q = inp.value.trim();
  if (!q) { toast('Type something to search', 'error'); return; }
  inp.disabled = true;
  const artistHint = (document.getElementById('img-artist-hint')?.value || '').trim();
  const { best, candidates } = await _itunesLookupWithCandidates(q, artistHint);
  inp.disabled = false;
  if (best) { acceptVerifySuggestion(lineIdx, `${best.title} - ${best.artist}`); return; }
  const item = document.getElementById(`vsitem-${lineIdx}`);
  if (!item) return;
  if (candidates.length) {
    const newHtml = candidates.map(c => `<button class="vsug-cand-btn" onclick="acceptVerifySuggestion(${lineIdx}, '${c.title.replace(/\\/g,'\\\\').replace(/'/g,"\\'")} - ${c.artist.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')"><span class="vsug-cand-title">${esc(c.title)}</span><span class="vsug-cand-artist"> — ${esc(c.artist)}</span><span class="vsug-cand-pct">${c.pct}%</span></button>`).join('');
    let candsDiv = item.querySelector('.vsug-cands');
    if (candsDiv) { candsDiv.innerHTML = newHtml; }
    else {
      candsDiv = document.createElement('div'); candsDiv.className = 'vsug-cands'; candsDiv.innerHTML = newHtml;
      item.insertBefore(candsDiv, item.querySelector('.vsug-search-row'));
    }
    toast('No auto-match — pick from suggestions', 'info');
  } else { toast('No iTunes results for that search', 'error'); }
}

'''

html = html[:start_idx] + NEW_VERIFY + html[end_idx:]
print("✅ verifyOCRLines replaced + new helpers inserted")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Add CSS before </style>
# ─────────────────────────────────────────────────────────────────────────────
CSS = """
  /* ── OCR suggestion panel ──────────────────────────────────────────────── */
  .vsug-item { padding:10px 12px; border-bottom:1px solid var(--border-subtle); background:rgba(245,158,11,.025); transition:opacity .3s; }
  .vsug-item:last-child { border-bottom:none; }
  .vsug-original { font-size:11px; color:#fbbf24; margin-bottom:4px; display:flex; align-items:center; gap:6px; }
  .vsug-ocr-badge { display:inline-block; background:rgba(245,158,11,.15); border:1px solid rgba(245,158,11,.3); border-radius:4px; padding:1px 6px; font-size:9px; font-weight:700; letter-spacing:.4px; flex-shrink:0; }
  .vsug-cands { display:flex; flex-direction:column; gap:4px; margin-bottom:8px; }
  .vsug-cand-btn { text-align:left; background:var(--surface2); border:1px solid var(--border); border-radius:6px; padding:6px 10px; cursor:pointer; font-family:inherit; font-size:12px; transition:border-color .12s,background .12s; display:flex; align-items:center; width:100%; }
  .vsug-cand-btn:hover { border-color:var(--accent2); background:rgba(124,58,237,.08); }
  .vsug-cand-title { font-weight:500; color:var(--text); }
  .vsug-cand-artist { color:var(--muted); flex:1; }
  .vsug-cand-pct { font-size:10px; color:var(--muted2); flex-shrink:0; margin-left:8px; font-variant-numeric:tabular-nums; }
  .vsug-search-row { display:flex; gap:6px; align-items:center; margin-top:6px; }
  .vsug-search-inp { flex:1; background:var(--surface3); border:1px solid var(--border); border-radius:5px; color:var(--text); padding:5px 8px; font-size:11px; font-family:inherit; outline:none; }
  .vsug-search-inp:focus { border-color:var(--accent2); }
  .vsug-btn-search { background:var(--accent); color:#fff; border:none; border-radius:5px; padding:5px 11px; font-size:11px; cursor:pointer; font-family:inherit; transition:background .12s; }
  .vsug-btn-search:hover { background:var(--accent2); }
  .vsug-btn-keep { background:none; border:1px solid var(--border); color:var(--muted); border-radius:5px; padding:5px 11px; font-size:11px; cursor:pointer; font-family:inherit; transition:all .12s; }
  .vsug-btn-keep:hover { border-color:var(--muted); color:var(--text); }
"""

STYLE_CLOSE = "</style>"
if STYLE_CLOSE in html:
    html = html.replace(STYLE_CLOSE, CSS + STYLE_CLOSE, 1)
    print("✅ CSS added")
else:
    print("⚠️  </style> not found — CSS not inserted")

# ─────────────────────────────────────────────────────────────────────────────
# Write output
# ─────────────────────────────────────────────────────────────────────────────
TARGET.write_text(html, encoding='utf-8')
print(f"\n✅ Done — {TARGET} updated. Original saved to {backup}")
print("Run: cd /home/era/playlist-server && git add -A && git commit -m 'ocr: suggestions for unmatched tracks' && git push && docker compose up -d --build")
