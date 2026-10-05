# WebRuleBench — Web Uygulaması Kullanım Kılavuzu

Ground truth toplama, onaylama ve LLM değerlendirme için Flask web uygulaması. Her bölümün **?** yardımı formülleri ve kuralları açıklar.

---

## Kurulum ve çalıştırma

Gereksinimler: Python 3.10+.

```bash
# proje kökünde
pip install -r requirements.txt

# ilk admin hesabı (token yalnızca bir kez ekrana yazılır)
webrulebench users create-admin <kullanıcı>

# çalıştır
./run.sh                      # ya da: webrulebench serve
```

Tarayıcıda aç: **http://127.0.0.1:5001** — kullanıcı adı ve token ile giriş yapılır; giriş bilgisi tarayıcıda hatırlanır.
Arayüz varsayılan olarak İngilizcedir; üst menüdeki **EN / TR** düğmesiyle Türkçeye geçilir (seçim hatırlanır).

Diğer kullanıcılar uygulamadaki **👥 Kullanıcılar** sayfasından (admin) ya da komut satırından eklenir:

```bash
webrulebench users create <kullanıcı> [--role user|admin]
webrulebench users reset-token <kullanıcı>     # token unutulduysa
webrulebench users list
```

---

## İş akışı — altı bölüm

Ana sayfa bölümlerin kartlarını gösterir; üst menü her sayfada ortaktır. Her sayfanın başlığındaki **?** o bölümün yardımını açar. 🔒 işaretli işlemler yalnızca admin içindir.

### 1. Veri Toplama
- Site listesi; ülkeye göre filtre ("⚠ Bilgisi eksik" ülke bilgisi olmayan siteleri gösterir).
- 🔒 Site ekle / düzenle: ad, URL, ülke (listeden ya da yeni ülke — ISO kodu, kıta, dil), not.
- 🔒 Sayfa ekle, yeniden indir, sil; **⚡ Toplu Sayfa Ekle**: bir listing sayfasından CSS selector ile linkleri çıkarıp seçilenleri indirir.
- Sayfa türleri dosya adından anlaşılır: `homepage.html`, `listing_NNN.html`, `article_NNN.html`.

### 2. Şablon & Prompt
- Şablonlar (`article`, `listing`, `product`): alanlar, tip (`text`, `date`, `image`, `url`, `list`, `price`), metrik (`rouge`, `jaccard`, `exact_match`), zorunluluk, birleştirme (`merge`). 🔒 Düzenleme.
- **Prompt'lar**: her şablon ve kural dili (CSS / XPath / Regex) için otomatik prompt (değiştirilemez) ve kullanıcıların eklediği varyantlar. Varyantı herkes ekler; yalnızca sahibi ya da admin düzenler. Kullanıcı prompt'u `{skeleton}` içermelidir.

### 3. Annotation
Siteyi seç → çalışma ekranı açılır (**← Siteler** ile geri dönülür).

1. Üstten bir sayfa seç (sayfa önizlemede açılır).
2. Sayfayı bir **layout**'a ata. Layout, aynı HTML yapısındaki sayfa grubudur (ör. standart haber, köşe yazısı, galeri); bir kural seti bütün sayfalarına uygulanır. Uygun layout yoksa 🔒 admin şablondan yeni layout oluşturur. Bozuk / içeriksiz sayfalar için **Skip this page**.
3. Layout'un her alanı için kuralını yaz — üç sekme:
   - **CSS**: elle yaz ya da sayfada tıklayarak seç. **Test** ile sonucu gör.
   - **XPath**: CSS'ten otomatik üretilir (sayfada CSS ile aynı metni veren aday önerilir); elle düzenlenebilir.
   - **Regex**: uzman girdisi; istenirse CSS'ten üretilir (REGEXN — layout'un birkaç sayfasında doğrulanır).
4. **💾 Kaydet** — kurallar yalnızca senin annotation dosyana (`annotations/<site>/<kullanıcı>.json`) yazılır.
5. **⚡ Toplu Sayfa Atama**: layout'un kurallarını atanabilecek bütün sayfalarda test et, uygun olanları **✓ Seçilenleri Ata** ile topluca ata.

CSS örnekleri:

