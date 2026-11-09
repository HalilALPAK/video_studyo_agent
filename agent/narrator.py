"""Anlatıcı karakter (Cuma Robot): videonun köşesinde konuşan yuvarlak rozet.

Asıl yöntem SadTalker (tools/SadTalker, yerel GPU): tek yüz fotoğrafı ve seslendirmeden dudakları
konuşmaya uyan, başı hafif hareket eden, göz kırpan bir video üretir (talking_head).
SadTalker kurulu değilse ya da hata verirse yedek yöntem: afişteki "Kararlı" yüzün üstüne ses
yüksekliğine göre 4 seviyede ağız çizilen PNG kareleri (track).
"""
import logging
import math
import os
import random
import shutil
import subprocess
from array import array
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter

from . import config

log = logging.getLogger(__name__)
POSTER = config.ROOT / "assets" / "narrator" / "cuma_robot_poster.jpg"
FACE_BOX = (677, 1178, 839, 1338)  # afişte "Kararlı" karesi (162x160)
# Aşağıdaki koordinatlar FACE_BOX içindeki piksellerdir
MOUTH = (110, 118)
EYES = [((84, 86), (12, 10)), ((124, 83), (10, 9))]  # (merkez, yarıçap x/y)

SIZE = 340  # rozet çapı (video pikseli)
RING = (242, 107, 29)  # logodaki turuncu
POSITION = (40, 150)  # sol üst köşe: alt köşeler ve sağ kenar TikTok/Reels/Shorts yazı ve düğmeleriyle kaplı
FPS = 30
LEVELS = 4  # 0 = kapalı (orijinal) ... 3 = en açık


def _mouth(draw: ImageDraw.ImageDraw, level: int, s: float) -> None:
    """level>0 için açık ağız; s = yüz karesinden çalışma çözünürlüğüne ölçek."""
    cx, cy = MOUTH[0] * s, MOUTH[1] * s
    w, h = (17 + 3 * level) * s / 2, (2.5 + 3.2 * level) * s / 2
    draw.ellipse((cx - w, cy - h * 0.7, cx + w, cy + h * 1.3), fill=(48, 14, 24))
    if level >= 2:  # üst dişler
        draw.chord((cx - w * 0.75, cy - h * 0.72, cx + w * 0.75, cy - h * 0.05), 180, 360, fill=(240, 236, 232))
    if level >= 3:  # dil, ağzın dibinde
        draw.chord((cx - w * 0.5, cy + h * 0.55, cx + w * 0.5, cy + h * 1.25), 180, 360, fill=(170, 70, 84))


def _blink(img: Image.Image, s: float) -> Image.Image:
    """Gözleri, hemen üstündeki ve altındaki deri rengi arasında dikey geçişle kapatır
    (ışık yüzün iki yanında çok farklı; tek renk gri leke gibi duruyor)."""
    img = img.convert("RGBA")
    for (ex, ey), (rx, ry) in EYES:
        top, bottom = img.getpixel((int(ex * s), int((ey - ry - 3) * s))), img.getpixel((int(ex * s), int((ey + ry + 3) * s)))
        bw, bh = int((2 * rx + 3) * s), int((2 * ry + 3) * s)
        lid = Image.new("RGBA", (bw, bh))
        for y in range(bh):
            t = y / max(1, bh - 1)
            ImageDraw.Draw(lid).line((0, y, bw, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(top[:3], bottom[:3])) + (255,))
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, bw - 1, bh - 1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(s))
        x0, y0 = int((ex - rx - 1.5) * s), int((ey - ry - 1.5) * s)
        img.paste(lid, (x0, y0), mask)
        ImageDraw.Draw(img).arc(((ex - rx) * s, (ey - ry * 0.5) * s, (ex + rx) * s, (ey + ry * 0.8) * s), 25, 155,
                                fill=(55, 50, 70), width=max(2, int(1.4 * s)))
    return img.convert("RGB")


