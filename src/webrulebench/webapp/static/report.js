/* Rapor sayfası için tablo + grafik yardımcıları.
 *
 * RT.table(spec)  → sıralanabilir tablo HTML'i; başlığında CSV / LaTeX / Markdown çıktısı.
 *   spec = {id, title, caption?, note?, columns: [{k, label, fmt?(v,row)→metin, html?(v,row)→HTML,
 *           num?, heat?(0..1 ısı hücresi), best?: 'max'|'min'|'absmin' (en iyi değer kalın), sortable?: false}], rows,
 *           sort?: {k, dir}}
 * RT.chart(id, title, build, opts) → grafik kutusu HTML'i; build(theme) Chart.js yapılandırmasını döndürür.
 *   Sayfaya eklendikten sonra RT.mount() çağrılır. PNG çıktısı aynı build ile açık "makale teması"nda,
 *   beyaz zeminde ve yüksek çözünürlükte yeniden çizilir; CSV grafiğin verisini verir (matplotlib vb. için).
 */
const RT = {
  // Okabe–Ito: renk körlüğüne dayanıklı, baskıda ayırt edilebilir
  PALETTE: ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00', '#F0E442', '#999999',
            '#332288', '#88CCEE', '#117733', '#AA4499'],
  SCREEN: {text: '#8892a4', grid: '#262b38', title: '#e2e8f0', font: "'Syne', sans-serif", bg: null},
  PAPER:  {text: '#222222', grid: '#dddddd', title: '#000000', font: 'Helvetica, Arial, sans-serif', bg: '#ffffff'},
  _tables: {}, _charts: {}, _pending: {},

  color(i, a = 1) {
    const c = this.PALETTE[i % this.PALETTE.length];
    if (a === 1) return c;
    const n = parseInt(c.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  },
  pct: v => v === null || v === undefined || Number.isNaN(v) ? '—' : (v * 100).toFixed(1),
  num: (v, d = 0) => v === null || v === undefined ? '—' : Number(v).toLocaleString(LOCALE, {maximumFractionDigits: d}),
  mean(xs) { xs = xs.filter(x => typeof x === 'number' && !Number.isNaN(x)); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; },
  heat(v) {               // kırmızı → sarı → yeşil (koyu tema), değerlendirme sayfalarıyla aynı
    if (v === null || v === undefined) return 'var(--bg)';
    return `hsla(${Math.round(v * 120)}, 65%, 40%, ${0.25 + v * 0.55})`;
  },

  // ── TABLO ───────────────────────────────────────────
  table(spec) {
    this._tables[spec.id] = spec;
    return `<div class="rt-block" id="rtb-${spec.id}">${this._tableInner(spec)}</div>`;
  },
  _cellText(c, r) {
    const v = r[c.k];
    if (c.fmt) return String(c.fmt(v, r));
    return v === null || v === undefined ? '—' : String(v);
  },
  _bests(spec) {
    const out = {};
    for (const c of spec.columns.filter(c => c.best)) {
      const vs = spec.rows.map(r => r[c.k]).filter(v => typeof v === 'number');
      if (vs.length < 2) continue;
      out[c.k] = c.best === 'max' ? Math.max(...vs) : c.best === 'absmin'      // absmin: sıfıra en yakın (ör. genelleme farkı)
        ? vs.reduce((m, v) => Math.abs(v) < Math.abs(m) ? v : m) : Math.min(...vs);
    }
    return out;
  },
  _sorted(spec) {
    const s = spec.sort;
    if (!s) return spec.rows;
    const dir = s.dir === 'asc' ? 1 : -1;
    return [...spec.rows].sort((a, b) => {
      const x = a[s.k], y = b[s.k];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;            // boşlar her zaman sonda
      if (y === null || y === undefined) return -1;
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), LOCALE)) * dir;
    });
  },
  _tableInner(spec) {
    const bests = this._bests(spec), rows = this._sorted(spec);
    const head = spec.columns.map(c => {
      const arrow = spec.sort?.k === c.k ? (spec.sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
      const click = c.sortable === false ? '' : ` onclick="RT.sortBy('${spec.id}','${c.k}')" style="cursor:pointer"`;
      return `<th${click} class="${c.num || c.heat ? 'th-num' : ''}" title="${Hub.esc(c.title || '')}">${Hub.esc(c.label)}${arrow}</th>`;
    }).join('');
    const body = rows.map(r => `<tr>${spec.columns.map(c => {
      const v = r[c.k], best = bests[c.k] !== undefined && v === bests[c.k];
      const inner = c.html ? c.html(v, r) : Hub.esc(this._cellText(c, r));
      if (c.heat) return `<td class="heat" style="background:${this.heat(typeof v === 'number' ? v : null)}">${best ? `<b>${inner}</b>` : inner}</td>`;
      return `<td class="${c.num ? 'num' : ''}">${best ? `<b class="rt-best">${inner}</b>` : inner}</td>`;
    }).join('')}</tr>`).join('') || `<tr><td colspan="${spec.columns.length}" class="empty">${Hub.esc(spec.empty || T('No data'))}</td></tr>`;
    return `<div class="rt-head"><span class="rt-title">${Hub.esc(spec.title || '')}</span>
        <span class="rt-actions">
          <button type="button" class="btn sm" onclick="RT.exportTable('${spec.id}','csv')" title="${T('Download CSV')}">CSV</button>
          <button type="button" class="btn sm" onclick="RT.exportTable('${spec.id}','tex')" title="${T('LaTeX (booktabs) table')}">LaTeX</button>
          <button type="button" class="btn sm" onclick="RT.exportTable('${spec.id}','md')" title="${T('Markdown table')}">MD</button>
        </span></div>
      <div class="table-wrap"><table class="${spec.columns.some(c => c.heat) ? 'heatmap' : ''}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
      ${spec.note ? `<p class="muted rt-note">${spec.note}</p>` : ''}`;
  },
  sortBy(id, k) {
    const spec = this._tables[id];
    spec.sort = spec.sort?.k === k ? {k, dir: spec.sort.dir === 'asc' ? 'desc' : 'asc'} : {k, dir: 'desc'};
    document.getElementById(`rtb-${id}`).innerHTML = this._tableInner(spec);
  },

  exportTable(id, fmt) {
    const spec = this._tables[id];
    const cols = spec.columns.filter(c => c.export !== false);
    const rows = this._sorted(spec), bests = this._bests(spec);
    const txt  = (c, r) => this._cellText(c, r);
    if (fmt === 'csv') {
      const q = s => /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      const lines = [cols.map(c => q(c.label)).join(','), ...rows.map(r => cols.map(c => q(txt(c, r))).join(','))];
      this.download(`${id}.csv`, '\ufeff' + lines.join('\n'), 'text/csv');
      return;
    }
    if (fmt === 'md') {
      const esc = s => s.replace(/\|/g, '\\|');
      const lines = [`| ${cols.map(c => esc(c.label)).join(' | ')} |`,
                     `| ${cols.map(c => c.num || c.heat ? '---:' : '---').join(' | ')} |`,
                     ...rows.map(r => `| ${cols.map(c => esc(txt(c, r))).join(' | ')} |`)];
      Hub.showText(`${spec.title} — Markdown`, [{label: T('Markdown table'), text: lines.join('\n')}]);
      return;
    }
    const tex = s => s.replace(/\\/g, '\\textbackslash{}').replace(/([&%$#_{}])/g, '\\$1')
                      .replace(/~/g, '\\textasciitilde{}').replace(/\^/g, '\\textasciicircum{}').replace(/—/g, '--');
    const align = cols.map(c => c.num || c.heat ? 'r' : 'l').join('');
    const body = rows.map(r => '    ' + cols.map(c => {
      const s = tex(txt(c, r));
      return bests[c.k] !== undefined && r[c.k] === bests[c.k] ? `\\textbf{${s}}` : s;
    }).join(' & ') + ' \\\\').join('\n');
    const out = `% \\usepackage{booktabs}\n\\begin{table}[t]\n  \\centering\n  \\small\n` +
      `  \\caption{${tex(spec.caption || spec.title || '')}}\n  \\label{tab:${id}}\n` +
      `  \\begin{tabular}{${align}}\n    \\toprule\n    ${cols.map(c => tex(c.label)).join(' & ')} \\\\\n    \\midrule\n${body}\n` +
      `    \\bottomrule\n  \\end{tabular}\n\\end{table}`;
    Hub.showText(`${spec.title} — LaTeX`, [{label: T('LaTeX (booktabs) — best values in bold'), text: out}]);
  },

  download(name, content, type) {
    const blob = content instanceof Blob ? content : new Blob([content], {type: `${type};charset=utf-8`});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  },

  // ── GRAFİK ──────────────────────────────────────────
  chart(id, title, build, opts = {}) {
    this._pending[id] = {title, build, opts};
    return `<div class="rt-block rt-chart">
      <div class="rt-head"><span class="rt-title">${Hub.esc(title)}</span>
        <span class="rt-actions">
          <button type="button" class="btn sm" onclick="RT.png('${id}')" title="${T('High-resolution PNG on a white background (for papers)')}">PNG</button>
          <button type="button" class="btn sm" onclick="RT.chartCsv('${id}')" title="${T('Chart data (CSV)')}">CSV</button>
        </span></div>
      <div class="rt-canvas" style="height:${opts.height || 300}px"><canvas id="rtc-${id}"></canvas></div>
      ${opts.note ? `<p class="muted rt-note">${opts.note}</p>` : ''}</div>`;
  },
  _themed(cfg, t, paper) {
    const o = cfg.options = cfg.options || {};
    o.maintainAspectRatio = false;
    o.plugins = o.plugins || {};
    o.plugins.legend = {labels: {color: t.text, font: {family: t.font, size: paper ? 13 : 11}, boxWidth: 12}, ...(o.plugins.legend || {})};
    if (o.plugins.legend.labels) o.plugins.legend.labels.color = t.text;
    if (o.plugins.title) o.plugins.title = {...o.plugins.title, color: t.title, font: {family: t.font, size: paper ? 15 : 12}};
    for (const ax of Object.values(o.scales || {})) {
      ax.ticks = {color: t.text, font: {family: t.font, size: paper ? 12 : 10}, ...(ax.ticks || {}), color: t.text};
      ax.grid = {color: t.grid, ...(ax.grid || {}), color: t.grid};
      if (ax.title) ax.title = {...ax.title, color: t.text, font: {family: t.font, size: paper ? 13 : 11}};
    }
    return cfg;
  },
  mount() {
    for (const [id, p] of Object.entries(this._pending)) {
      const cv = document.getElementById(`rtc-${id}`);
      if (!cv) continue;
      this._charts[id]?.destroy();
      const cfg = this._themed(p.build(this.SCREEN), this.SCREEN, false);
      cfg.options.responsive = true;
      this._charts[id] = new Chart(cv, cfg);
      this._charts[id]._rt = p;
    }
    this._pending = {};
  },
  png(id) {
    const live = this._charts[id];
    if (!live) return;
    const p = live._rt, w = 1400, h = Math.round(w * live.height / Math.max(live.width, 1));
    const host = document.createElement('div');
    host.style.cssText = `position:fixed;left:-20000px;top:0;width:${w}px;height:${h}px`;
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    host.appendChild(cv);
    document.body.appendChild(host);
    const cfg = this._themed(p.build(this.PAPER), this.PAPER, true);
    Object.assign(cfg.options, {responsive: false, animation: false, devicePixelRatio: 2});
    cfg.plugins = [...(cfg.plugins || []), {id: 'rtBg', beforeDraw: c => {
      const x = c.ctx; x.save(); x.fillStyle = '#ffffff'; x.fillRect(0, 0, c.width, c.height); x.restore(); }}];
    const ch = new Chart(cv, cfg);
    cv.toBlob(b => { this.download(`${id}.png`, b); ch.destroy(); host.remove(); }, 'image/png');
  },
  chartCsv(id) {
    const ch = this._charts[id];
    if (!ch) return;
    const {labels = [], datasets = []} = ch.config.data;
    const q = s => /[",\n]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : String(s ?? '');
    let lines;
    if (datasets.some(d => d.data.some(v => v && typeof v === 'object'))) {           // scatter: nokta listesi
      lines = ['series,label,x,y', ...datasets.flatMap(d => d.data.map(pt => [d.label, pt.label ?? '', pt.x, pt.y].map(q).join(',')))];
    } else {
      lines = [['label', ...datasets.map(d => d.label)].map(q).join(','),
               ...labels.map((l, i) => [l, ...datasets.map(d => d.data[i] ?? '')].map(q).join(','))];
    }
    this.download(`${id}.csv`, '\ufeff' + lines.join('\n'), 'text/csv');
  },
};
