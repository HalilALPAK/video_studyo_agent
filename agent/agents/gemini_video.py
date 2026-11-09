"""Video Üretim Ajanı: videonun tamamını Gemini Omni Flash üretir.

Her sahne (uzunsa birkaç parça) tek klip olarak istenir: sahne görüntüsü, seçildiyse köşede konuşan
Cuma Robot ve ses birlikte gelir. Burada sadece klipler birleştirilip altyazı eklenir. Klipler ücretli
olduğu için metni ve görseli değişmeyen klip asla yeniden üretilmez: yarım kalan üretimde
aynı klasörden, düzeltmede önceki sürümden alınır.
"""
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

from .. import omni
from . import producer
from .scriptwriter import Script

log = logging.getLogger(__name__)

W, H, FPS = producer.W, producer.H, producer.FPS
MANIFEST = "clips.json"  # klip dosyası -> metin+görsel özeti


def _key(text: str, visual: str) -> str:
    return hashlib.sha256(f"{text}\n{visual}".encode("utf-8")).hexdigest()


def _manifest(folder: Path | None) -> dict[str, str]:
    path = folder / MANIFEST if folder else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}


def produce(
    script: Script,
    workdir: Path,
    prev_dir: Path | None = None,
    force_scenes: set[int] = frozenset(),
    on_progress=lambda text: None,
    usage_ref: int | None = None,
    narrator: bool = True,
    cartoon: bool = True,
) -> Path:
    """Videoyu üretir, MP4 yolunu döndürür. force_scenes (1 tabanlı) önceki sürümden alınmaz."""
    omni.require_key()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")

    manifest = _manifest(workdir)
    previous = {key: name for name, key in _manifest(prev_dir).items()}
    jobs = [(i, k, part, scene.visual)
            for i, scene in enumerate(script.scenes, start=1)
            for k, part in enumerate(omni.chunks(scene.narration), start=1)]
    clips, report = [], []
    for done, (i, k, part, visual) in enumerate(jobs, start=1):
        clip = workdir / f"clip_{i}_{k}.mp4"
        key = _key(part, f"{visual}|{narrator}|{cartoon}")
        clips.append((clip, part))
        if manifest.get(clip.name) == key and clip.exists():
            continue  # yarım kalan önceki denemeden, parası ödenmiş
        if i not in force_scenes and key in previous and (prev_dir / previous[key]).exists():
            shutil.copy2(prev_dir / previous[key], clip)
        else:
            on_progress(f"Gemini sahneyi üretiyor ({done}/{len(jobs)})")
            log.info("Sahne %d parça %d üretiliyor", i, k)
            omni.scene_clip(part, visual, clip, usage_ref, narrator=narrator, cartoon=cartoon)
            report.append(f"gemini {i}.{k}")
        manifest[clip.name] = key
        (workdir / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    on_progress("Altyazılar hazırlanıyor")
    captions_dir = workdir / "captions"
    shutil.rmtree(captions_dir, ignore_errors=True)
    captions_dir.mkdir()
    caption_lines = []
    for n, (clip, part) in enumerate(clips):
        length = omni.duration(clip)
        chunks = producer._caption_chunks(part)
        if not chunks:  # seslendirmesiz klip: altyazı yok, boş katman süreyi korur
            png = captions_dir / f"{n:03d}_blank.png"
            Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(png)
            caption_lines.append(f"file '{png.as_posix()}'\nduration {length:.3f}")
            continue
        total_chars = sum(len(c) for c in chunks)
        for j, chunk in enumerate(chunks):
            png = captions_dir / f"{n:03d}_{j:02d}.png"
            producer._caption_layer((W, H), chunk).save(png)
            caption_lines.append(f"file '{png.as_posix()}'\nduration {length * len(chunk) / total_chars:.3f}")
    caption_lines.append(caption_lines[-1].split("\n")[0])  # concat son kareyi süresiz bırakır
    (workdir / "captions.txt").write_text("\n".join(caption_lines), encoding="utf-8")
    (workdir / "clips.txt").write_text("\n".join(f"file '{c.as_posix()}'" for c, _ in clips), encoding="utf-8")

    on_progress("Video birleştiriliyor")
    out = workdir / "video.mp4"
    proc = subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(workdir / "clips.txt"),
        "-f", "concat", "-safe", "0", "-i", str(workdir / "captions.txt"),
        "-filter_complex",
        f"[0:v]scale={W}:{H},fps={FPS},format=yuv420p[bg];[1:v]fps={FPS},format=rgba[cap];"
        "[bg][cap]overlay=0:0:eof_action=pass,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg hatası: {proc.stderr[-1500:]}")
    (workdir / "produce_report.json").write_text(
        json.dumps({"regenerated": report, "engine": "omni"}, ensure_ascii=False), encoding="utf-8")
    log.info("Video hazır: %s (üretilen klip: %s)", out, ", ".join(report) or "yok")
    return out
