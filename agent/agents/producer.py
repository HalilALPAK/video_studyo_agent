"""Video Üretim Ajanı: sahne görselleri + seslendirme + altyazı -> 1080x1920 MP4.

Her sahnenin dosyaları (scene_N.png / scene_N.mp3) ayrı tutulur. Düzeltmede önceki
sürümle karşılaştırılır; sadece metni veya görsel tarifi değişen ya da açıkça yeniden
istenen sahneler yeniden üretilir, gerisi önceki sürümden kopyalanır.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imageio_ffmpeg
from mutagen.mp3 import MP3
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from .. import config, llm, narrator, omni, voices
from .scriptwriter import Script

log = logging.getLogger(__name__)

W, H = 1080, 1920
FPS = 30
FONT_PATHS = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


# --- Görsel sağlayıcılar -------------------------------------------------------------

def _image_openai(prompt: str, out: Path) -> None:
    from openai import OpenAI

    result = OpenAI().images.generate(
        model=config.IMAGE_MODEL,
        prompt=f"{prompt}\n\nStyle: {config.IMAGE_STYLE}",
        size="1024x1536",
        n=1,
    )
    out.write_bytes(base64.b64decode(result.data[0].b64_json))


def _image_placeholder(prompt: str, out: Path) -> None:
    """Anahtarsız test için: tarif metninden renk türeten düz bir kart."""
    digest = hashlib.md5(prompt.encode()).digest()
    img = Image.new("RGB", (1024, 1536), (120 + digest[0] % 120, 120 + digest[1] % 120, 120 + digest[2] % 120))
    draw = ImageDraw.Draw(img)
    # dikey kırpmada kenarlar gider; metin ortadaki güvenli alanda kalsın
    draw.multiline_text((140, 500), textwrap.fill(prompt, 30), font=_font(34), fill=(30, 30, 30), spacing=10)
    img.save(out)


class _Svg(BaseModel):
    svg: str


SVG_SYSTEM = """Eğitici kısa videolar için çizgi film illüstratörüsün. İstenen sahneyi tek bir SVG \
olarak çiz.

Teknik kurallar:
- Kök öğe <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1536" width="1024" height="1536">.
- Tamamen kendi içinde: <image>, dış bağlantı, <script>, <foreignObject> ve yazı tipi kullanma.
- Hiç yazı, harf veya rakam olmasın (<text> öğesi yok).
- Önemli öğeleri ortadaki dikey alanda tut (x: 120-900); kenarlar dikey videoda kırpılabilir. \
Alt kısımda (y: 1150-1450) altyazı kutusu olacak; oraya kritik detay koyma.
- Arka planı tüm tuvali dolduran sade bir zemin veya ortamla doldur.

Stil: {style}"""


def _image_claude_svg(prompt: str, out: Path) -> None:
    """Claude'a SVG çizdirir, yerel Chrome ile PNG'ye çevirir. Anahtar veya indirme gerekmez."""
    result = llm.structured(
        system=SVG_SYSTEM.format(style=config.IMAGE_STYLE),
        prompt=f"Sahne: {prompt}",
        schema=_Svg,
        effort="medium",
    )
    match = re.search(r"<svg\b.*</svg>", result.svg, re.S | re.I)
    if not match:
        raise RuntimeError("Claude geçerli bir SVG döndürmedi.")
    svg = re.sub(r"<(script|foreignObject)\b.*?</\1>", "", match.group(0), flags=re.S | re.I)
    out.with_suffix(".svg").write_text(svg, encoding="utf-8")
    _render_svg(svg, out)


def _render_svg(svg: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "scene.html"
        page.write_text(
            "<!doctype html><html><body style='margin:0;background:#fff'>"
            "<style>svg{display:block;width:1024px;height:1536px}</style>" + svg + "</body></html>",
            encoding="utf-8",
        )
        cmd = [
            config.CHROME_PATH, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", f"--user-data-dir={Path(tmp) / 'profile'}",
            "--window-size=1024,1536", f"--screenshot={out}", page.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if not out.exists():
            raise RuntimeError(f"Chrome SVG'yi çeviremedi: {proc.stderr[-800:]}")


IMAGE_PROVIDERS = {"claude-svg": _image_claude_svg, "openai": _image_openai, "placeholder": _image_placeholder}


# --- Seslendirme sağlayıcıları -------------------------------------------------------

def _tts_edge(text: str, out: Path, preset: dict, rate: int) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, preset["name"], rate=voices.rate_string(rate), pitch=preset["pitch"] or "+0Hz")
    asyncio.run(communicate.save(str(out)))


def _tts_pocket(text: str, out: Path, preset: dict, rate: int) -> None:
    """Yerel Türkçe model (Pocket TTS Turkish, CPU). Hız ayarı olmadığı için ffmpeg atempo ile uygulanır."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        proc = subprocess.run(
            [str(config.POCKET_EXE), "generate", "--voice", preset["name"], "--emotion", preset.get("emotion", "mutlu"),
             "--seed", "7", "--text", text, "-o", str(wav)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if proc.returncode != 0 or not wav.exists():
            raise RuntimeError(f"Pocket TTS hatası: {(proc.stderr or proc.stdout)[-600:]}")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav),
                        "-filter:a", f"atempo={1 + rate / 100:.3f}", "-b:a", "128k", str(out)],
                       check=True, capture_output=True)