```css
h1.article-title           → class ile
h1#main-title              → id ile
div.content p              → iç içe eleman
div[data-type="article"]   → öznitelik değeri
div[class*="content"]      → class içinde "content" geçenler
h2 a, h3 a                 → alternatifler (virgülle)
```

İpuçları: benzer yapıdaki sayfaları aynı layout'a ata; listing sayfaları için ayrı layout kullan; makaleye özgü numara içeren id/class'lardan kaçın (diğer sayfalarda tutmaz).

### 4. Ground Truth Onayı
Site → layout → derleme sayfası. Her annotatörün kuralları yan yana; kural dilleri ayrı sekmelerde.
- **Katman 1 (kural uyumu)**: alan bazında aynı (normalize) kuralı yazan annotatör çiftlerinin oranı ve en sık yazılan kural önerisi (✓ ≥ 0.6, ~ 0.4–0.6, ! < 0.4). Fleiss κ ve Krippendorff α: **Rapor → Annotation & GT**.
- **Katman 2 (K2)**: örnek sayfada her kuralın çıkardığı metnin EM / Jaccard / ROUGE skorları; en yüksek ROUGE-L önerisi.
- 🔒 Admin hangi kural dillerinin GT'ye dahil olacağını seçer, önerileri uygular ya da elle değiştirir ve **💾 GT Kaydet** ile `ground_truth/approved/<site>.json`'a yazar. Diğer kullanıcılar sayfayı salt-okunur görür.
- Liste sayfalarında durum: **onaylı**, **güncelleme var** (onaydan sonra annotation değişmiş), **GT yok**.

### 5. LLM Değerlendirme
- **⚡ Hızlı test**: tek layout, kaydedilmez — prompt denemek için.
- **Yeni deney / ⚖ Karşılaştırmalı deney**: model(ler), kural dil(ler)i (CSS, XPath, Regex, LLM CSS → REGEXN), temizleme stratejisi, şablon başına prompt, örnek sayfa seçimi ve layout kapsamı. Layout başına tek LLM çağrısı yapılır; kurallar layout'un bütün GT sayfalarında skorlanır (örnek sayfa ve diğer sayfalar ayrı).
- Deney ayrıntısı, grup sayfası (sıralama, ısı haritası, layout bazında, **cross-check**) ve ikili karşılaştırma. Deney iptal edilebilir ve kaldığı yerden sürdürülebilir.
- **⚙ LLM Modelleri**: backend'ler, Ollama'da yüklü modeller, model parametreleri, bağlantı testi. 🔒 Düzenleme; API anahtarı `data/.env`'e yazılır.

### 6. Rapor & Dışa Aktarma
Sekmeler: 📦 Veri seti · ✍ Annotation & GT · 🤖 LLM sonuçları · ⬇ Dışa aktarma · 🧾 Denetim kaydı (🔒).
- **Annotation & GT**: kullanıcı ilerlemesi, GT durumu, alan bazında Fleiss κ ve **▶ Hesapla** ile içerik düzeyinde uyum: her annotatörün kuralı ≥2 annotatörlü layout'ların bütün GT sayfalarında çalıştırılır; alan bazında Krippendorff α, annotatör çiftleri ve layout bazında uyum (sonuç dosyalar değişene kadar saklanır).
- Her tablo **CSV / LaTeX / MD**, her grafik **PNG / CSV** olarak alınır.
- Onaylı GT: JSONL, CSV, HuggingFace JSONL ve dataset card; deneyler için tekrarlanabilirlik manifesti.

---

## Sorun giderme

- **Port meşgul**: başka bir portla başlat: `WRB_PORT=5003 ./run.sh`.
- **Sayfa önizlemede boş görünüyor**: bazı sayfalar iframe'de yüklenmez; dosyayı doğrudan aç: `data/dataset/raw/<site>/article_001.html`.
- **Sayfa indirilemiyor**: JavaScript ile oluşan sayfalar için `playwright install chromium`.
- **LLM bağlantı hatası**: ⚙ LLM Modelleri'nde **⚡ Test**; Ollama için `ollama serve` çalışıyor mu ve model yüklü mü (`ollama list`)?
- **Admin token'ı unutuldu**: `webrulebench users reset-token <kullanıcı>`.
