// ── GT DERLEME ──────────────────────────────────────────
// /ground-truth/<site>/<layout> sayfasında kullanılır (eskiden index.html'de modaldı).
// Sayfa şunları sağlar: activeDomain, _templates, showToast, _escHtml, _escAttr,
// closeCompileModal (listeye dönüş) ve selectSite (no-op).

// onclick="f('…')" içine gömülecek metin: önce JS tek tırnak kaçışı, sonra HTML nitelik kaçışı
function _jsq(s) { return _escAttr(String(s ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'")); }

// ── KURAL DİLLERİ ────────────────────────────────────────
// Annotatör/GT alan değeri: düz string (= CSS), CSS listesi (links) ya da {css, xpath, regex}.
// Her dil ayrı derlenir: sekme değişince _compileData.users[u].selectors ve gt_selectors
// o dilin görünümüyle değiştirilir; K1/K2/tablo kodu dilden habersiz çalışır.
const COMPILE_LANGS = { css: 'CSS', xpath: 'XPath', regex: 'Regex' };
let _compileLang      = 'css';
let _compileRawUsers  = {};   // {user: {field: ham değer}}
let _compileRawGt     = {};   // {field: ham değer}
let _compileSelByLang = {};   // {lang: {field: {user, selector}}}
let _compileK2ByLang  = {};   // {lang: K2 sonucu}
let _compileInclude   = {};   // {lang: GT'ye dahil mi}

function _ruleOf(v, lang) {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v[lang] || '';
  return lang === 'css' ? (v || '') : '';
}

// Seçiciyi önizleme DOM'unda çalıştır: CSS → querySelectorAll, XPath → evaluate.
// Regex DOM'a eşlenemez (ham HTML'de çalışır) → vurgulama yok, K2/Test sunucuda.
function _compileQuery(doc, rule) {
  if (!rule || _compileLang === 'regex') return [];
  if (_compileLang === 'xpath') {
    const r = doc.evaluate(String(rule), doc, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    const out = [];
    for (let i = 0; i < r.snapshotLength; i++) {
      const n = r.snapshotItem(i);
      const el = n.nodeType === 1 ? n : (n.ownerElement || n.parentElement);   // @attr / text() → eleman
      if (el && !out.includes(el)) out.push(el);
    }
    return out;
  }
  return [...doc.querySelectorAll(rule)];
}

// Regex için metin/eşleşme sayısı sunucuda: {key: rule} → {texts: {key}, counts: {key}}
async function _compileRemote(page, rules) {
  const res = await fetch('/api/compile/texts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ domain: activeDomain, filename: page, rule_type: _compileLang, rules }),
  });
  return res.json();
}

function _compileFields() {
  const layout = _compileData.layout;
  const tmpl   = _templates[layout.template_id || ''] || {};
  return tmpl.fields ? Object.keys(tmpl.fields) : Object.keys(layout.selectors || {});
}

function compileSetLang(lang) {
  _compileLang = lang;
  const d = _compileData;
  const view = src => Object.fromEntries(Object.entries(src || {}).map(([f, v]) => [f, _ruleOf(v, lang)]).filter(([, r]) => r));
  Object.keys(d.users).forEach(u => { d.users[u].selectors = view(_compileRawUsers[u]); });
  d.gt_selectors   = view(_compileRawGt);
  _compileSelected = _compileSelByLang[lang];
  _compileK2       = _compileK2ByLang[lang] || {};
  _computeK1();
  if (_compileLayer === 2 && !Object.keys(_compileK2).length) _compileLayer = 1;
  compileSetLayer(_compileLayer);
  _compileRenderLangBar();
  _compileUpdateSummary();
  _compileHighlightAll();
}

function _compileRenderLangBar() {
  const el = document.getElementById('compileLangBar');
  if (!el) return;
  const n = _compileFields().length;
  el.innerHTML = Object.entries(COMPILE_LANGS).map(([k, label]) => {
    const sel = Object.keys(_compileSelByLang[k] || {}).length;
    const ann = Object.values(_compileRawUsers).filter(u => Object.values(u).some(v => _ruleOf(v, k))).length;
    return `<button type="button" class="compile-lang-tab ${k === _compileLang ? 'active' : ''} ${_compileInclude[k] ? '' : 'excluded'}"
      onclick="compileSetLang('${k}')" title="${_escAttr(T('{n} annotators entered rules in this language', {n: ann}) + (_compileInclude[k] ? '' : ' · ' + T('not included in GT')))}">
      ${label} <span class="compile-lang-count">${sel}/${n}</span>${_compileInclude[k] ? '' : ` <span class="compile-lang-off">${T('not included')}</span>`}</button>`;
  }).join('') + `
    <label class="compile-include" title="${_escAttr(T("If unchecked, this language's rules are not written to the GT (and are removed from the existing GT)"))}">
      <input type="checkbox" id="compileIncludeCb" ${_compileInclude[_compileLang] ? 'checked' : ''} ${_compileRO() ? 'disabled' : ''}
        onchange="compileSetInclude(this.checked)"> ${T('Include {lang} in GT', {lang: COMPILE_LANGS[_compileLang]})}</label>`;
}

function compileSetInclude(on) {
  _compileInclude[_compileLang] = on;
  _compileRenderLangBar();
  _compileUpdateSummary();
}

// Sayfa, admin olmayan kullanıcı için COMPILE_READONLY = true tanımlar
const _compileRO = () => typeof COMPILE_READONLY !== 'undefined' && COMPILE_READONLY;

// Regex sekmesi: alanın CSS'inden (CSS sekmesinde seçili, yoksa mevcut GT) regex üret — REGEXN
async function compileSuggestRegex(field, btn) {
  if (_compileRO()) return;
  const css = _compileSelByLang.css?.[field]?.selector || _ruleOf(_compileRawGt[field], 'css');
  const cssStr = Array.isArray(css) ? css.join(', ') : css;
  if (!cssStr) { showToast(T('No CSS for this field — select one in the CSS tab first'), 'err'); return; }
  btn.disabled = true; btn.textContent = '…';
  const res = await fetch('/api/suggest-regex', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ selector: cssStr, domain: activeDomain, layout_id: _compileLayoutId, field,
                           filename: document.getElementById('compilePreviewPage').value || '' }),
  });
  const d = await res.json();
  if (!d.success) { btn.disabled = false; btn.textContent = '↻'; showToast(d.error || T('Could not generate regex'), 'err'); return; }
  compileManualSet(field, d.regex);
  showToast(T('{field}: same result as CSS on {passed}/{total} pages ({strategy})', {field, passed: d.passed, total: d.total, strategy: d.strategy}), d.passed === d.total ? 'ok' : 'err');
}

