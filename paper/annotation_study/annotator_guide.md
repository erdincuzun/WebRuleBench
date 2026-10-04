# Annotatör Uyumu Çalışması — Annotatör Kılavuzu

Bu çalışmada aynı sayfa düzenleri (layout) için birden fazla annotatörün **birbirinden bağımsız** olarak
yazdığı çıkarım kuralları karşılaştırılır; uyum Fleiss κ (kural düzeyi) ve içerik benzerliği (ROUGE / Jaccard)
ile ölçülür ve SoftwareX makalesinde raporlanır. Sonuçların anlamlı olması için **bağımsızlık** en önemli kuraldır.

## 1. Kapsam: 10 site, her birinden "Article 1" layout'u

Layout'lar tanımlıdır ve sayfalar layout'lara atanmıştır; yeni layout oluşturmanız ya da sayfa ataması yapmanız
gerekmez. Her layout için **kendi kurallarınızı** yazıp kaydedeceksiniz.

Seçim ölçütü: onaylı GT'si olan ve mevcut bir annotatör kuralı bulunan 70 "Article 1" layout'u arasından
**GT sayfası en fazla olan 10 layout** (eşitlikte alfabetik sıra; seçim `sample.json` dosyasındadır).
Böylece her layout'un kuralları çok sayıda sayfada sınanır.

| # | Site | Layout | Ülke | Dil | GT sayfası |
|---|---|---|---|---|---|
| 1 | 525.az | layout-1 · Article 1 | Azerbaijan | az | 49 |
| 2 | abante.com.ph | layout-1 · Article 1 | Philippines | tl | 45 |
| 3 | akipress.com | layout-1 · Article 1 | Kyrgyzstan | en | 44 |
| 4 | alayam.com | layout-1 · Article 1 | Bahrain | ar | 42 |
| 5 | 20minutos.es | layout-2 · Article 1 | Spain | es | 41 |
| 6 | abendzeitung.de | layout-1 · Article 1 | Germany | de | 41 |
| 7 | aljazeera.com | layout-2 · Article 1 | Qatar | en | 41 |
| 8 | 24chasa.bg | layout-1 · Article 1 | Bulgaria | bg | 40 |
| 9 | adevarul.ro | layout-1 · Article 1 | Romania | ro | 40 |
| 10 | agenciabrasil.ebc.com.br | layout-2 · Article 1 | Brazil | pt | 40 |

Tahmini süre: layout başına 10–15 dakika, toplam 2–2,5 saat. İstediğiniz sırayla ve birkaç oturumda yapabilirsiniz.
Yalnızca bu layout'larla çalışın; sitenin diğer layout'larına (listing vb.) kural yazmanız gerekmez.

## 2. Bağımsızlık kuralları (önemli)

- **"👤 Başkasından Al"** düğmesini kullanmayın (başka bir annotatörün kurallarını kopyalar).
- Çalışma bitene kadar **Ground Truth Onayı** bölümünü ve **Rapor → Annotation & GT** sekmesini açmayın
  (diğer annotatörlerin kurallarını ve uyumu gösterirler).
- Kurallarınızı başka biriyle konuşmayın; takıldığınız yerde bu kılavuza göre kendi kararınızı verin ve not alın.

## 3. Nasıl yapılır

1. Giriş yapın (kullanıcı adı ve token size ayrıca iletilir). Sağ üstten dili **TR** seçebilirsiniz.
2. **Annotation** bölümünden siteyi açın; üstten layout'a atanmış bir sayfa seçin (layout panelinde sayfa sayıları görünür).
3. Layout'u açın, **Kendi Annotation'ım** sekmesinde her alan için kuralı yazın:
   - **CSS** zorunludur. Elle yazabilir ya da sayfada tıklayarak seçebilirsiniz.
   - **XPath** ve **Regex** isteğe bağlıdır; bu çalışmada boş bırakabilirsiniz (karşılaştırma CSS üzerinden yapılır).
