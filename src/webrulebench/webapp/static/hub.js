// Hub + bölüm sayfaları için ortak yardımcılar (oturum, site seçici, derin link).
// Oturum index.html ile ortaktır: aynı Flask session'ı ve aynı localStorage
// anahtarları (llmwb_username / llmwb_token) kullanılır.

const Hub = {
  me: null,
  _sites: null,
  _ready: null,

  isAdmin() { return this.me?.role === 'admin'; },

  // /annotate?site=...&open=...  — index.html içindeki _handleDeepLink() okur
  annotateUrl(params = {}) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v); });
    const s = q.toString();
    return '/annotate' + (s ? '?' + s : '');
  },

  go(params) { location.href = this.annotateUrl(params); },

  ready() {
    if (!this._ready) this._ready = this._init();
    return this._ready;
  },

  async _init() {
    const res  = await fetch('/api/me');
    const data = await res.json();
    if (data.logged_in) {
      this.me = data;
    } else {
      const u = localStorage.getItem('llmwb_username');
      const t = localStorage.getItem('llmwb_token');
      if (u && t && await this._postLogin(u, t)) {
        // _postLogin this.me'yi doldurdu
      } else {
        document.getElementById('hubLogin').classList.add('open');
        const saved = localStorage.getItem('llmwb_username');
        if (saved) document.getElementById('hubLoginUser').value = saved;
        await new Promise(resolve => { this._loginResolve = resolve; });
      }
    }
    this._renderUser();
    this.applyRoleGates();
    return this.me;
  },

  async _postLogin(username, token) {
    const r = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username, token}),
    });
    const d = await r.json();
    if (!d.success) return d.error || T('Login failed');
    this.me = {logged_in: true, username: d.username, role: d.role};
    return true;
  },

  async login() {
    const username = document.getElementById('hubLoginUser').value.trim().toLowerCase();
    const token    = document.getElementById('hubLoginToken').value.trim();
    const errEl    = document.getElementById('hubLoginErr');
    if (!username || !token) { errEl.textContent = T('Username and token are required'); return; }
    const ok = await this._postLogin(username, token);
    if (ok !== true) { errEl.textContent = ok; return; }
    localStorage.setItem('llmwb_username', username);
    localStorage.setItem('llmwb_token', token);
    document.getElementById('hubLogin').classList.remove('open');
    this._loginResolve?.();
  },

  async logout() {
    await fetch('/logout', {method: 'POST'});
    localStorage.removeItem('llmwb_username');
    localStorage.removeItem('llmwb_token');
    location.reload();
  },

  _renderUser() {
    const el = document.getElementById('hubUser');
    if (!this.me) { el.innerHTML = ''; return; }
    el.innerHTML = `
      ${this.isAdmin() ? `<a class="btn sm" href="/settings/users" title="${this.esc(T('Users — accounts, roles, tokens'))}">👥</a>` : ''}
      <a class="btn sm" href="/settings/llm-models" title="${this.esc(T('LLM Models — backend and model settings'))}">⚙<span class="wide-only"> ${T('LLM Models')}</span></a>
      <span>👤 ${this.esc(this.me.username)} ${this.isAdmin() ? '<span class="role-tag">A</span>' : ''}</span>
      <button type="button" class="btn sm" onclick="Hub.logout()">${T('Log out')}</button>`;
  },

  // data-admin işaretli öğeler admin değilse kilitlenir
  applyRoleGates(root = document) {
    root.querySelectorAll('[data-admin]').forEach(el => {
      if (this.isAdmin()) return;
      el.classList.add('locked');
      el.title = T('Admin only');
      if (el.tagName === 'A') el.removeAttribute('href');
    });
  },

  async sites() {
    if (!this._sites) {
      const res = await fetch('/api/sites');
      this._sites = (await res.json()).sites || [];
    }
    return this._sites;
  },

  async site(domain) {
    const res = await fetch(`/api/site/${encodeURIComponent(domain)}`);
    return res.json();
  },

  siteStatus(s) {
    if (s.gt_exported)                          return 'gt';
    if (s.ready || s.total_annotated >= 5)      return 'ready';
    if ((s.total_annotated || s.annotated) > 0) return 'partial';
    return 'empty';
  },

  // Aranabilir site seçici. Seçilen domain URL'de (?site=) tutulur ki
  // bölümler arası geçişte ve yenilemede kaybolmasın.
  async sitePicker(container, onChange) {
    const sites = await this.sites();
    const id = 'sitelist-' + Math.random().toString(36).slice(2, 8);
    container.innerHTML = `
      <input type="search" class="picker" list="${id}" placeholder="${this.esc(T('Search and select a site ({n} sites)...', {n: sites.length}))}">
      <datalist id="${id}">
        ${sites.map(s => `<option value="${this.esc(s.domain)}">${this.esc(s.name || '')} · ${this.esc(s.country || '')}</option>`).join('')}
      </datalist>`;
    const input = container.querySelector('input');
    const domains = new Set(sites.map(s => s.domain));
    const pick = () => {
      const d = input.value.trim();
      if (!domains.has(d)) return;
      const url = new URL(location.href);
      url.searchParams.set('site', d);
      history.replaceState(null, '', url);
      onChange(d);
    };
    input.addEventListener('change', pick);
    const initial = new URLSearchParams(location.search).get('site');
    if (initial && domains.has(initial)) { input.value = initial; pick(); }
    return input;
  },

  // Başlık + bölümler ({label, text}) içeren salt okunur metin penceresi (prompt görüntüleme vb.)
  showText(title, parts) {
    document.getElementById('hubTextModal')?.remove();
    const el = document.createElement('div');
    el.id = 'hubTextModal';
    el.className = 'modal-overlay open';
    el.innerHTML = `<div class="modal-box" role="dialog" aria-modal="true" style="width:min(900px,100%)">
      <div class="modal-head"><div class="panel-title">${this.esc(title)}</div>
        <button type="button" class="icon-btn" aria-label="${T('Close')}">✕</button></div>
      <div class="modal-content">${parts.map(p => `
        <div class="lbl">${this.esc(p.label)} <span class="muted" style="text-transform:none;letter-spacing:0">${T('{n} characters', {n: p.text.length.toLocaleString(LOCALE)})}</span>
          <button type="button" class="btn sm" data-copy style="margin-left:auto">📋 ${T('Copy')}</button></div>
        <pre class="cli" style="max-height:46vh;white-space:pre-wrap">${this.esc(p.text)}</pre>`).join('')}</div></div>`;
    const close = () => el.remove();
    el.addEventListener('click', e => { if (e.target === el) close(); });
    el.querySelector('.icon-btn').onclick = close;
    el.querySelectorAll('[data-copy]').forEach((b, i) => b.onclick = () =>
      navigator.clipboard?.writeText(parts[i].text).then(() => this.toast(T('Copied'))));
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(el);
  },

  // Şablonun prompt'unu göster: pid 'auto' (ya da boş) → otomatik prompt (rule dili için), aksi halde deneme prompt'u
  async showPrompt(tid, ruleType, pid) {
    const d = await (await fetch(`/api/templates/${encodeURIComponent(tid)}/prompts`)).json();
    let name, sys, usr;
    if (!pid || pid === 'auto') {
      const a = d.auto?.[ruleType];
      if (!a) { this.toast(T('Prompt not found'), 'err'); return; }
      [name, sys, usr] = [`${T('Automatic prompt')} · ${tid} · ${ruleType}`, a.system, a.user];
    } else {
      const p = (d.prompts || []).find(x => x.id === pid);
      if (!p) { this.toast(T('Prompt not found'), 'err'); return; }
      [name, sys, usr] = [`${p.name} · ${tid} · ${p.rule_type}`, p.system_prompt, p.user_prompt];
    }
    this.showText(name, [{label: T('System prompt'), text: sys}, {label: T('User prompt ({skeleton} is replaced by the page skeleton)'), text: usr}]);
  },

  openHelp()  { document.getElementById('helpModal')?.classList.add('open'); },
  closeHelp() { document.getElementById('helpModal')?.classList.remove('open'); },

  toast(msg, type = 'ok') {
    const el = document.getElementById('hubToast');
    el.textContent = msg;
    el.className = `toast show ${type}`;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
  },

  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  },
};

document.addEventListener('DOMContentLoaded', () => Hub.ready());
document.addEventListener('keydown', e => { if (e.key === 'Escape') Hub.closeHelp(); });
