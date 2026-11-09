"""Tüm ayarlar .env dosyasından okunur; burada sadece varsayılanlar var."""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


WINDOWS = os.name == "nt"


def venv_bin(venv: Path, name: str) -> Path:
    """Sanal ortamdaki çalıştırılabilir dosya (Windows: Scripts/x.exe, Linux: bin/x)."""
    return venv / "Scripts" / f"{name}.exe" if WINDOWS else venv / "bin" / name


def _default_chrome() -> str:
    if WINDOWS:
        return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    names = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
    return next(filter(None, map(shutil.which, names)), "google-chrome")


DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "agent.db"
VIDEO_DIR = DATA_DIR / "videos"

# Claude (ajanların beyni): auto | claude-code (yerel Claude Code girişi) | api (ANTHROPIC_API_KEY)
LLM_BACKEND = _env("LLM_BACKEND", "auto")
CLAUDE_CODE_PATH = _env("CLAUDE_CODE_PATH")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-opus-5-5")

# Görsel üretimi: "claude-svg" (Claude çizer, Chrome PNG'ye çevirir; anahtar gerekmez),
# "openai" (OPENAI_API_KEY gerekir) veya "placeholder" (düz renkli test kartı)
IMAGE_PROVIDER = _env("IMAGE_PROVIDER", "claude-svg")
IMAGE_MODEL = _env("IMAGE_MODEL", "gpt-image-1")
IMAGE_WORKERS = int(_env("IMAGE_WORKERS", "3"))
IMAGE_STYLE = _env(
    "IMAGE_STYLE",
    "flat 2D cartoon illustration, clean thick black outlines, soft pastel colors, "
    "simple shapes, friendly educational style, plain light background, no text, no letters",
)

# Seslendirme: şimdilik "edge" (ücretsiz). Sesli video modeli veya ElevenLabs sonra eklenebilir.
TTS_PROVIDER = _env("TTS_PROVIDER", "edge")
TTS_VOICES = {
    "female": _env("TTS_VOICE_FEMALE", "tr-TR-EmelNeural"),
    "male": _env("TTS_VOICE_MALE", "tr-TR-AhmetNeural"),
}
TTS_DEFAULT_VOICE = _env("TTS_DEFAULT_VOICE", "female")

# Anlatıcı karakter: videonun köşesinde konuşan rozet (agent/narrator.py). Boş = kapalı.
NARRATOR_NAME = _env("NARRATOR_NAME", "Cuma Robot")
# Yüksek kalite anlatıcı (Gemini Omni Flash). Panelden girilen anahtar veritabanında saklanır ve önceliklidir.
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# Yayın (social-auto-upload)
SAU_DIR = Path(_env("SAU_DIR", str(ROOT / "social-auto-upload")))
# Tarayıcı araçları playwright'ın kurulu olduğu ortamda çalışır: Windows'ta social-auto-upload'ınki,
# Linux paketinde ana ortam. Bağlı hesapların oturum dosyaları da buna göre konumlanır.
BROWSER_PYTHON = venv_bin((SAU_DIR if SAU_DIR.exists() else ROOT) / ".venv", "python")
ACCOUNTS_DIR = SAU_DIR / "cookies" if SAU_DIR.exists() else DATA_DIR / "accounts"
POCKET_EXE = venv_bin(ROOT / "tools" / "tts-tr" / ".venv", "pocket-tts-turkish")
CHROME_PATH = _env("CHROME_PATH") or _default_chrome()
# Hesap bağlama için kalıcı Chrome profili (girişler ve kayıtlı şifreler burada kalır)
CHROME_PROFILE_DIR = Path(_env("CHROME_PROFILE_DIR", str(DATA_DIR / "chrome-profile")))
CHROME_CDP_PORT = int(_env("CHROME_CDP_PORT", "9333"))
PLATFORMS = [p.strip() for p in _env("PLATFORMS", "youtube,tiktok,instagram").split(",") if p.strip()]
SAU_ACCOUNT = _env("SAU_ACCOUNT", "main")
YOUTUBE_VISIBILITY = _env("YOUTUBE_VISIBILITY", "public")
YOUTUBE_MADE_FOR_KIDS = _env("YOUTUBE_MADE_FOR_KIDS", "0") == "1"  # yasal beyan: içerik çocuklara özel mi
PUBLISH_TIMEOUT_SEC = int(_env("PUBLISH_TIMEOUT_SEC", "1200"))

# İstatistik
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = _env("YOUTUBE_CHANNEL_ID")

# Planlama
PLAN_AHEAD_DAYS = int(_env("PLAN_AHEAD_DAYS", "7"))
VIDEOS_PER_DAY = int(_env("VIDEOS_PER_DAY", "1"))

PANEL_HOST = _env("PANEL_HOST", "127.0.0.1")
PANEL_PORT = int(_env("PANEL_PORT", "5050"))
