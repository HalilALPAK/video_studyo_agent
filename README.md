<p align="center">
  <img src="assets/narrator/cuma_face.png" width="160" alt="Cuma Robot">
</p>

<h1 align="center">Video Stüdyosu</h1>

<p align="center">
  Konunu yaz <b>Cuma Robot</b> anlatsın ya da istediğin videoyu kendi cümlelerinle iste.<br>
  Kısa dikey videoları ücretsiz yerel olarak ya da Gemini ile üretir, onayından sonra<br>
  YouTube, TikTok ve Instagram'a yükler.
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
| **Claude Code girişi** veya `ANTHROPIC_API_KEY` | Konuları planlar, senaryoları yazar, tarifini sahnelere böler; yerel üretimde sahneleri de çizer. |
| **Google Chrome** | Sosyal medya hesaplarını bağlar, videoları yükler, yerel üretimde çizimleri görüntüye çevirir. |
| **Gemini API anahtarı** *(isteğe bağlı)* | Sadece "Gemini API" yöntemini seçersen. [AI Studio](https://aistudio.google.com/apikey)'dan alınır, hesapta faturalandırma açık olmalı. |

## Nasıl çalışır

Panel dört adımdan oluşur:

1. **Kanal:** Kanal adını ve video konularını kaydet. Sadece tarifle video yapacaksan atlayabilirsin.
2. **İsim:** Kullanıcı adı YouTube, TikTok ve Instagram'da taranır; alınmışsa benzerleri önerilir.
3. **Video üret:** Tüm üretim burada, tek bir formdan yapılır. Hazır olan videoyu izle; beğendiysen onayla, beğenmediysen ne değişsin yaz, sadece ilgili kısım yeniden üretilir.
4. **Yayın:** Hesaplarını bir kez bağla, onayladığın videoları tek tuşla yükle.

### Üretim formundaki seçimler

**Ne tür video?**

| | Konularımdan | Kendi tarifimden |
|---|---|---|
| **Ne yazarsın** | Hiçbir şey; 1. adımdaki konular kullanılır | İstediğin videonun tarifi |
| **Senaryo** | Claude yeni bir alt başlık seçer, senaryoyu yazar | Claude tarifini sahnelere böler |
| **Anlatıcı** | Seçenek: köşede konuşan Cuma Robot ya da görünmeyen ses | Yok; seslendirme ancak tarifte istersen olur |

**Nasıl üretilsin?**

| | Yerel · ücretsiz | Gemini API · yüksek kalite |
|---|---|---|
| **Görüntü** | Claude'un çizdiği çizgi film sahneleri | Gemini'nin ürettiği gerçek hareketli video |
| **Ses** | Listeden seçtiğin Türkçe ses | Gemini'nin kendi sesi |
| **Cuma Robot** | Köşede konuşan rozet | Köşede, sahneyle birlikte canlandırılır |
| **Ücret** | Yok | Saniye başına (aşağıda) |

## Gemini maliyeti

Sadece Gemini yöntemi ücretlidir. Video başına tahmini ücret (720p, yaklaşık 0,07 $/sn, Kasım 2026 fiyatları):

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

API anahtarın, bağlı hesapların ve videoların indirme paketlerinde bulunmaz; güncelleme yaptığında korunur. Senaryo ve çizim istekleri Anthropic'e, seslendirme metinleri (yerel yöntemde) Microsoft'un ücretsiz ses servisine, Gemini yönteminde metinler ve (Cuma açıksa) `cuma.jpeg` Google'a gönderilir.

## Bilinen sınırlar

- Yerel yöntemde Cuma Robot'un ağzı ses yüksekliğine göre açılıp kapanan basit bir animasyondur; gerçekçi dudak senkronu Gemini yönteminde olur.
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
  agents/producer.py       Yerel video üretimi (Claude çizimleri, seslendirme, altyazı)
  agents/gemini_video.py   Gemini video üretimi (Gemini Omni Flash)
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
