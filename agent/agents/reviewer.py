"""Onay/Düzeltme Ajanı: "Beğendim" -> yayına onaylar; "Beğenmedim" + not -> Claude notu
yorumlar, senaryoyu sadece gereken yerlerde günceller ve hangi adımların (metin, ses,
görsel) yeniden üretileceğine karar verir. Üretim ajanı sadece o adımları yeniden yapar."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .. import db, llm, voices
from . import gemini_video, producer
from .scriptwriter import Script


class Revision(BaseModel):
    summary: str  # kullanıcıya gösterilecek kısa Türkçe özet
    script: Script  # güncellenmiş senaryo; değişmeyen sahneler birebir aynı kalmalı
    regenerate_images: list[int]  # metni aynı kalsa da yeniden çizilecek sahneler (1 tabanlı)
    voice: str  # "same" veya listedeki ses kimliklerinden biri
    rate: Literal["same", "slower", "faster", "normal"]


SYSTEM = """Kısa bilgi videoları için düzeltme editörüsün. Kullanıcı bir videoyu beğenmedi ve not \
yazdı. Notu yorumla ve sadece gereken değişikliği yap:

- Metin/bilgi/ton ile ilgiliyse ilgili sahnelerin narration alanını (ve gerekirse title, \
description, hashtags) değiştir. Dokunulmayan sahnelerin narration ve visual alanlarını harfi \
harfine aynı bırak; değişen her alan o sahnenin yeniden üretilmesine yol açar.
- Görselin içeriği değişecekse o sahnenin visual alanını yeniden yaz (İngilizce, görselde yazı yok).
{media_rules}
- Bir sahnenin narration alanı boşsa, kullanıcı istemedikçe boş kalsın.
- Toplam seslendirme en fazla {max_words} kelime olmalı (video {seconds} saniyeyi geçmemeli).
- summary: neyi değiştirdiğini 1-2 cümleyle Türkçe yaz."""


OMNI_RULES = """- Sahne aynı tarifle sadece yeniden üretilmeliyse (ör. "3. sahne çirkin", "robotun sesi bozuk") \
visual'i değiştirmeden sahne numarasını regenerate_images'a ekle. Her yeniden üretim ücretlidir; \
sadece gereken sahneleri ekle.
- Video ve ses Gemini tarafından birlikte üretilir, ses seçilemez: voice ve rate alanlarını "same" bırak."""

LOCAL_RULES = """- Görsel aynı tarifle sadece yeniden çizilmeliyse (ör. "3. görsel çirkin") visual'i değiştirmeden \
sahne numarasını regenerate_images'a ekle.
- Ses ile ilgiliyse (başka ses, erkek/kadın, hız) voice ve rate alanlarını ayarla; değişiklik yoksa \
"same". voice için sadece şu kimlikler geçerli:
{voices}"""


def _video(video_id: int) -> dict:
    v = db.one("SELECT * FROM videos WHERE id = ?", (video_id,))
    if v is None:
        raise ValueError(f"Video bulunamadı: {video_id}")
    return v


def approve(video_id: int) -> None:
    v = _video(video_id)
    db.execute("UPDATE videos SET status = 'approved' WHERE id = ? AND status = 'review'", (video_id,))
    db.execute("UPDATE subtopics SET status = 'approved' WHERE id = ?", (v["subtopic_id"],))


def revise(video_id: int, feedback: str) -> int:
    """Geri bildirime göre yeni sürüm üretir, yeni video id'sini döndürür."""
    v = _video(video_id)
    progress = lambda text: db.set_progress(v["subtopic_id"], text)  # noqa: E731
    progress("Notun yorumlanıyor, senaryo düzeltiliyor")
    old_script = Script.model_validate_json(v["script"])
    meta = json.loads(v["meta"] or "{}")
    engine = meta.get("engine", "local")
    old_voice = voices.resolve(meta.get("voice"))[0]
    media_rules = OMNI_RULES if engine == "omni" else LOCAL_RULES.format(
        voices="\n".join(f"  {key}: {info['label']} - {info['desc']}" for key, info in voices.VOICES.items()))
    scenes = "\n".join(
        f"Sahne {i}: narration={s.narration!r} | visual={s.visual!r}"
        for i, s in enumerate(old_script.scenes, start=1)
    )
    rev = llm.structured(
        system=SYSTEM.format(
            media_rules=media_rules, max_words=voices.current_length()["words"][1], seconds=voices.current_length()["max_seconds"],
        ),
        prompt=(
            f"Mevcut senaryo (JSON):\n{old_script.model_dump_json(indent=2)}\n\n"
            f"Sahne numaraları:\n{scenes}\n\n"
            + (f"Mevcut ses: {old_voice}, hız: {meta.get('rate', 'normal')}\n\n" if engine != "omni" else "")
            + f"Kullanıcının notu: {feedback}"
        ),
        schema=Revision,
        effort="medium",
    )

    new_meta = {"revision_summary": rev.summary, "feedback": feedback, "engine": engine,
                "narrator": meta.get("narrator", True), "cartoon": meta.get("cartoon", True),
                "voice": rev.voice if rev.voice in voices.VOICES else old_voice,
                "rate": meta.get("rate", "normal") if rev.rate == "same" else rev.rate}

    db.execute("UPDATE videos SET status = 'rejected', feedback = ? WHERE id = ?", (feedback, video_id))
    version = v["version"] + 1
    workdir = Path(v["workdir"]).parent / f"v{version}"
    new_id = db.execute(
        "INSERT INTO videos(subtopic_id, version, script, meta, workdir, status) VALUES(?, ?, ?, ?, ?, 'producing')",
        (v["subtopic_id"], version, rev.script.model_dump_json(), json.dumps(new_meta, ensure_ascii=False), str(workdir)),
    )
    db.execute("UPDATE subtopics SET status = 'producing' WHERE id = ?", (v["subtopic_id"],))
    try:
        if engine == "omni":
            path = gemini_video.produce(
                rev.script,
                workdir,
                prev_dir=Path(v["workdir"]),
                force_scenes=set(rev.regenerate_images),
                on_progress=progress,
                usage_ref=new_id,
                narrator=new_meta["narrator"],
                cartoon=new_meta["cartoon"],
            )
        else:
            path = producer.produce(
                rev.script,
                workdir,
                voice=new_meta["voice"],
                rate=new_meta["rate"],
                prev=(old_script, Path(v["workdir"])),
                force_images=set(rev.regenerate_images),
                force_voice=(new_meta["voice"], new_meta["rate"]) != (old_voice, meta.get("rate", "normal")),
                on_progress=progress,
                max_seconds=voices.current_length()["max_seconds"],
                with_narrator=new_meta["narrator"],
            )
    except Exception as e:
        db.execute("UPDATE videos SET status = 'failed' WHERE id = ?", (new_id,))
        db.execute("UPDATE subtopics SET status = 'failed', error = ? WHERE id = ?", (str(e), v["subtopic_id"]))
        raise
    db.execute("UPDATE videos SET status = 'review', path = ?, meta = ? WHERE id = ?",
               (str(path), json.dumps(new_meta, ensure_ascii=False), new_id))
    db.execute("UPDATE subtopics SET status = 'review', progress = '' WHERE id = ?", (v["subtopic_id"],))
    return new_id
