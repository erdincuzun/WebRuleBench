// Arayüz dili — tarayıcı tarafı. Kaynak metinler İngilizcedir; window.I18N
// (/i18n/<dil>.js) {"İngilizce": "çeviri"} sözlüğüdür. Sözlükte olmayan metin
// İngilizce kalır. Yer tutucular: T('{n} pages', {n: 3}).
window.LANG   = document.documentElement.lang || 'en';
window.I18N   = window.I18N || {};
window.LOCALE = ({en: 'en-GB', tr: 'tr-TR'})[window.LANG] || 'en-GB';

// İngilizce kaynakta yer tutucu 1 ise ardındaki çoğul isim tekile çevrilir
// ("{n} pages" → "1 page", "{n} required fields" → "1 required field"); i18n.py ile aynı kural.
const _SING_EXCEPT = new Set(['is', 'has', 'was', 'this', 'bus', 'gas', 'ms', 's']);
function _singular(w) {
  const lw = w.toLowerCase();
  if (_SING_EXCEPT.has(lw) || w.length < 3) return w;
  if (lw.endsWith('ies')) return w.slice(0, -3) + 'y';
  if (/(ch|sh|x|ss)es$/.test(lw)) return w.slice(0, -2);
  if (lw.endsWith('s') && !lw.endsWith('ss')) return w.slice(0, -1);
  return w;
}
function _englishPlurals(s, params) {
  for (const [k, v] of Object.entries(params)) {
    if (String(v).trim() !== '1') continue;
    s = s.replace(new RegExp(`\\{${k}\\} ([A-Za-z-]+)(\\s*)([A-Za-z-]+)?(\\s*)([A-Za-z]+)?`), (m, w1, sp, w2 = '', sp2 = '', w3 = '') => {
      const s1 = _singular(w1);
      if (s1 !== w1) return `{${k}} ${s1}${sp}${w2 === 'are' ? 'is' : w2}${sp2}${w3}`;
      const s2 = w2 ? _singular(w2) : w2;
      if (s2 !== w2) return `{${k}} ${w1}${sp}${s2}${sp2}${w3 === 'are' ? 'is' : w3}`;
      return m;
    });
  }
  return s;
}

function T(s, params) {
  let r = window.I18N[s];
  if (r === undefined) r = params ? _englishPlurals(s, params) : s;
  if (params) r = r.replace(/\{(\w+)\}/g, (m, k) => (params[k] ?? m));
  return r;
}

function setLang(lang) {
  document.cookie = `lang=${lang};path=/;max-age=31536000;samesite=lax`;
  location.reload();
}

// TR modunda CSS `text-transform: uppercase` Türkçe kuralını kullanır (i → İ). Bu Türkçe
// arayüz metinleri için doğrudur ("SEÇİLİ SİTE") ama veri ve İngilizce teknik terimleri
// bozar ("ARTİCLE", "20MİNUTOS.ES"). Büyük harfle gösterilen öğelerde metin Türkçe bir
// arayüz metni değilse öğeye lang="en" verilir; DOM değiştikçe yeniden uygulanır.
(function () {
  if (window.LANG !== 'tr') return;
  const SEL = 'th, .stat-label, .site-stat-label, .form-row label, .form-row .form-field, .plist-group, .lbl, ' +
              '.help-content h3, .mcp-label, .form-label, .panel-title, [style*="uppercase"]';
  const TR_CHARS = /[çğıöşüÇĞÖŞÜİ]/;
  let values = null, pending = false;
  const fix = () => {
    pending = false;
    // yalnızca İngilizceden farklı çevrilmiş metinler Türkçe sayılır ("Listing" → "Listing" teknik terimdir)
    values = values || new Set(Object.entries(window.I18N).filter(([k, v]) => k !== v).map(([, v]) => String(v).trim()));
    document.querySelectorAll(SEL).forEach(el => {
      const t = el.textContent.trim();
      if (!t) return;
      const turkish = TR_CHARS.test(t) || values.has(t);
      if (turkish) { if (el.getAttribute('lang') === 'en') el.removeAttribute('lang'); }
      else if (el.getAttribute('lang') !== 'en') el.setAttribute('lang', 'en');
    });
  };
  const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(fix); } };
  document.addEventListener('DOMContentLoaded', () => {
    fix();
    new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true, characterData: true});
  });
})();
