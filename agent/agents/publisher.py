"""Yayın Ajanı: onaylanan videoyu, giriş yapılan "Video Stüdyosu" Chrome'unda platformların
kendi yükleme sayfalarından yükler (tools/studio_upload.py)."""
import json
import logging
import subprocess
from pathlib import Path

from .. import config, db, voices
from .scriptwriter import Script

log = logging.getLogger(__name__)

CONNECT_HELPER = config.ROOT / "tools" / "connect_account.py"
STUDIO_UPLOADER = config.ROOT / "tools" / "studio_upload.py"


def build_command(platform: str, video: Path, script: Script) -> list[str]:
    tags = ",".join(t.lstrip("#") for t in script.hashtags)
    return [str(config.BROWSER_PYTHON), str(STUDIO_UPLOADER), "--platform", platform, "--file", str(video),
            "--title", script.title, "--desc", script.description, "--tags", tags,
            "--visibility", config.YOUTUBE_VISIBILITY, *(["--kids"] if config.YOUTUBE_MADE_FOR_KIDS else []),
            "--profile", str(config.CHROME_PROFILE_DIR), "--port", str(config.CHROME_CDP_PORT),
            "--chrome", config.CHROME_PATH, "--timeout", str(config.PUBLISH_TIMEOUT_SEC - 60),
            "--debug-dir", str(config.DATA_DIR / "upload_debug")]


PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook-page": "Facebook Sayfası",  # sadece eski yayın kayıtları için
}


def account_file(platform: str) -> Path:
    if platform == "tiktok":
        return config.ACCOUNTS_DIR / "tk_uploader" / f"{config.SAU_ACCOUNT}.json"
    return config.ACCOUNTS_DIR / f"{platform}_{config.SAU_ACCOUNT}.json"


def accounts() -> list[dict]:
    """Platform başına giriş durumu (giriş dosyası var mı)."""
    return [
        {"platform": p, "label": PLATFORM_LABELS.get(p, p), "connected": account_file(p).exists()}
        for p in config.PLATFORMS
    ]


def connected_platforms() -> list[str]:
    return [a["platform"] for a in accounts() if a["connected"]]


def _helper(platform: str, *extra: str) -> list[str]:
    return [
        str(config.BROWSER_PYTHON), str(CONNECT_HELPER), "--platform", platform,
        "--profile", str(config.CHROME_PROFILE_DIR), "--port", str(config.CHROME_CDP_PORT),
        "--chrome", config.CHROME_PATH, *extra,
    ]


def inspect(platform: str) -> str:
    """Bağlı hesabın sayfasını (YouTube Studio, TikTok Studio, Instagram) Video Stüdyosu Chrome'unda açar."""
    proc = subprocess.run(_helper(platform, "--inspect"), cwd=config.ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    label = PLATFORM_LABELS.get(platform, platform)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        raise RuntimeError(f"{label} açılamadı: {err[-1] if err else 'bilinmeyen hata'}")
    return f"{label} hesabı Video Stüdyosu Chrome penceresinde açıldı."


def login(platform: str, signup: bool = False, fill: dict | None = None, switch: bool = False) -> str:
    """Kalıcı "Video Stüdyosu" Chrome profilinde giriş (signup=True ise kayıt) sayfasını açar;
    kullanıcı giriş yapınca oturum otomatik algılanıp kaydedilir ve sekme hesabın sayfasında açık kalır.
    switch=True önce bu platformdaki hesaptan çıkış yapar. fill (email, password, name, username)
    verilirse formlar bununla doldurulur; stdin ile geçer, diske yazılmaz."""
    cmd = _helper(platform, "--out", str(account_file(platform)))
    if signup:
        cmd.append("--signup")
    if fill:
        cmd.append("--fill")
    if switch:
        cmd.append("--switch")
        account_file(platform).unlink(missing_ok=True)  # yeni hesap girilene kadar bağlı görünmesin
    label = PLATFORM_LABELS.get(platform, platform)
    proc = subprocess.run(cmd, cwd=config.ROOT, input=json.dumps(fill or {}), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=960)
    if proc.returncode != 0 or not account_file(platform).exists():
        err = (proc.stderr or proc.stdout).strip().splitlines()
        raise RuntimeError(f"{label} bağlanamadı: {err[-1] if err else 'bilinmeyen hata'}")
    return f"{label} bağlandı"


def upload(platform: str, video: Path, script: Script) -> tuple[bool, str, str]:
    """(başarılı mı, log, url) döndürür."""
    log.info("%s yükleniyor", platform)
    try:
        proc = subprocess.run(
            build_command(platform, video, script), cwd=config.ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=config.PUBLISH_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, f"{config.PUBLISH_TIMEOUT_SEC} sn içinde bitmedi", ""
    output = (proc.stdout + "\n" + proc.stderr)[-4000:]
    url = next((line[5:].strip() for line in proc.stdout.splitlines() if line.startswith("URL: ")), "")
    return proc.returncode == 0, output, url


def publish_video(video_id: int, platforms: list[str] | None = None) -> dict[str, bool]:
    """Videoyu yükler. platforms verilmezse giriş yapılmış tüm platformlara."""
    platforms = platforms if platforms is not None else connected_platforms()
    if not platforms:
        raise RuntimeError("Bağlı sosyal medya hesabı yok; önce Yayın adımında hesap bağla.")
    # Aynı videonun iki kez yayına girmesini engelle (panel ve günlük döngü aynı anda çalışabilir)
    claimed = db.execute(
        "UPDATE videos SET status = 'publishing' WHERE id = ? AND status IN ('approved', 'publish_failed')",
        (video_id,),
    )
    if not claimed:
        log.info("Video %s yayına hazır değil veya zaten yayında", video_id)
        return {}
    v = db.one("SELECT * FROM videos WHERE id = ?", (video_id,))
    script = Script.model_validate_json(v["script"])
    if credit := voices.credit(json.loads(v["meta"] or "{}").get("voice")):
        script = script.model_copy(update={"description": f"{script.description}\n\n{credit}"})
    results = {}
    for platform in platforms:
        post = db.one("SELECT * FROM posts WHERE video_id = ? AND platform = ?", (video_id, platform))
        if post and post["status"] == "ok":
            results[platform] = True
            continue
        ok, output, url = upload(platform, Path(v["path"]), script)
        db.execute(
            "INSERT INTO posts(video_id, platform, status, url, log) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(video_id, platform) DO UPDATE SET status = excluded.status, url = excluded.url, "
            "log = excluded.log, updated_at = CURRENT_TIMESTAMP",
            (video_id, platform, "ok" if ok else "failed", url, output),
        )
        results[platform] = ok

    final = "published" if all(results.values()) else "publish_failed"
    db.execute("UPDATE videos SET status = ? WHERE id = ?", (final, video_id))
    if final == "published":
        db.execute("UPDATE subtopics SET status = 'published' WHERE id = ?", (v["subtopic_id"],))
    return results
