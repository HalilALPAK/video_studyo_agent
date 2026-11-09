<p align="center">
  <img src="assets/narrator/cuma_face.png" width="160" alt="Cuma Robot">
</p>

<h1 align="center">Video Stüdyosu</h1>

<p align="center">
  Konunu yaz <b>Cuma Robot</b> anlatsın ya da istediğin videoyu kendi cümlelerinle iste.<br>
  Kısa dikey videolar üretir, onayından sonra YouTube, TikTok ve Instagram'a yükler.
</p>

---

## İndir

| Sistem | Dosya | Nasıl açılır |
|---|---|---|
| **Windows 10/11** | [VideoStudyosu.exe](https://github.com/HalilALPAK/video_studyo_agent/raw/main/downloads/VideoStudyosu.exe) | Çift tıkla |
| **Ubuntu / Debian** | [video-studyosu.deb](https://github.com/HalilALPAK/video_studyo_agent/raw/main/downloads/video-studyosu.deb) | Çift tıklayıp kur, menüden "Video Stüdyosu"nu aç |
| **Diğer Linux** | [video-studyosu-linux.run](https://github.com/HalilALPAK/video_studyo_agent/raw/main/downloads/video-studyosu-linux.run) | `chmod +x video-studyosu-linux.run` ve `./video-studyosu-linux.run` |

İlk açılışta gerekli bileşenler internetten indirilir (birkaç dakika). Sonraki açılışlar anında olur ve panel tarayıcıda açılır.

> **Windows uyarısı:** Dosya imzalı olmadığı için "Windows bilgisayarınızı korudu" uyarısı çıkabilir. *Ek bilgi → Yine de çalıştır* ile açabilirsin.
>
> **Ubuntu'da çift tıklama kurulumu açmazsa:** `sudo apt install ./video-studyosu.deb`

## Başlamadan önce gerekenler

| Gereken | Ne için |
|---|---|
| **Gemini API anahtarı** | Videoları üretir. [AI Studio](https://aistudio.google.com/apikey)'dan alınır, hesapta faturalandırma açık olmalı. |
| **Claude Code girişi** veya `ANTHROPIC_API_KEY` | Konuları planlar, senaryoları yazar, promptunu sahnelere böler. |
| **Google Chrome** | Sosyal medya hesaplarını bağlar ve videoları yükler. |

## Nasıl çalışır

1. **Başla:** Kanal adını ve konularını yaz, Gemini API anahtarını gir.
2. **İsim:** Kullanıcı adı YouTube, TikTok ve Instagram'da taranır; alınmışsa benzerleri önerilir.
3. **Videolar:** Her video hazır olunca izle. Beğendiysen onayla, beğenmediysen ne değişsin yaz; sadece ilgili sahneler yeniden üretilir.
4. **Yayın:** Hesaplarını bir kez bağla, onayladığın videoları tek tuşla yükle.

Her sahneyi Gemini tek klip olarak üretir, sahne görüntüsü ve ses birlikte gelir. Seslendirmeli videolarda altyazıyı uygulama ekler.

### İki üretim yolu

| | Konudan video | Prompt ile video |
|---|---|---|
| **Ne yazarsın** | Kanal adı ve konular | İstediğin videonun tarifi |
| **Senaryo** | Claude konuyu alt başlıklara böler, senaryoyu yazar | Claude tarifini sahnelere böler |
| **Anlatıcı** | Seçenek: köşede konuşan Cuma Robot ya da görünmeyen ses | Yok; seslendirme ancak tarifte istersen olur |
| **Stil** | Kanalın çizgi film stili | Tarifte ne yazdıysan |

## Maliyet

Video başına tahmini Gemini ücreti (720p, yaklaşık 0,07 $/sn, Kasım 2026 fiyatları):

| Süre | Tahmini ücret |
|---|---|
| Kısa (~30 sn) | ≈ 2,4 $ |
| Orta (~45 sn) | ≈ 3,5 $ |
| Uzun (en fazla 1 dk) | ≈ 4,2 $ |

Panel her videonun ve ayın tahmini harcamasını gösterir; kesin tutar Google faturandadır. Hata sonrası "Tekrar dene" ve düzeltmelerde hazır klipler yeniden ücretlendirilmez. Güncel fiyatlar: [Gemini API fiyatlandırması](https://ai.google.dev/gemini-api/docs/pricing).

## Verilerin

Her şey kendi bilgisayarında kalır:

- Windows: `%LOCALAPPDATA%\VideoStudyosu`
- Linux: `~/.local/share/video-studyosu`

API anahtarın, bağlı hesapların ve videoların indirme paketlerinde bulunmaz; güncelleme yaptığında korunur. Video üretimi için metinler ve (Cuma anlatıcı açıksa) `cuma.jpeg` Google'a, senaryo istekleri Anthropic'e gönderilir.

## Bilinen sınırlar

- Google'a göre Gemini Omni'de İngilizce dışındaki diller değerlendirilmedi; Türkçe telaffuz ve klipler arası ses farklı çıkabilir.
- Her videonun tamamı yapay zekâ ile üretilir ve Gemini çıktıları görünmez SynthID filigranı taşır. Platformların yapay zekâ içeriği etiketleme kurallarına uy.
- Tarayıcıyla yükleme platformların kullanım şartlarına aykırı olabilir ve arayüzleri değişince bozulabilir.
- Kullanıcı adı taramasında TikTok ve Instagram çoğu zaman "kontrol et" döner; bağlantıdan elle bakılır.
- İstatistikler yalnızca YouTube için otomatiktir (API anahtarı ve kanal kimliği gerekir).

## Geliştiriciler için

```
agent/
  orchestrator.py          Akışı yönetir
  agents/brand.py          Kullanıcı adı taraması
  agents/planner.py        Alt başlık ve takvim
  agents/scriptwriter.py   Senaryo (Claude)
  agents/gemini_video.py   Video üretimi (Gemini Omni Flash)
  agents/reviewer.py       Onay ve düzeltme
  agents/publisher.py      Yayın
  agents/analyst.py        İstatistik
  web/                     Yerel panel (Flask, 127.0.0.1:5050)
tools/studio_upload.py     Chrome üzerinden yükleme
```

Kaynaktan çalıştırma ve günlük otomatik çalışma:

```
python -m agent panel
python -m agent daily
```

Karakter referansı proje kökündeki `cuma.jpeg` dosyasıdır; değiştirip paketleri yeniden üretmen yeterli.

Paketleri üretme (`dist/` altına yazar):

```
python tools/build_linux.py     # .deb ve .run
python tools/build_windows.py   # .exe (Windows'ta; PyInstaller, Pillow ve uv gerekir)
```
