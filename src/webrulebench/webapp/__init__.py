"""
webapp — WebRuleBench web uygulaması (Flask).

  core.py      uygulama nesnesi, yollar, oturum/yetki, dil, ortak yardımcılar
  routes/      bölüm başına blueprint'ler (auth, users, pages, data, templates, annotation,
               groundtruth, evaluation, llm, reports)
  app.py       blueprint'leri kaydeder ve sunucuyu başlatır:  webrulebench serve  (python -m webrulebench.webapp)
  templates/ static/ i18n/   arayüz
  manage_users.py            komut satırından kullanıcı yönetimi
"""
