"""Gemini Omni Flash istemcisi (Gemini API, ücretli): videonun tamamı buradan üretilir.

Cuma Robot'un yüz görselinden, sahne metnini Türkçe söylediği kısa klipler üretir. Omni kendi
sesini ve dudak hareketini birlikte üretir (dışarıdan ses verip dudak senkronu yaptırmak API'de
yok), bu yüzden bu modda seslendirme de Omni'den gelir. Her çağrının token kullanımı ve tahmini
maliyeti api_usage tablosuna yazılır; panel buradan özet gösterir.
"""
import base64
import io
import logging
import math
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageFilter

from . import config, db

log = logging.getLogger(__name__)

MODEL = "gemini-omni-1.2-flash"
# ai.google.dev/gemini-api/docs/pricing (Kasım 2026): girdi 1,50 $, video çıktısı 12 $ / 1M token;
# 720p'de saniyede 5.792 token, yani ~0,07 $/sn
PRICE_INPUT = 1.50 / 1_000_000
PRICE_OUTPUT = 12.00 / 1_000_000
TOKENS_PER_SECOND = 5792
MAX_WORDS_PER_CLIP = 28  # klip en fazla 15 sn; Türkçe ~2,3 kelime/sn
WORDS_PER_SECOND = 2.3

FACE_IMAGE = config.ROOT / "assets" / "narrator" / "cuma_face.png"
REFERENCE_IMAGE = config.ROOT / "cuma.jpeg"  # kullanıcının verdiği karakter paftası; her klipte gönderilir
PROMPT = """[# Sources <FIRST_FRAME>@Image1]
A cute, cheerful child-like robot (exactly the robot in the first frame) looks straight into the camera \
and says in Turkish, clearly and enthusiastically, with natural lip movements:
"{text}"
Static camera, the same close-up framing as the first frame for the whole clip, face centered, subtle \
natural head movements and blinking. Bright, friendly young robot voice, the same voice in every clip. \
The clip ends right after the last word. No background music, no sound effects, no other people, \
no on-screen text, no scene cuts."""


SCENE_PROMPT = """Vertical cartoon educational video. Style: {style}.
Scene: {visual}
The narrator is the robot character shown in the reference sheet, with exactly the same face, colors, \
helmet and body. Use the sheet only for the character's appearance: do not show the sheet itself, its \
panels, its logo, its city background or any of its text in the video. \
The scene fills the whole frame; the narrator appears only small, head and shoulders, inside a round \
orange-rimmed picture-in-picture bubble in the top-left corner, looking at the camera for the whole clip.
In that bubble the narrator says in Turkish, clearly and enthusiastically, with natural lip movements:
"{text}"
Bright, friendly young robot voice, the same voice in every clip. The narrator finishes speaking just \
before the clip ends. The only sound is this speech: no background music, no sound effects. \
Single continuous shot, no scene cuts, no subtitles, no on-screen text."""


class OmniError(RuntimeError):
    pass


def api_key() -> str:
    return db.get_setting("gemini_api_key") or config.GEMINI_API_KEY


def require_key() -> None:
    if not api_key():
        raise OmniError("Video üretmek için Gemini API anahtarı gerekli: 1. adımdaki Değiştir bölümünden gir.")


def _client(key: str | None = None):
    from google import genai

    key = key or api_key()
    if not key:
        raise OmniError("Gemini API anahtarı girilmemiş.")
    return genai.Client(api_key=key)


def verify(key: str) -> None:
    """Anahtarı ücretsiz bir çağrıyla (model listesi) dener; geçersizse OmniError."""
    try:
        names = [m.name for m in _client(key).models.list()]
    except Exception as e:  # noqa: BLE001 - SDK farklı hata türleri fırlatıyor
        raise OmniError(f"Anahtar doğrulanamadı: {str(e)[:200]}") from e
    if not any("omni" in n for n in names):
        log.warning("Model listesinde Omni görünmedi (%d model); yine de deneniyor", len(names))


def _first_frame() -> bytes:
    """Yüzü 9:16 karenin ortasına yerleştirir (Omni kare oran desteklemiyor); kenarlar bulanık."""
    face = Image.open(FACE_IMAGE).convert("RGB").resize((720, 720), Image.LANCZOS)
    frame = face.resize((1280, 1280)).crop((280, 0, 1000, 1280)).filter(ImageFilter.GaussianBlur(30))
    frame.paste(face, (0, 280))
    buf = io.BytesIO()
    frame.save(buf, "PNG")
    return buf.getvalue()