TTS_PROVIDERS = {"edge": _tts_edge, "pocket": _tts_pocket}


def _tts(preset: dict):
    return TTS_PROVIDERS[preset.get("engine", config.TTS_PROVIDER)]


def voice_sample(voice_id: str) -> Path:
    """Paneldeki "dinle" düğmesi için kısa örnek; ilk istekte üretilip saklanır."""
    _, preset = voices.resolve(voice_id)
    out = config.DATA_DIR / "voice_samples" / f"{voice_id}.mp3"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        _tts(preset)(voices.SAMPLE_TEXT, out, preset, preset["rate"])
    return out


# --- Kare çizimi ---------------------------------------------------------------------

def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _cover(img: Image.Image) -> Image.Image:
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def _caption_chunks(text: str, max_words: int = 6) -> list[str]:
    """Altyazıyı kısa parçalara böler; noktalama işaretinde parçayı erken kapatır."""
    chunks, current = [], []
    for word in text.split():
        current.append(word)
        if len(current) >= max_words or word[-1] in ".!?,;:":
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


def _caption_layer(size: tuple[int, int], caption: str) -> Image.Image:
    """Şeffaf zemin üzerine altyazı kutusu."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(64)
    lines = textwrap.wrap(caption, 22)
    line_h = 80
    box_h = line_h * len(lines) + 50
    top = 1350 - box_h // 2
    draw.rounded_rectangle((60, top, W - 60, top + box_h), radius=28, fill=(0, 0, 0, 170))
    for i, line in enumerate(lines):
        y = top + 25 + i * line_h
        draw.text((W // 2, y), line, font=font, fill="white", anchor="ma", stroke_width=3, stroke_fill="black")
    return overlay


def _render_frame(background: Image.Image, caption: str, out: Path) -> None:
    frame = background.copy().convert("RGBA")
    Image.alpha_composite(frame, _caption_layer(frame.size, caption)).convert("RGB").save(out)


# --- Ana akış ------------------------------------------------------------------------

def _copy_if_unchanged(prev_dir: Path | None, name: str, workdir: Path, unchanged: bool) -> bool:
    if prev_dir and unchanged and (prev_dir / name).exists():
        shutil.copy2(prev_dir / name, workdir / name)
        return True
    return False


def produce(
    script: Script,
    workdir: Path,
    voice: str | None = None,
    rate: str = "normal",
    prev: tuple[Script, Path] | None = None,
    force_images: set[int] = frozenset(),
    force_voice: bool = False,
    on_progress=lambda text: None,
    max_seconds: int | None = None,
    engine: str = "local",
    usage_ref: int | None = None,
) -> Path:
    """Videoyu üretir ve MP4 yolunu döndürür. force_images 1 tabanlı sahne numaralarıdır.
    on_progress panelde gösterilecek kısa durum metinlerini alır. max_seconds verilirse
    toplam süre bu sınırı aşmayacak şekilde ses hızlandırılır (yerel modda).
    engine: "local" (TTS + SadTalker) veya "omni" (Gemini Omni hem konuşur hem anlatıcıyı canlandırır;
    API maliyeti usage_ref video id'siyle kaydedilir). Kullanılan yöntem produce_report.json'a yazılır."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    prev_script, prev_dir = prev if prev else (None, None)
    image_fn = IMAGE_PROVIDERS[config.IMAGE_PROVIDER]

    frames_dir = workdir / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir()
    frame_lines, audio_lines, report = [], [], []

    def old_scene(i: int):
        return prev_script.scenes[i - 1] if prev_script and i <= len(prev_script.scenes) else None

    # Görseller en yavaş adım; değişenleri paralel üret
    to_draw = []
    for i, scene in enumerate(script.scenes, start=1):
        old = old_scene(i)
        image_same = old is not None and old.visual == scene.visual and i not in force_images
        if not _copy_if_unchanged(prev_dir, f"scene_{i}.png", workdir, image_same):
            to_draw.append((i, scene.visual))
    if to_draw:
        log.info("%d görsel üretiliyor", len(to_draw))
        done = [0]
        on_progress(f"Görseller çiziliyor (0/{len(to_draw)})")

        def draw(job):
            image_fn(job[1], workdir / f"scene_{job[0]}.png")
            done[0] += 1
            on_progress(f"Görseller çiziliyor ({done[0]}/{len(to_draw)})")

        with ThreadPoolExecutor(max_workers=config.IMAGE_WORKERS) as pool:
            list(pool.map(draw, to_draw))
        report += [f"görsel {i}" for i, _ in to_draw]

    prev_omni = bool(prev_dir and (prev_dir / "narr_1.mp4").exists())
    if engine == "omni":
        try:
            _omni_narration(script, workdir, prev_dir if prev_omni else None, old_scene, usage_ref,
                            on_progress, report)
        except omni.OmniError as e:
            # Ücretli servis çalışmazsa video yarım kalmasın: yerel ses + SadTalker ile devam
            log.warning("Gemini Omni başarısız, yerel yönteme geçiliyor: %s", e)
            on_progress("Gemini kullanılamadı, yerel yönteme geçiliyor")
            report.append(f"Gemini başarısız, yerel yöntem kullanıldı: {e}")
            engine = "local"
            for leftover in workdir.glob("narr_*.mp4"):
                leftover.unlink()

    _, preset = voices.resolve(voice)
    base_rate = preset["rate"] + voices.RATE_ADJUST.get(rate, 0)

    def speak(i: int, text: str, extra: int = 0) -> None:
        _tts(preset)(text, workdir / f"scene_{i}.mp3", preset, base_rate + extra)

    if engine == "local":
        on_progress("Seslendirme hazırlanıyor")
        for i, scene in enumerate(script.scenes, start=1):
            old = old_scene(i)
            voice_same = old is not None and old.narration == scene.narration and not force_voice and not prev_omni
            if not _copy_if_unchanged(prev_dir, f"scene_{i}.mp3", workdir, voice_same):
                log.info("Sahne %d seslendiriliyor", i)
                speak(i, scene.narration)
                report.append(f"ses {i}")

    def durations() -> list[float]:
        return [MP3(workdir / f"scene_{i}.mp3").info.length for i in range(1, len(script.scenes) + 1)]

    lengths = durations()
    if engine == "local" and max_seconds and sum(lengths) > max_seconds:
        # Metin seçilen süreye sığmadıysa sesi biraz hızlandırarak yeniden üret
        extra = min(int((sum(lengths) / max_seconds - 1) * 100) + 3, 30)
        log.info("Süre %.0f sn > %d sn; ses %%%d hızlandırılıyor", sum(lengths), max_seconds, extra)
        on_progress(f"Süre {max_seconds} sn sınırına sığdırılıyor")
        for i, scene in enumerate(script.scenes, start=1):
            speak(i, scene.narration, extra)
        lengths = durations()
        report.append(f"ses %{extra} hızlandırıldı")

    on_progress("Altyazı ve kareler hazırlanıyor")
    for i, scene in enumerate(script.scenes, start=1):
        img_name, mp3_name = f"scene_{i}.png", f"scene_{i}.mp3"
        duration = lengths[i - 1]
        chunks = _caption_chunks(scene.narration)
        total_chars = sum(len(c) for c in chunks)
        background = _cover(Image.open(workdir / img_name).convert("RGB"))
        for j, chunk in enumerate(chunks):
            frame = frames_dir / f"{i:02d}_{j:02d}.png"
            _render_frame(background, chunk, frame)
            frame_lines.append(f"file '{frame.as_posix()}'\nduration {duration * len(chunk) / total_chars:.3f}")
        audio_lines.append(f"file '{(workdir / mp3_name).as_posix()}'")

    # concat demuxer son kareyi süresiz bırakır; son kare bir kez daha yazılır
    frame_lines.append(frame_lines[-1].split("\n")[0])
    (workdir / "frames.txt").write_text("\n".join(frame_lines), encoding="utf-8")
    (workdir / "audio.txt").write_text("\n".join(audio_lines), encoding="utf-8")

    on_progress("Video birleştiriliyor")
    out = workdir / "video.mp4"
    inputs = [
        "-f", "concat", "-safe", "0", "-i", str(workdir / "frames.txt"),
        "-f", "concat", "-safe", "0", "-i", str(workdir / "audio.txt"),
    ]
    head = None
    if engine == "omni":
        # Omni klipleri zaten konuşan anlatıcı; sesleri sahne mp3'lerine ayrıldı, burada sadece görüntü
        head = _concat([workdir / f"narr_{i}.mp4" for i in range(1, len(script.scenes) + 1)],
                       workdir / "narrator.mp4", audio=False)
    elif config.NARRATOR_NAME and narrator.sadtalker_ready():
        # Konuşan yüz (SadTalker): ses değişmediyse önceki sürümün videosu kullanılır
        audio_same = not any(r.startswith("ses") for r in report)
        if _copy_if_unchanged(prev_dir, "narrator.mp4", workdir, audio_same and not prev_omni):
            head = workdir / "narrator.mp4"
        else:
            total = sum(lengths)
            on_progress(f"{config.NARRATOR_NAME} konuşturuluyor (~{narrator.estimate_minutes(total)} dk)")
            try:
                head = narrator.talking_head([workdir / f"scene_{i}.mp3" for i in range(1, len(script.scenes) + 1)], workdir)
                report.append("anlatıcı")
            except Exception:
                log.exception("SadTalker başarısız; anlatıcı için çizimli ağız kullanılacak")
        on_progress("Video birleştiriliyor")
    x, y = narrator.POSITION
    if head:
        mask, ring = narrator.badge_layers(config.DATA_DIR / "narrator")
        total = f"{sum(lengths) + 1:.2f}"
        inputs += ["-i", str(head), "-loop", "1", "-t", total, "-i", str(mask), "-loop", "1", "-t", total, "-i", str(ring)]
        size = narrator.SIZE
        video = ["-filter_complex",
                 f"[0:v]fps={FPS},format=yuv420p[bg];"
                 f"[2:v]crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size},fps={FPS},format=rgba[face];"
                 f"[3:v]format=gray[mask];[face][mask]alphamerge[badge];"
                 f"[bg][badge]overlay={x}:{y}[withface];[withface][4:v]overlay={x}:{y},format=yuv420p[v]",
                 "-map", "[v]", "-map", "1:a"]
    elif config.NARRATOR_NAME:
        # Yedek: ağzı her sahnenin ses yüksekliğine göre çizilen rozet
        mp3s = [workdir / f"scene_{i}.mp3" for i in range(1, len(script.scenes) + 1)]
        inputs += ["-f", "concat", "-safe", "0", "-i", str(narrator.track(mp3s, lengths, workdir))]
        video = ["-filter_complex",
                 f"[0:v]fps={FPS},format=yuv420p[bg];[2:v]fps={FPS},format=rgba[n];"
                 f"[bg][n]overlay={x}:{y}:eof_action=pass,format=yuv420p[v]",
                 "-map", "[v]", "-map", "1:a"]
    else:
        video = ["-vf", f"fps={FPS},format=yuv420p"]
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *inputs, *video,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",  # TTS 24 kHz mono; Instagram web standart ses ister
        "-shortest", "-movflags", "+faststart", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg hatası: {proc.stderr[-1500:]}")
    (workdir / "produce_report.json").write_text(
        json.dumps({"regenerated": report, "engine": engine}, ensure_ascii=False), encoding="utf-8")
    log.info("Video hazır: %s (%s; yeniden üretilen: %s)", out, engine, ", ".join(report) or "yok")
    return out


def report_of(workdir: Path) -> dict:
    path = workdir / "produce_report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _concat(clips: list[Path], out: Path, audio: bool = True) -> Path:
    listing = out.with_suffix(".txt")
    listing.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf-8")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
    proc = subprocess.run(cmd + [str(out)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg birleştirme hatası: {proc.stderr[-800:]}")
    return out


def _omni_narration(script: Script, workdir: Path, prev_dir: Path | None, old_scene, usage_ref,
                    on_progress, report: list) -> None:
    """Her sahne için Cuma'nın metni söylediği Gemini Omni klibini üretir (uzun metin birkaç klibe
    bölünür), sesini scene_i.mp3 olarak ayırır. Metni değişmeyen sahnelerin klipleri yeniden kullanılır."""
    total = len(script.scenes)
    for i, scene in enumerate(script.scenes, start=1):
        narr, mp3 = workdir / f"narr_{i}.mp4", workdir / f"scene_{i}.mp3"
        old = old_scene(i)
        same = old is not None and old.narration == scene.narration
        if _copy_if_unchanged(prev_dir, narr.name, workdir, same) and \
                _copy_if_unchanged(prev_dir, mp3.name, workdir, same):
            continue
        on_progress(f"{config.NARRATOR_NAME} Gemini ile konuşturuluyor ({i}/{total})")
        parts = omni.chunks(scene.narration)
        clips = [workdir / f"narr_{i}_{k}.mp4" for k in range(1, len(parts) + 1)]
        for part, clip_path in zip(parts, clips):
            omni.clip(part, clip_path, usage_ref)
        _concat(clips, narr) if len(clips) > 1 else shutil.copy2(clips[0], narr)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(narr), "-vn",
                        "-ar", "44100", "-ac", "2", "-b:a", "160k", str(mp3)], check=True, capture_output=True)
        report.append(f"gemini {i}")