// "Kaydedilecek" sütunu: admin alanın GT kuralını elle yazabilir
function compileManualSet(field, value) {
  if (_compileRO()) return;
  value = value.trim();
  if (!value) delete _compileSelected[field];
  else {
    _compileSelected[field] = { user: '__manual__', selector: value };
    // elle kural girilen dil GT'ye dahil edilir (dahil değilken girilen kural kaybolmasın)
    if (!_compileInclude[_compileLang]) {
      _compileInclude[_compileLang] = true;
      showToast(T('{lang} included in GT', {lang: COMPILE_LANGS[_compileLang]}), 'ok');
    }
  }
  _compileRenderTable();
  _compileRenderLangBar();
  _compileUpdateSummary();
  _compileHighlightAll();
}

let _compileLayoutId  = null;
let _compileData      = null;   // API response
let _compileSelected  = {};     // {field: {user, selector}}
let _compileLayer     = 1;      // 1 = Selector, 2 = İçerik
let _compileK1        = {};     // {field: {kappa, suggested_user, suggested_sel}}
let _compileK2        = {};     // {field: {scores:{user:{em,jac,r1,r2,rl}}, suggested_user, suggested_sel}}

// ── KURAL UYUMU (rule_agreement.py ile birebir aynı) ─────────
// Layout × alan düzeyinde Fleiss κ tanımsızdır (tek konu: şans uyumu kestirilemez). Burada
// gözlenen ikili uyum P_o gösterilir: aynı kuralı yazan annotatör çiftlerinin oranı, kurallar
// anlamı değiştirmeyen yazım farklarından arındırılmış (normalize) olarak. Fleiss κ veri seti
// düzeyinde, layout'lar konu sayılarak Rapor bölümünde hesaplanır.
function _splitTop(s, seps) {
  const out = []; let cur = '', depth = 0, quote = '';
  for (const ch of s) {
    if (quote) { cur += ch; if (ch === quote) quote = ''; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth--;
    if (depth === 0 && seps.includes(ch)) { out.push(cur, ch); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur);
  return out;
}
function _normAttr(a) {
  const m = /^\[\s*([^\s~|^$*=\]]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\s\]]+))\s*(i|s)?\s*)?\]$/.exec(a);
  if (!m) return a;
  const [, name, op, v1, v2, v3, flag] = m;
  if (!op) return `[${name.toLowerCase()}]`;
  const val = v1 !== undefined ? v1 : v2 !== undefined ? v2 : v3;
  return `[${name.toLowerCase()}${op}"${val}"` + (flag ? ` ${flag}` : '') + ']';
}
function _normCompound(c) {
  const m = /^(\*|[a-zA-Z][\w-]*)/.exec(c);
  let tag = m ? m[1].toLowerCase() : '';
  const rest = m ? c.slice(m[1].length) : c;
  const parts = rest.match(/#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?/g) || [];
  if (parts.join('') !== rest) return null;
  const ids = parts.filter(p => p[0] === '#');
  const classes = parts.filter(p => p[0] === '.').sort();
  const attrs = parts.filter(p => p[0] === '[').map(_normAttr).sort();
  const pseudos = parts.filter(p => p[0] === ':');
  if (tag === '*' && (ids.length || classes.length || attrs.length || pseudos.length)) tag = '';
  return tag + ids.join('') + classes.join('') + attrs.join('') + pseudos.join('');
}
function _normCssOne(sel) {
  const orig = sel.trim().replace(/\s+/g, ' ');
  // birleştiricilerin etrafındaki boşluk (yalnızca üst düzeyde; [href~="x"] gibi değerler bozulmaz)
  const s = _splitTop(orig, '>+~').map(t => (t.length === 1 && '>+~'.includes(t)) ? ` ${t} ` : t).join('').replace(/\s+/g, ' ').trim();
  const out = [];
  for (const t of _splitTop(s, ' ')) {
    if (t === ' ' || !t) continue;
    if (t === '>' || t === '+' || t === '~') { out.push(t); continue; }
    const n = _normCompound(t);
    if (n === null) return orig;
    out.push(n);
  }
  return out.join(' ');
}
function _normalizeRule(rule, lang = 'css') {
  if (typeof rule !== 'string' || !rule.trim()) return null;
  if (lang !== 'css') return rule.trim();
  const alts = _splitTop(rule, ',').filter(a => a !== ',' && a.trim()).map(_normCssOne);
  return alts.length ? alts.sort().join(', ') : null;
}
function _observedAgreement(ratings) {
  const r = ratings.filter(Boolean), n = r.length;
  if (n < 2) return null;
  let agree = 0;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) if (r[i] === r[j]) agree++;
  return agree / (n * (n - 1) / 2);
}