def chunks(text: str) -> list[str]:
    """Metni cümle sınırlarından, her parça bir klibe (≤10 sn) sığacak şekilde böler."""
    sentences = re.findall(r"[^.!?]+[.!?]*", text)
    parts, current = [], []
    for sentence in (s.strip() for s in sentences if s.strip()):
        if current and len(" ".join(current + [sentence]).split()) > MAX_WORDS_PER_CLIP:
            parts.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        parts.append(" ".join(current))
    return parts or [text]


def record_usage(ref: int | None, seconds: float, input_tokens: int, output_tokens: int) -> float:
    cost = input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT
    db.execute(
        "INSERT INTO api_usage(video_id, model, seconds, input_tokens, output_tokens, cost_usd) VALUES(?, ?, ?, ?, ?, ?)",
        (ref, MODEL, seconds, input_tokens, output_tokens, cost),
    )
    return cost


def duration(path: Path) -> float:
    out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def clip(text: str, out: Path, ref: int | None = None) -> float:
    """Cuma'nın `text`i söylediği klibi üretir; süresini (sn) döndürür."""
    image = base64.b64encode(_first_frame()).decode()
    try:
        interaction = _client().interactions.create(
            model=MODEL,
            input=[
                {"type": "image", "data": image, "mime_type": "image/png"},
                {"type": "text", "text": PROMPT.format(text=text.replace('"', "'"))},
            ],
            response_format={"type": "video", "aspect_ratio": "9:16", "resolution": "720p"},
            generation_config={"video_config": {"task": "image_to_video"}},
            timeout=900,
        )
    except OmniError:
        raise
    except Exception as e:  # noqa: BLE001
        raise OmniError(f"Gemini Omni hatası: {str(e)[:300]}") from e
    return _save(interaction, out, ref)


def _save(interaction, out: Path, ref: int | None) -> float:
    video = interaction.output_video
    if video is None or not video.data:
        reasons = "; ".join(str(err) for err in (interaction.errors or [])) or interaction.status
        raise OmniError(f"Gemini Omni video döndürmedi ({reasons}). İçerik filtresine takılmış olabilir.")
    out.write_bytes(base64.b64decode(video.data))
    seconds = duration(out)
    usage = interaction.usage
    record_usage(
        ref, seconds,
        (usage and usage.total_input_tokens) or 0,
        (usage and usage.total_output_tokens) or round(seconds * TOKENS_PER_SECOND),
    )
    return seconds


def clip_seconds(text: str) -> int:
    """Metnin rahatça söyleneceği klip süresi; Omni 3-15 tam saniye kabul ediyor."""
    return max(3, min(15, math.ceil(len(text.split()) / WORDS_PER_SECOND) + 1))


def scene_clip(text: str, visual: str, out: Path, ref: int | None = None) -> float:
    """Sahneyi, köşede `text`i söyleyen Cuma ile birlikte tek klip üretir; süresini (sn) döndürür."""
    if not REFERENCE_IMAGE.exists():
        raise OmniError(f"Cuma Robot referans görseli bulunamadı: {REFERENCE_IMAGE}")
    image = base64.b64encode(REFERENCE_IMAGE.read_bytes()).decode()
    prompt = SCENE_PROMPT.format(style=config.IMAGE_STYLE, visual=visual, text=text.replace('"', "'"))
    try:
        interaction = _client().interactions.create(
            model=MODEL,
            input=[
                {"type": "image", "data": image, "mime_type": "image/jpeg"},
                {"type": "text", "text": prompt},
            ],
            response_format={"type": "video", "aspect_ratio": "9:16", "resolution": "720p",
                             "duration": f"{clip_seconds(text)}s"},
            timeout=900,
        )
    except Exception as e:  # noqa: BLE001 - SDK farklı hata türleri fırlatıyor
        raise OmniError(f"Gemini hatası: {str(e)[:300]}") from e
    return _save(interaction, out, ref)


def usage_summary() -> dict:
    month = db.one(
        "SELECT COUNT(DISTINCT video_id) videos, COUNT(*) clips, COALESCE(SUM(seconds), 0) seconds, "
        "COALESCE(SUM(cost_usd), 0) cost FROM api_usage WHERE created_at >= date('now', 'start of month')"
    )
    total = db.one("SELECT COALESCE(SUM(cost_usd), 0) cost FROM api_usage")
    return {**month, "total_cost": total["cost"]}


def video_cost(video_id: int) -> float:
    return db.one("SELECT COALESCE(SUM(cost_usd), 0) c FROM api_usage WHERE video_id = ?", (video_id,))["c"]
