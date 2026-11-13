"""Seslendirme ve video süresi seçenekleri (panelde kullanıcıya sunulur)."""
from . import config, db

# rate/pitch: canlı anlatım için hafif hızlandırılmış ve tizleştirilmiş ayarlar
VOICES = {
    # Yerel Türkçe model (tools/tts-tr, Pocket TTS Turkish, CC BY 4.0: açıklamada kaynak belirtilir)
    **{f"dogal_{g[0]}{n}": {"engine": "pocket", "name": f"{g}_{n}", "emotion": "mutlu", "rate": 0, "pitch": None,
                           "label": f"Doğal {'Kadın' if g == 'female' else 'Erkek'} {n}",
                           "desc": f"Doğal Türkçe {'kadın' if g == 'female' else 'erkek'} sesi (yerel model)"}
       for g in ("female", "male") for n in (1, 2, 3)},
    "emel": {"name": "tr-TR-EmelNeural", "label": "Emel", "desc": "Türkçe, kadın, sıcak ve canlı",
             "rate": 8, "pitch": "+2Hz"},
    "ahmet": {"name": "tr-TR-AhmetNeural", "label": "Ahmet", "desc": "Türkçe, erkek, net ve enerjik",
              "rate": 8, "pitch": "+1Hz"},
    "ava": {"name": "en-US-AvaMultilingualNeural", "label": "Ava", "desc": "Kadın, çok ifadeli (hafif aksan olabilir)",
            "rate": 0, "pitch": "+0Hz"},
    "emma": {"name": "en-US-EmmaMultilingualNeural", "label": "Emma", "desc": "Kadın, neşeli, sohbet tonunda (hafif aksan olabilir)",
             "rate": 0, "pitch": "+0Hz"},
    "brian": {"name": "en-US-BrianMultilingualNeural", "label": "Brian", "desc": "Erkek, samimi ve rahat (hafif aksan olabilir)",
              "rate": 0, "pitch": "+0Hz"},
    "andrew": {"name": "en-US-AndrewMultilingualNeural", "label": "Andrew", "desc": "Erkek, sıcak, güven veren (hafif aksan olabilir)",
               "rate": 0, "pitch": None},  # bu ses pitch ayarını kabul etmiyor
}
if not config.POCKET_EXE.exists():  # yerel model kurulu değilse (Linux temel kurulum) listede gösterme
    VOICES = {key: v for key, v in VOICES.items() if v.get("engine") != "pocket"}
DEFAULT_VOICE = "emel"
ALIASES = {"female": "emel", "male": "ahmet"}  # eski kayıtlar için
RATE_ADJUST = {"normal": 0, "slower": -10, "faster": 10}

SAMPLE_TEXT = "Biliyor muydun? Ahtapotların tam üç kalbi var! Üstelik kanları mavi. Hadi, bu tuhaf canlıyı birlikte tanıyalım!"

# kelime aralıkları ölçülen ~2 kelime/sn (Emel, +%8) üzerinden; aşılırsa üretimde ses hızlandırılır
LENGTHS = {
    "short": {"label": "Kısa (~30 sn)", "words": (50, 62), "max_seconds": 35},
    "medium": {"label": "Orta (~45 sn)", "words": (72, 90), "max_seconds": 50},
    "long": {"label": "Uzun (en fazla 1 dk)", "words": (95, 115), "max_seconds": 60},
}
DEFAULT_LENGTH = "medium"

# Üretim yöntemi: yerel (Claude çizer, seçilen ses okur; ücretsiz) veya Gemini Omni (gerçek video, ücretli)
QUALITIES = {
    "local": {"label": "Yerel · ücretsiz", "desc": "Sahneleri bilgisayarındaki Claude çizer, seçtiğin ses okur. API anahtarı gerekmez."},
    "omni": {"label": "Gemini API · yüksek kalite", "desc": "Google Gemini gerçek hareketli video ve ses üretir. Ücretli, API anahtarı gerekir."},
}
DEFAULT_QUALITY = "local"


def resolve(voice_id: str | None) -> tuple[str, dict]:
    voice_id = ALIASES.get(voice_id or "", voice_id or "")
    if voice_id not in VOICES:
        voice_id = current_voice()
    return voice_id, VOICES[voice_id]


def current_voice() -> str:
    v = db.get_setting("voice", DEFAULT_VOICE)
    return v if v in VOICES else DEFAULT_VOICE


def use_cuma() -> bool:
    """Konudan üretilen videolarda Cuma Robot köşede anlatıcı olsun mu."""
    return db.get_setting("use_cuma", "1") == "1"


def current_quality() -> str:
    q = db.get_setting("quality", DEFAULT_QUALITY)
    return q if q in QUALITIES else DEFAULT_QUALITY


def current_length() -> dict:
    return LENGTHS.get(db.get_setting("video_length", DEFAULT_LENGTH), LENGTHS[DEFAULT_LENGTH])


POCKET_CREDIT = "Seslendirme: Pocket TTS Turkish (Wite Tech, CC BY 4.0)"


def credit(voice_id: str | None) -> str:
    """Seçilen sesin lisansı kaynak gösterilmesini istiyorsa açıklamaya eklenecek satır."""
    return POCKET_CREDIT if resolve(voice_id)[1].get("engine") == "pocket" else ""


def rate_string(percent: int) -> str:
    return f"{percent:+d}%"