function _modeOf(arr) {
  const freq = {};
  arr.forEach(v => { freq[v] = (freq[v] || 0) + 1; });
  return Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

function _kappaBadge(k) {
  if (k === null) return '';
  const cls = k >= 0.6 ? 'kappa-hi' : k >= 0.4 ? 'kappa-mid' : 'kappa-lo';
  const label = k >= 0.6 ? '✓' : k >= 0.4 ? '~' : '!';
  return `<span class="kappa-badge ${cls}" title="${_escAttr(T('Rule agreement (share of annotator pairs that wrote the same normalized rule) = {v}', {v: k.toFixed(2)}))}">${label}${k.toFixed(2)}</span>`;
}

// ── ROUGE / JACCARD ───────────────────────────────────────
function _tokenize(text) {
  return (text || '').toLowerCase().replace(/[^\w\s]/g, ' ').split(/\s+/).filter(Boolean);
}

function _jaccard(a, b) {
  const sa = new Set(_tokenize(a)), sb = new Set(_tokenize(b));
  if (sa.size === 0 && sb.size === 0) return 1;
  const inter = [...sa].filter(t => sb.has(t)).length;
  const union = new Set([...sa, ...sb]).size;
  return union ? inter / union : 0;
}

function _rougeN(hyp, ref, n) {
  const ngrams = (tokens, n) => {
    const out = [];
    for (let i = 0; i <= tokens.length - n; i++) out.push(tokens.slice(i, i + n).join(' '));
    return out;
  };
  const hTokens = _tokenize(hyp), rTokens = _tokenize(ref);
  if (!hTokens.length || !rTokens.length) return 0;
  const hGrams = ngrams(hTokens, n), rGrams = ngrams(rTokens, n);
  const rSet = {};
  rGrams.forEach(g => { rSet[g] = (rSet[g] || 0) + 1; });
  let match = 0;
  const hSet = {};
  hGrams.forEach(g => { hSet[g] = (hSet[g] || 0) + 1; });
  Object.entries(hSet).forEach(([g, c]) => { match += Math.min(c, rSet[g] || 0); });
  const precision = hGrams.length ? match / hGrams.length : 0;
  const recall    = rGrams.length ? match / rGrams.length : 0;
  if (precision + recall === 0) return 0;
  return 2 * precision * recall / (precision + recall); // F1
}

function _rougeL(hyp, ref) {
  const h = _tokenize(hyp), r = _tokenize(ref);
  if (!h.length || !r.length) return 0;
  // LCS via DP
  const dp = Array.from({length: h.length + 1}, () => new Array(r.length + 1).fill(0));
  for (let i = 1; i <= h.length; i++)
    for (let j = 1; j <= r.length; j++)
      dp[i][j] = h[i-1] === r[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
  const lcs = dp[h.length][r.length];
  const precision = h.length ? lcs / h.length : 0;
  const recall    = r.length ? lcs / r.length : 0;
  if (precision + recall === 0) return 0;
  return 2 * precision * recall / (precision + recall);
}

function _scoreColor(v) {
  if (v >= 0.8) return 'var(--green)';
  if (v >= 0.5) return 'var(--yellow)';
  return 'var(--red)';
}

// ── KATMAN 1 HESAP ────────────────────────────────────────
function _computeK1() {
  if (!_compileData) return;
  const { users, layout } = _compileData;
  const tid    = layout.template_id || '';
  const tmpl   = _templates[tid] || {};
  const fields = tmpl.fields ? Object.keys(tmpl.fields) : Object.keys(layout.selectors || {});
  const userKeys = Object.keys(users);

  _compileK1 = {};
  fields.forEach(field => {
    const sels = userKeys.map(u => (users[u]?.selectors || {})[field] || null);
    const nonEmpty = sels.filter(Boolean);
    const kappa = _observedAgreement(sels.map(x => _normalizeRule(x, _compileLang)));
    const suggested_sel = _modeOf(nonEmpty) || null;
    const suggested_user = suggested_sel
      ? userKeys.find(u => (users[u]?.selectors || {})[field] === suggested_sel) || null
      : null;
    _compileK1[field] = { kappa, suggested_sel, suggested_user };
  });

  // Global kappa = mean of non-null field kappas
  const vals = Object.values(_compileK1).map(v => v.kappa).filter(v => v !== null);
  const globalK = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
  const gEl = document.getElementById('compileKappaGlobal');
  if (gEl) gEl.innerHTML = globalK !== null ? `${T('Mean rule agreement')} = ${_kappaBadge(globalK)}` : '';
}

// ── KATMAN 2 HESAP (iframe içeriği) ───────────────────────
async function compileRunK2() {
  const page = document.getElementById('compilePreviewPage').value;
  if (!page) { showToast(T('Select a page first'), 'err'); return; }
  if (!_compileData) return;

  const frame = document.getElementById('compileIframe');
  let doc;
  try { doc = frame.contentDocument; } catch(e) { showToast(T('iframe access error'), 'err'); return; }
  if (!doc || !doc.body) { showToast(T('Page not loaded yet, please wait'), 'err'); return; }

  const { users, layout, gt_selectors } = _compileData;
  const tid    = layout.template_id || '';
  const tmpl   = _templates[tid] || {};
  const fields = tmpl.fields ? Object.keys(tmpl.fields) : Object.keys(layout.selectors || {});
  const userKeys = Object.keys(users);

  // Regex: metinler sunucuda ham HTML üzerinden
  let remote = null;
  if (_compileLang === 'regex') {
    const rules = {};
    fields.forEach(f => {
      userKeys.forEach(u => { const s = (users[u]?.selectors || {})[f]; if (s) rules[`${u}|${f}`] = s; });
      const g = (gt_selectors || {})[f]; if (g) rules[`__gt__|${f}`] = g;
    });
    remote = await _compileRemote(page, rules);
  }

  _compileK2 = {};
  _compileK2ByLang[_compileLang] = _compileK2;
  fields.forEach(field => {
    const gtSel = (gt_selectors || {})[field];
    // Extract text per user
    const texts = {};
    userKeys.forEach(u => {
      const sel = (users[u]?.selectors || {})[field];
      if (!sel) { texts[u] = null; return; }
      try {
        if (remote) { texts[u] = remote.texts?.[`${u}|${field}`] || null; return; }
        const els = _compileQuery(doc, sel);
        texts[u] = els.length ? [...els].map(el => el.innerText || el.textContent || '').join(' ').trim() : null;
      } catch(e) { texts[u] = null; }
    });

    // Reference: GT text if GT selector exists, else pairwise approach
    let refText = null;
    if (gtSel) {
      try {
        if (remote) refText = remote.texts?.[`__gt__|${field}`] || null;
        else {
          const els = _compileQuery(doc, gtSel);
          refText = els.length ? [...els].map(el => el.innerText || el.textContent || '').join(' ').trim() : null;
        }
      } catch(e) {}
    }

    const scores = {};
    userKeys.forEach(u => {
      const hyp = texts[u];
      if (!hyp) { scores[u] = null; return; }
      const ref = refText || Object.values(texts).filter(t => t && t !== hyp)[0] || hyp;
      const em  = hyp === ref ? 1 : 0;
      const jac = _jaccard(hyp, ref);
      const r1  = _rougeN(hyp, ref, 1);
      const r2  = _rougeN(hyp, ref, 2);
      const rl  = _rougeL(hyp, ref);
      scores[u] = { em, jac, r1, r2, rl, text: hyp };
    });

    // Suggested: highest ROUGE-L
    const best = userKeys
      .filter(u => scores[u])
      .sort((a, b) => (scores[b]?.rl || 0) - (scores[a]?.rl || 0))[0] || null;
    const suggested_sel = best ? (users[best]?.selectors || {})[field] || null : null;

    _compileK2[field] = { scores, suggested_user: best, suggested_sel };
  });

  // Switch to K2 view
  compileSetLayer(2);
  showToast(T('K2 content analysis complete'), 'ok');
}

// ── KATMAN SWITCH ─────────────────────────────────────────
function compileSetLayer(n) {
  _compileLayer = n;
  document.getElementById('compileLayerK1Btn').classList.toggle('active', n === 1);
  document.getElementById('compileLayerK2Btn').classList.toggle('active', n === 2);
  _compileRenderTable();
}

// ── OTOMATİK SEÇ ─────────────────────────────────────────
function compileAutoSelect() {
  if (!_compileData) return;
  const source = _compileLayer === 2 && Object.keys(_compileK2).length ? _compileK2 : _compileK1;
  let changed = 0;
  Object.entries(source).forEach(([field, info]) => {
    if (info.suggested_sel && info.suggested_user) {
      _compileSelected[field] = { user: info.suggested_user, selector: info.suggested_sel };
      changed++;
    }
  });
  _compileRenderTable();
  _compileUpdateSummary();
  _compileHighlightAll();
  showToast('💡 ' + T('{n} fields auto-selected', {n: changed}), 'ok');
}

async function openCompileModal(layoutId) {
  if (!activeDomain) { showToast(T('Select a site first'), 'err'); return; }
  _compileLayoutId = layoutId;
  _compileSelected = {};
  _compileLayer    = 1;
  _compileK1       = {};
  _compileK2       = {};

  document.getElementById('compileOverlay').classList.add('open');
  document.getElementById('compileTitle').textContent = `⚙ ${T('Compile')} — ${layoutId}`;
  document.getElementById('compileTableBody').innerHTML = `<tr><td colspan="99" style="color:var(--text3);padding:20px;text-align:center">${T('Loading…')}</td></tr>`;
  document.getElementById('compilePagesWrap').innerHTML = '';
  document.getElementById('compileSummary').textContent = '';
  document.getElementById('compileKappaGlobal').textContent = '';
  document.getElementById('compileLayerK1Btn').classList.add('active');
  document.getElementById('compileLayerK2Btn').classList.remove('active');

  const res  = await fetch(`/api/compile/${activeDomain}/${layoutId}`);
  const data = await res.json();
  if (data.error) { showToast(data.error, 'err'); closeCompileModal(); return; }

  // Ham değerleri sakla; her dil için mevcut GT'yi ön-seçim yap
  _compileRawUsers = {};
  Object.entries(data.users || {}).forEach(([u, ud]) => { _compileRawUsers[u] = { ...(ud.selectors || {}) }; });
  _compileRawGt = { ...(data.gt_selectors || {}) };
  _compileSelByLang = {}; _compileK2ByLang = {}; _compileInclude = {};
  Object.keys(COMPILE_LANGS).forEach(lang => {
    const sel = {};
    Object.entries(_compileRawGt).forEach(([f, v]) => { const r = _ruleOf(v, lang); if (r) sel[f] = { user: '__gt__', selector: r }; });
    _compileSelByLang[lang] = sel;
    const anyAnn = Object.values(_compileRawUsers).some(u => Object.values(u).some(v => _ruleOf(v, lang)));
    // varsayılan: GT'de o dil varsa dahil; CSS için annotatör girmişse de dahil
    _compileInclude[lang] = Object.keys(sel).length > 0 || (lang === 'css' && anyAnn);
  });

  _compileData = data;
  _compileRenderPages();
  compileSetLang('css');

  // Populate preview page dropdown
  const sel = document.getElementById('compilePreviewPage');
  const allPages = [...new Set([...data.union_pages, ...data.gt_pages])].sort();
  sel.innerHTML = `<option value="">${T('Select page…')}</option>` +
    allPages.map(p => `<option value="${p}">${p}</option>`).join('');
  if (allPages.length) { sel.value = allPages[0]; compileLoadPreview(); }
}

function closeCompileModal() {
  document.getElementById('compileOverlay').classList.remove('open');
  _compileData = null;
  _compileSelected = {};
  _compileK1 = {};
  _compileK2 = {};
  _compileZoom = 1.0;
  document.getElementById('compileZoomLabel').textContent = '100%';
}

function _compileRenderTable() {
  const data   = _compileData;
  const users  = Object.keys(data.users);
  const layout = data.layout;
  const tid    = layout.template_id || '';
  const tmpl   = _templates[tid] || {};
  const fields = tmpl.fields ? Object.keys(tmpl.fields) : Object.keys(layout.selectors || {});
  const isK2   = _compileLayer === 2;

  // ── Header ──
  const thead = document.getElementById('compileTableHead');
  if (!isK2) {
    thead.innerHTML = `<tr>
      <th>${T('Field')}</th>
      ${users.map(u => `<th class="user-col">${u}</th>`).join('')}
      <th style="color:var(--green)">${T('Current GT')}</th>
      <th class="metric-col">κ (sel)</th>
      <th title="${_escAttr(T('{lang} rule to be written to the GT — filled by selecting a cell; the admin can edit it by hand', {lang: COMPILE_LANGS[_compileLang]}))}">${T('To save')}</th>
    </tr>`;
  } else {
    thead.innerHTML = `<tr>
      <th>${T('Field')}</th>
      ${users.map(u => `<th class="user-col">${u} (${T('text')})</th>`).join('')}
      <th class="metric-col">EM</th>
      <th class="metric-col">Jac</th>
      <th class="metric-col">R-1</th>
      <th class="metric-col">R-2</th>
      <th class="metric-col">R-L</th>
    </tr>`;
  }

  // ── Body ──
  const tbody = document.getElementById('compileTableBody');
  tbody.innerHTML = fields.map(field => {
    const gtSel  = (data.gt_selectors || {})[field] || '';
    const selCur = _compileSelected[field];
    const k1info = _compileK1[field] || {};
    const k2info = _compileK2[field] || {};

    if (!isK2) {
      // ── Katman 1 ──
      const fcolor = _fieldColor(field);
      const frgb   = _hexToRgb(fcolor);
      const userCells = users.map(u => {
        const sel = (data.users[u]?.selectors || {})[field] || '';
        if (!sel) return `<td><span class="compile-sel-cell empty">—</span></td>`;
        const isSelected  = selCur?.user === u;
        const isSuggested = k1info.suggested_user === u && !isSelected;
        const allVals = users.map(uu => (data.users[uu]?.selectors || {})[field]).filter(Boolean);
        const allSame = allVals.length > 1 && allVals.every(v => v === allVals[0]);
        const cls = ['compile-sel-cell',
          isSelected  ? 'selected'  : '',
          isSuggested ? 'suggested' : '',
          allSame     ? 'same-badge': '',
        ].filter(Boolean).join(' ');
        const cellStyle = isSelected
          ? `outline:2px solid ${fcolor};background:rgba(${frgb},.15);color:${fcolor};`
          : isSuggested
            ? `outline:1px dashed ${fcolor};color:${fcolor};opacity:.7;`
            : '';
        return `<td><span class="${cls}" title="${_escAttr(sel)}" style="${cellStyle}"
          onclick="compileSelectCell('${field}','${u}','${_jsq(sel)}')"
          onmouseenter="compileHoverCell('${_jsq(sel)}')"
          onmouseleave="compileHoverCell(null)">${_escHtml(sel)}</span></td>`;
      });

      const isGtSelected = selCur?.user === '__gt__';
      const gtCls = ['compile-sel-cell', gtSel ? '' : 'empty', isGtSelected ? 'selected' : ''].filter(Boolean).join(' ');
      const gtStyle = isGtSelected ? `outline:2px solid ${fcolor};background:rgba(${frgb},.15);color:${fcolor};` : '';
      const gtCell = gtSel
        ? `<td><span class="${gtCls}" title="${_escAttr(gtSel)}" style="${gtStyle}"
            onclick="compileSelectCell('${field}','__gt__','${_jsq(gtSel)}')"
            onmouseenter="compileHoverCell('${_jsq(gtSel)}')"
            onmouseleave="compileHoverCell(null)">${_escHtml(gtSel)}</span></td>`
        : `<td><span class="compile-sel-cell empty">—</span></td>`;

      const hasSelection = !!selCur;
      const kBadge = _kappaBadge(k1info.kappa ?? null);
      return `<tr>
        <td class="field-name">${field}${hasSelection ? ' <span style="color:var(--green);font-size:10px">✓</span>' : ''}${k1info.suggested_sel && !hasSelection ? ' <span style="color:var(--accent2);font-size:10px">💡</span>' : ''}</td>
        ${userCells.join('')}
        ${gtCell}
        <td style="white-space:nowrap">${kBadge}</td>
        <td><input type="text" class="compile-manual ${selCur?.user === '__manual__' ? 'manual' : ''}" value="${_escAttr(selCur?.selector || '')}" ${_compileRO() ? 'readonly' : ''}
          placeholder="${_escAttr(T('— not written to GT'))}" title="${selCur?.user === '__manual__' ? T('Entered by hand') : selCur ? _escAttr(T('Source: {src}', {src: selCur.user === '__gt__' ? T('current GT') : selCur.user})) : ''}"
          onchange="compileManualSet('${field}', this.value)" onmouseenter="compileHoverCell(this.value)" onmouseleave="compileHoverCell(null)">
          ${_compileLang === 'regex' && !_compileRO() ? `<button type="button" class="compile-gen-btn" title="${_escAttr(T('Generate regex from CSS (REGEXN)'))}" onclick="compileSuggestRegex('${field}', this)">↻</button>` : ''}</td>
      </tr>`;

    } else {
      // ── Katman 2 ──
      const fcolor = _fieldColor(field);
      const frgb   = _hexToRgb(fcolor);
      const userCells = users.map(u => {
        const sc  = k2info.scores?.[u];
        const sel = (data.users[u]?.selectors || {})[field] || '';
        if (!sc) return `<td><span class="compile-content-cell empty" style="opacity:.3">—</span></td>`;
        const isSelected  = selCur?.user === u;
        const isSuggested = k2info.suggested_user === u && !isSelected;
        const cls = ['compile-sel-cell',
          isSelected  ? 'selected'  : '',
          isSuggested ? 'suggested' : '',
        ].filter(Boolean).join(' ');
        const cellStyle = isSelected
          ? `outline:2px solid ${fcolor};background:rgba(${frgb},.15);color:${fcolor};`
          : isSuggested
            ? `outline:1px dashed ${fcolor};color:${fcolor};opacity:.7;`
            : '';
        const short = sc.text.length > 60 ? sc.text.slice(0, 57) + '…' : sc.text;
        return `<td><span class="${cls}" title="${_escAttr(sc.text)}" style="${cellStyle}"
          onclick="compileSelectCell('${field}','${u}','${_jsq(sel)}')"
          onmouseenter="compileHoverCell('${_jsq(sel)}')"
          onmouseleave="compileHoverCell(null)">${_escHtml(short)}</span></td>`;
      });

      // Pick best scores across users for coloring reference
      const allScores = users.map(u => k2info.scores?.[u]).filter(Boolean);
      const avgScore = (key) => allScores.length
        ? allScores.reduce((s, sc) => s + (sc[key] || 0), 0) / allScores.length : 0;
      const em  = allScores.some(sc => sc.em)  ? '✓' : '✗';
      const jac = avgScore('jac'), r1 = avgScore('r1'), r2 = avgScore('r2'), rl = avgScore('rl');
      const fmt = v => `<span style="color:${_scoreColor(v)}">${v.toFixed(2)}</span>`;

      const hasSelection = !!selCur;
      return `<tr>
        <td class="field-name">${field}${hasSelection ? ' <span style="color:var(--green);font-size:10px">✓</span>' : ''}${k2info.suggested_user && !hasSelection ? ' <span style="color:var(--accent2);font-size:10px">💡</span>' : ''}</td>
        ${userCells.join('')}
        ${allScores.length ? `
        <td class="compile-score-cell" style="color:${em==='✓'?'var(--green)':'var(--red)'}">${em}</td>
        <td class="compile-score-cell">${fmt(jac)}</td>
        <td class="compile-score-cell">${fmt(r1)}</td>
        <td class="compile-score-cell">${fmt(r2)}</td>
        <td class="compile-score-cell">${fmt(rl)}</td>`
        : `<td class="compile-score-cell" colspan="5" style="color:var(--text3)" title="${_escAttr(T('No annotator rule extracts content from the page for this field'))}">—</td>`}
      </tr>`;
    }
  }).join('');
}

// ── FIELD RENK PALETİ ────────────────────────────────────
const _FIELD_PALETTE = [
  '#5b7cfa', '#34d399', '#f87171', '#fbbf24', '#a78bfa',
  '#38bdf8', '#fb923c', '#4ade80', '#e879f9', '#67e8f9',
];

function _fieldColor(field) {
  if (!_compileData) return _FIELD_PALETTE[0];
  const layout = _compileData.layout;
  const tid    = layout.template_id || '';
  const tmpl   = _templates[tid] || {};
  const fields = tmpl.fields ? Object.keys(tmpl.fields) : Object.keys(layout.selectors || {});
  const idx    = fields.indexOf(field);
  return _FIELD_PALETTE[(idx >= 0 ? idx : 0) % _FIELD_PALETTE.length];
}

function _hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `${r},${g},${b}`;
}

function compileSelectCell(field, user, selector) {
  _compileSelected[field] = { user, selector };
  _compileRenderTable();
  _compileUpdateSummary();
  _compileHighlightAll();
}

function compileHoverCell(selector) {
  const frame = document.getElementById('compileIframe');
  try {
    const doc = frame.contentDocument;
    doc.querySelectorAll('.__compile_hover').forEach(el => {
      el.classList.remove('__compile_hover');
      delete el.dataset.compileHover;
    });
    if (selector) _compileQuery(doc, selector).forEach(el => {
      el.classList.add('__compile_hover');
    });
  } catch(e) {}
}

function _compileHighlightAll() {
  const frame = document.getElementById('compileIframe');
  try {
    const doc = frame.contentDocument;
    if (!doc) return;

    // Temizle — tüm field class'larını ve etiketleri kaldır
    doc.querySelectorAll('[class*="__cfield_"]').forEach(el => {
      [...el.classList].filter(c => c.startsWith('__cfield_')).forEach(c => el.classList.remove(c));
    });
    doc.querySelectorAll('.__compile_label').forEach(el => el.remove());

    // Her field için seçili selector'ı renkli highlight et + etiket ekle
    Object.entries(_compileSelected).forEach(([field, { selector }]) => {
      if (!selector) return;
      const color   = _fieldColor(field);
      const rgb     = _hexToRgb(color);
      const cls     = `__cfield_${field.replace(/[^a-zA-Z0-9]/g,'_')}`;

      // CSS kuralını güncelle
      _compileUpdateFieldStyle(doc, cls, color, rgb);

      try {
        _compileQuery(doc, selector).forEach(el => {
          el.classList.add(cls);
          // Etiket zaten varsa ekleme
          const existingLbl = el.parentElement?.querySelector(`.__compile_label[data-field="${field}"]`);
          if (existingLbl) return;

          const lbl = doc.createElement('span');
          lbl.className = '__compile_label';
          lbl.dataset.field = field;
          lbl.dataset.sel   = selector;
          lbl.textContent   = `${field} · ${selector}`;
          lbl.style.cssText = `
            display:block;
            background:${color};color:#fff;
            font:600 10px/1.4 monospace;
            padding:1px 6px;border-radius:3px 3px 0 0;
            white-space:nowrap;overflow:hidden;max-width:280px;
            text-overflow:ellipsis;pointer-events:none;
            opacity:.82;margin-bottom:0;
          `;
          // Etiketi element'in hemen önüne, parent'a ekle
          if (el.parentElement) {
            el.parentElement.insertBefore(lbl, el);
          }
        });
      } catch(e) {}
    });
  } catch(e) {}
}

function _compileUpdateFieldStyle(doc, cls, color, rgb) {
  let sheet = doc.getElementById('__compile_field_styles');
  if (!sheet) {
    sheet = doc.createElement('style');
    sheet.id = '__compile_field_styles';
    doc.head.appendChild(sheet);
  }
  // Sadece bu class'ı güncelle — diğerlerini koru
  const rule = `.${cls} { outline: 2px solid ${color} !important; outline-offset: 3px !important; background: rgba(${rgb},.08) !important; }`;
  const existing = sheet.textContent;
  const clsRe = new RegExp(`\\.${cls}\\s*\\{[^}]*\\}`, 'g');
  sheet.textContent = existing.replace(clsRe, '') + rule;
}

function _compileInjectStyles(doc) {
  if (doc.getElementById('__compile_style')) return;
  const s = doc.createElement('style');
  s.id = '__compile_style';
  s.textContent = `
    .__compile_hover { outline: 2px solid #fbbf24 !important; outline-offset: 3px !important; background: rgba(251,191,36,.1) !important; }
  `;
  doc.head.appendChild(s);
}

function _compileRenderPages() {
  const data    = _compileData;
  const wrap    = document.getElementById('compilePagesWrap');
  const union   = data.union_pages;
  const gtPages = new Set(data.gt_pages);

  wrap.innerHTML = union.map(p => {
    const inGT = gtPages.has(p);
    return `<div class="compile-page-row">
      <input type="checkbox" class="compile-page-cb" value="${p}" checked>
      <span style="font-family:var(--mono);font-size:11px;color:var(--text2)">${p}</span>
      ${inGT ? '<span style="font-size:10px;color:var(--green)">GT</span>' : ''}
    </div>`;
  }).join('') || `<div style="color:var(--text3);font-size:12px;padding:4px">${T('No user assignments')}</div>`;

  document.getElementById('compileSelectAllPages').checked = true;
  document.getElementById('compilePageCount').textContent = T('{n} pages', {n: union.length});
}

function compileToggleAllPages(checked) {
  document.querySelectorAll('.compile-page-cb').forEach(cb => cb.checked = checked);
}

function _compileUpdateSummary() {
  const selCount    = Object.keys(_compileSelected).length;
  const layout      = _compileData?.layout || {};
  const tid         = layout.template_id || '';
  const tmpl        = _templates[tid] || {};
  const totalFields = tmpl.fields ? Object.keys(tmpl.fields).length : Object.keys(layout.selectors || {}).length;
  const incl = Object.keys(COMPILE_LANGS).filter(l => _compileInclude[l]).map(l => COMPILE_LANGS[l]);
  document.getElementById('compileSummary').textContent =
    T('{lang}: {n} / {total} fields selected · Included in GT: {langs}', {lang: COMPILE_LANGS[_compileLang], n: selCount, total: totalFields, langs: incl.join(', ') || '—'});
  _compileRenderLangBar();
}

// ── ZOOM ─────────────────────────────────────────────────
let _compileZoom = 1.0;

function _compileApplyZoom() {
  const frame = document.getElementById('compileIframe');
  const wrap  = document.getElementById('compileIframeWrap');
  frame.style.width  = (100 / _compileZoom) + '%';
  frame.style.height = (100 / _compileZoom) + '%';
  frame.style.transform = `scale(${_compileZoom})`;
  document.getElementById('compileZoomLabel').textContent = Math.round(_compileZoom * 100) + '%';
}

function compileZoom(delta) {
  _compileZoom = Math.min(2.0, Math.max(0.25, _compileZoom + delta));
  _compileApplyZoom();
}

function compileZoomReset() {
  _compileZoom = 1.0;
  _compileApplyZoom();
}

function compileZoomFit() {
  const wrap = document.getElementById('compileIframeWrap');
  const frame = document.getElementById('compileIframe');
  // Reset first to get natural scroll width
  frame.style.transform = 'none';
  frame.style.width  = '100%';
  frame.style.height = '100%';
  let naturalW = 0;
  try { naturalW = frame.contentDocument?.body?.scrollWidth || 0; } catch(e) {}
  if (!naturalW) { _compileZoom = 1.0; _compileApplyZoom(); return; }
  const wrapW = wrap.clientWidth;
  _compileZoom = Math.min(1.0, Math.round((wrapW / naturalW) * 100) / 100);
  _compileApplyZoom();
}

document.addEventListener('wheel', (e) => {
  if (!e.ctrlKey && !e.metaKey) return;
  const wrap = document.getElementById('compileIframeWrap');
  if (!wrap || !wrap.contains(e.target)) return;
  e.preventDefault();
  compileZoom(e.deltaY < 0 ? 0.1 : -0.1);
}, { passive: false });

function compileLoadPreview() {
  const page = document.getElementById('compilePreviewPage').value;
  if (!page || !activeDomain) return;
  const frame = document.getElementById('compileIframe');
  frame.src   = `/api/page/${activeDomain}/${page}`;
  frame.onload = () => {
    try { _compileInjectStyles(frame.contentDocument); } catch(e) {}
    _compileHighlightAll();
    _compileApplyZoom();
  };
}

async function compileTestAll() {
  const page = document.getElementById('compilePreviewPage').value;
  if (!page) { showToast(T('Select a page first'), 'err'); return; }
  const frame  = document.getElementById('compileIframe');
  const status = document.getElementById('compileTestStatus');
  status.textContent = T('Testing…');
  try {
    const doc = frame.contentDocument;
    doc.querySelectorAll('.__compile_hl').forEach(el => el.classList.remove('__compile_hl'));
    let total = 0;
    if (_compileLang === 'regex') {
      const rules = Object.fromEntries(Object.entries(_compileSelected).map(([f, { selector }]) => [f, selector]));
      const r = await _compileRemote(page, rules);
      total = Object.values(r.counts || {}).reduce((a, b) => a + b, 0);
    } else Object.values(_compileSelected).forEach(({ selector }) => {
      try {
        const matches = _compileQuery(doc, selector);
        matches.forEach(el => el.classList.add('__compile_hl'));
        total += matches.length;
      } catch(e) {}
    });
    status.textContent = T('{n} matches', {n: total});
    status.style.color = total ? 'var(--green)' : 'var(--red)';
  } catch(e) { status.textContent = T('Error'); }
}

async function compileSave() {
  // Yalnızca "GT'ye dahil" dillerin seçimleri birleştirilir: yalnız CSS → düz string, aksi halde {css, xpath, regex}
  const langs  = Object.keys(COMPILE_LANGS).filter(l => _compileInclude[l]);
  const fields = new Set([..._compileFields(), ...langs.flatMap(l => Object.keys(_compileSelByLang[l] || {}))]);
  const selectors = {};
  fields.forEach(f => {
    const parts = {};
    langs.forEach(l => { const s = _compileSelByLang[l]?.[f]?.selector; if (s) parts[l] = s; });
    if (!Object.keys(parts).length) return;
    selectors[f] = (Object.keys(parts).length === 1 && parts.css)
      ? parts.css : { css: parts.css || null, xpath: parts.xpath || null, regex: parts.regex || null };
  });
  const empty = langs.filter(l => !Object.keys(_compileSelByLang[l] || {}).length);
  if (empty.length && !confirm(T('{langs} included in GT but no fields selected. Save anyway?', {langs: empty.map(l => COMPILE_LANGS[l]).join(', ')}))) return;

  const pages = [...document.querySelectorAll('.compile-page-cb:checked')].map(cb => cb.value);

  if (!Object.keys(selectors).length) { showToast(T('Select at least one field'), 'err'); return; }

  const res  = await fetch(`/api/compile/${activeDomain}/${_compileLayoutId}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ selectors, pages }),
  });
  const data = await res.json();
  if (data.success) {
    showToast('✓ ' + T('{fields} fields, {pages} pages saved to GT', {fields: data.fields, pages: data.pages}), 'ok');
    closeCompileModal();
    await selectSite(activeDomain);
  } else {
    showToast(data.error || T('Save error'), 'err');
  }
}