def _badge(face: Image.Image) -> Image.Image:
    """Yüzü turuncu halkalı yuvarlak rozete yerleştirir (şeffaf arka plan)."""
    face = face.resize((SIZE, SIZE), Image.LANCZOS)
    mask = Image.new("L", (SIZE * 4, SIZE * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE * 4 - 1, SIZE * 4 - 1), fill=255)
    mask = mask.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(face, (0, 0), mask)
    ring = Image.new("RGBA", (SIZE * 4, SIZE * 4), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((8, 8, SIZE * 4 - 9, SIZE * 4 - 9), outline=RING + (255,), width=44)
    return Image.alpha_composite(out, ring.resize((SIZE, SIZE), Image.LANCZOS))


def sprites(out_dir: Path) -> dict[tuple[int, bool], Path]:
    """(ağız seviyesi, göz kapalı mı) -> PNG yolu. Bir kez üretilir, sonra önbellekten gelir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {(lvl, blink): out_dir / f"mouth{lvl}{'_blink' if blink else ''}.png"
             for lvl in range(LEVELS) for blink in (False, True)}
    if all(p.exists() for p in paths.values()):
        return paths
    base = Image.open(POSTER).convert("RGB").crop(FACE_BOX)
    s = 8  # çizimi 8 kat büyükte yapıp yumuşatarak küçült (kenarlar fotoğrafla kaynaşsın)
    big = base.resize((base.width * s, base.height * s), Image.LANCZOS)
    for (lvl, blink), path in paths.items():
        img = big.copy()
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        if lvl:
            _mouth(draw, lvl, s)
        layer = layer.filter(ImageFilter.GaussianBlur(s * 0.6))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        if blink:
            img = _blink(img, s)
        _badge(img).save(path)
    return paths


def _loudness(mp3: Path) -> list[float]:
    """Kare başına (1/FPS sn) ses yüksekliği (RMS)."""
    rate = 16000
    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", str(mp3),
         "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"],
        capture_output=True, check=True,
    ).stdout
    pcm = array("h", raw[: len(raw) // 2 * 2])
    hop = rate // FPS
    return [math.sqrt(sum(x * x for x in pcm[i:i + hop]) / hop) for i in range(0, len(pcm) - hop + 1, hop)] or [0.0]


def _levels(loud: list[float]) -> list[int]:
    ref = sorted(loud)[int(len(loud) * 0.95)] or 1.0
    lv = [sum(v / ref >= t for t in (0.12, 0.35, 0.65)) for v in loud]  # 0..3
    # tek karelik titremeleri at (3'lü medyan)
    padded = [lv[0]] + lv + [lv[-1]]
    return [sorted(padded[i:i + 3])[1] for i in range(len(lv))]


def track(mp3s: list[Path], durations: list[float], out_dir: Path, seed: int = 0) -> Path:
    """Sahne seslerine göre anlatıcı karelerinin concat listesini yazar, yolunu döndürür."""
    paths = sprites(config.DATA_DIR / "narrator")
    rng = random.Random(seed)
    levels: list[int] = []
    for mp3, duration in zip(mp3s, durations):
        lv = _levels(_loudness(mp3))
        want = round(duration * FPS)  # sahne süresine tam oturt (sesler uç uca eklenir)
        levels += (lv + [0] * want)[:want]
    blink = [False] * len(levels)
    i = rng.randint(FPS, 3 * FPS)
    while i < len(levels):
        for k in range(i, min(i + 4, len(levels))):
            blink[k] = True
        i += rng.randint(int(2.5 * FPS), 5 * FPS)
    # aynı kareyi tekrar eden ardışık kareleri tek satırda birleştir
    lines, prev, run = [], None, 0
    for state in zip(levels, blink):
        if state == prev:
            run += 1
            continue
        if prev is not None:
            lines.append(f"file '{paths[prev].as_posix()}'\nduration {run / FPS:.4f}")
        prev, run = state, 1
    lines.append(f"file '{paths[prev].as_posix()}'\nduration {run / FPS:.4f}")
    lines.append(lines[-1].split("\n")[0])
    out = out_dir / "narrator.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# --- SadTalker ---------------------------------------------------------------------------

SADTALKER_DIR = config.ROOT / "tools" / "SadTalker"
FACE_IMAGE = config.ROOT / "assets" / "narrator" / "cuma_face.png"  # 512px "Kararlı" yüz
SECONDS_PER_FRAME = 0.4  # RTX 3050'de ölçülen: 483 kare 212 sn (batch 2; batch 4 VRAM'e sığmayıp yavaşlıyor)
EXPRESSION_SCALE = 1.8  # çizgi film yüzde ağız varsayılan ayarda çok az açılıyor


def sadtalker_ready() -> bool:
    return (config.venv_bin(SADTALKER_DIR / ".venv", "python")).exists() and \
        (SADTALKER_DIR / "checkpoints" / "SadTalker_V0.0.2_256.safetensors").exists()


def estimate_minutes(seconds: float) -> int:
    return max(1, round(seconds * 25 * SECONDS_PER_FRAME / 60))


def talking_head(mp3s: list[Path], workdir: Path) -> Path:
    """Sahne seslerini birleştirip SadTalker'la konuşan yüz videosu üretir (25 fps, ~256 px)."""
    wav = workdir / "narration.wav"
    listing = workdir / "narration.txt"
    listing.write_text("\n".join(f"file '{m.as_posix()}'" for m in mp3s), encoding="utf-8")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-ar", "16000", "-ac", "1", str(wav)], check=True, capture_output=True)
    result_dir = workdir / "sadtalker"
    shutil.rmtree(result_dir, ignore_errors=True)
    env = {**os.environ, "PATH": f"{SADTALKER_DIR / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [str(config.venv_bin(SADTALKER_DIR / ".venv", "python")), "inference.py",
         "--driven_audio", str(wav), "--source_image", str(FACE_IMAGE), "--result_dir", str(result_dir),
         "--preprocess", "crop", "--size", "256", "--batch_size", "2", "--expression_scale", str(EXPRESSION_SCALE)],
        cwd=SADTALKER_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=3 * 3600,
    )
    videos = sorted(result_dir.glob("*.mp4"))  # alt klasördekiler ara çıktı
    if proc.returncode != 0 or not videos:
        raise RuntimeError(f"SadTalker hatası: {(proc.stderr or proc.stdout)[-800:]}")
    out = workdir / "narrator.mp4"
    shutil.copy2(videos[-1], out)
    shutil.rmtree(result_dir, ignore_errors=True)
    return out


def badge_layers(out_dir: Path) -> tuple[Path, Path]:
    """Konuşan yüz videosunu rozete çevirmek için daire maskesi ve turuncu halka."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mask_path, ring_path = out_dir / f"mask_{SIZE}.png", out_dir / f"ring_{SIZE}.png"
    if not mask_path.exists():
        mask = Image.new("L", (SIZE * 4, SIZE * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, SIZE * 4 - 1, SIZE * 4 - 1), fill=255)
        mask.resize((SIZE, SIZE), Image.LANCZOS).save(mask_path)
        ring = Image.new("RGBA", (SIZE * 4, SIZE * 4), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((8, 8, SIZE * 4 - 9, SIZE * 4 - 9), outline=RING + (255,), width=44)
        ring.resize((SIZE, SIZE), Image.LANCZOS).save(ring_path)
    return mask_path, ring_path