4. Her kuralı **Test** ile deneyin. Kaydetmeden önce kuralların layout'un **en az 3 farklı sayfasında**
   doğru içeriği verdiğini kontrol edin: üstten başka sayfa seçerek ya da **⚡ Toplu Sayfa Atama** penceresinde
   **Kurallar: Benim kurallarım** seçiliyken **Test Et** ile (önce kurallarınızı kaydedin). Bu pencerede **Ground truth**
   seçeneğini kullanmayın — mevcut GT kurallarının sonuçlarını gösterir ve bağımsızlığı bozar. Sayfalar zaten atanmış
   olduğundan atama yapmanız gerekmez; isterseniz kendi kurallarınızla doğruladığınız sayfaları **✓ Seçilenleri Ata** ile
   topluca onaylayabilirsiniz (atama yalnızca sizin annotation dosyanıza yazılır).
5. **💾 Kaydet**.

## 4. Alanlar ve karar kuralları

**Genel**
- Kural, layout'un **bütün sayfalarında** çalışmalı: makaleye özgü id/sınıflardan (`#post-12345`, `.article-98765`), sıra numarasına dayalı
  seçicilerden (`:nth-child(7)`) ve rastgele görünen hash sınıflarından (`.sc-f98b1ad2-0`, `.css-1x2y3z`) kaçının.
- Kısa ve okunabilir seçici tercih edin: önce anlamlı **id**, sonra anlamlı **class**, sonra `data-*` öznitelik, en son etiket yapısı.
- Alan sayfada yoksa **boş bırakın** (zorlama bir seçici yazmayın).
- Birden fazla olası öğe varsa makalenin **ana içeriğine** ait olanı seçin (kenar çubuğu, "ilgili haberler" kutusu, reklam değil).

**Article (haber sayfası)**

| Alan | Ne seçilir | Not |
|---|---|---|
| `title` * | Haberin ana başlığı | Genelde `h1`; sitenin genel adı değil |
| `body` * | Haber metninin tamamını içeren kapsayıcı | Paragrafları kapsayan en küçük öğe; paylaşım/yorum/reklam bloklarını dışarıda bırakmaya çalışın |
| `author` | Yazar adı/adları | Yalnızca ad; "Yazan:" etiketi dahil olabilir |
| `date` | Yayın tarihi | Güncelleme tarihi değil, yayın tarihi (`time` öğesi varsa onu) |
| `category` | Kategori / bölüm adı | Genelde breadcrumb ya da başlık üstü etiket |
| `images` | Haberin ana görsel(ler)i | `img` öğesi; logo, reklam, yazar fotoğrafı değil. Birden çok görsel olabilir |
| `images_caption` | Görsel altyazısı | `figcaption` vb. |
| `related_links` | Haber içindeki "ilgili haber" bağlantıları | `a` öğeleri |
| `summary` | Spot / özet paragraf | Başlığın altındaki öne çıkan giriş metni |
| `tags` | Etiketler / anahtar kelimeler | Genelde sayfa sonundaki etiket listesi |

(* zorunlu alan)

Virgülle ayrılmış alternatif seçici yazabilirsiniz (`h1.title, h1.headline`); tekil alanlarda sayfada eşleşen **ilk** alternatif kullanılır.

## 5. Not tutma

Her layout için kısa not alın (ör. "tarih iki yerde var, yayın tarihini seçtim", "summary yok"). Notlar,
anlaşmazlıkların nedenini (kılavuz belirsizliği mi, gerçek yorum farkı mı) yorumlamak için kullanılacaktır.
Notlarınızı bu klasördeki `notes_<kullanıcı>.md` dosyasına ya da e-postayla iletebilirsiniz; toplam harcadığınız süreyi de yazın.

## 6. Bilinmesi gerekenler (araştırmacı için)

- Karşılaştırılan diğer kurallar (A1) bu kılavuzdan **önce** yazılmıştır; makalede sınırlama olarak belirtilmelidir.
- Uyum, Rapor → Annotation & GT sekmesinde (alan bazında κ, düşük uyumlu alanlar) ve her layout'un GT Onayı sayfasında (K1/K2) izlenir.
