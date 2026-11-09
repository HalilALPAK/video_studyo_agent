"""Orkestratör: ajanları sırayla çalıştıran iş akışı.

Akış kodla yönetilir (her adım belirli); Claude'un yaratıcılık gerektiren işleri
(planlama, senaryo, düzeltme yorumu, isim önerisi) ilgili ajanların içinde yapılır.
"""
import datetime as dt
import json
import logging

from . import config, db, omni, voices
from .agents import analyst, gemini_video, planner, publisher, scriptwriter

log = logging.getLogger(__name__)


def ensure_plan() -> list[dict]:
    """Önümüzdeki PLAN_AHEAD_DAYS gün dolu olacak kadar alt başlık planlar."""
    upcoming = db.one(
        "SELECT COUNT(*) n FROM subtopics WHERE planned_for >= ? AND status = 'planned'",
        (dt.date.today().isoformat(),),
    )["n"]
    need = config.PLAN_AHEAD_DAYS * config.VIDEOS_PER_DAY - upcoming
    if need <= 0 or not db.one("SELECT 1 FROM topics WHERE active = 1"):
        return []
    return planner.plan(need)


def produce_subtopic(subtopic_id: int) -> int:
    """Senaryo yazar, videoyu üretir ve onaya gönderir. Video id'sini döndürür (kaldırıldıysa 0)."""
    row = db.one("SELECT status, mode, angle FROM subtopics WHERE id = ?", (subtopic_id,))
    if row is None or row["status"] == "deleted":
        return 0  # sırada beklerken panelden kaldırıldı ya da konusu değişti
    omni.require_key()
    db.execute("UPDATE subtopics SET status = 'producing', error = '' WHERE id = ?", (subtopic_id,))
    progress = lambda text: db.set_progress(subtopic_id, text)  # noqa: E731
    workdir = config.VIDEO_DIR / str(subtopic_id) / "v1"
    from_prompt = row["mode"] == "prompt"
    # Yarım kalan denemenin senaryosu ve ayarları korunur: aynı metinle üretilen ücretli klipler tekrar ödenmez
    failed = db.one("SELECT id, script, meta FROM videos WHERE subtopic_id = ? AND status = 'failed' AND version = 1 "
                    "ORDER BY id DESC", (subtopic_id,))
    try:
        if failed and failed["script"]:
            script = scriptwriter.Script.model_validate_json(failed["script"])
            video_id = failed["id"]
            old = json.loads(failed["meta"] or "{}")
            meta = {"engine": "omni", "narrator": old.get("narrator", True), "cartoon": old.get("cartoon", True)}
            db.execute("UPDATE videos SET status = 'producing' WHERE id = ?", (video_id,))
        else:
            meta = {"engine": "omni", "narrator": not from_prompt and voices.use_cuma(), "cartoon": not from_prompt}
            progress("Senaryo yazılıyor")
            script = (scriptwriter.write_from_prompt(row["angle"]) if from_prompt
                      else scriptwriter.write(subtopic_id, narrator=meta["narrator"]))
            video_id = db.execute(
                "INSERT INTO videos(subtopic_id, version, script, meta, workdir) VALUES(?, 1, ?, ?, ?)",
                (subtopic_id, script.model_dump_json(), json.dumps(meta), str(workdir)),
            )
        path = gemini_video.produce(script, workdir, on_progress=progress, usage_ref=video_id,
                                    narrator=meta["narrator"], cartoon=meta["cartoon"])
    except Exception as e:
        log.exception("Alt başlık %s üretilemedi", subtopic_id)
        db.execute("UPDATE subtopics SET status = 'failed', error = ?, progress = '' WHERE id = ?", (str(e), subtopic_id))
        db.execute("UPDATE videos SET status = 'failed' WHERE subtopic_id = ? AND status = 'producing'", (subtopic_id,))
        raise
    db.execute("UPDATE videos SET status = 'review', path = ?, meta = ? WHERE id = ?",
               (str(path), json.dumps(meta, ensure_ascii=False), video_id))
    db.execute("UPDATE subtopics SET status = 'review', progress = '' WHERE id = ?", (subtopic_id,))
    return video_id


PROMPT_TOPIC = "Prompt videoları"  # pasif konu: planlayıcı bundan alt başlık üretmez


def add_prompt_video(text: str) -> int:
    """Serbest metinle istenen videoyu kuyruğa ekler, alt başlık id'sini döndürür."""
    db.execute("INSERT OR IGNORE INTO topics(title, active) VALUES(?, 0)", (PROMPT_TOPIC,))
    topic = db.one("SELECT id FROM topics WHERE title = ?", (PROMPT_TOPIC,))
    title = text if len(text) <= 90 else text[:87].rstrip() + "..."
    return db.execute(
        "INSERT INTO subtopics(topic_id, title, angle, planned_for, status, progress, mode) "
        "VALUES(?, ?, ?, ?, 'planned', 'Sırada', 'prompt')",
        (topic["id"], title, text, dt.date.today().isoformat()),
    )


def kickoff(count: int) -> str:
    """Başla adımı: `count` alt başlık planlar ve hepsini hemen üretir (tarihlerini beklemeden)."""
    omni.require_key()
    created = planner.plan(count)
    if not created:
        raise RuntimeError("Konulardan yeni alt başlık çıkarılamadı (hepsi daha önce işlenmiş olabilir). "
                           "Gelişmiş sayfasından yeni bir konu ekleyip tekrar dene.")
    for item in created:
        db.execute("UPDATE subtopics SET progress = 'Sırada' WHERE id = ?", (item["id"],))
    made = 0
    for item in created:
        try:
            made += bool(produce_subtopic(item["id"]))
        except Exception:
            continue  # hata alt başlığa yazıldı; diğerleriyle devam
    return f"{made} video hazırlandı"


def produce_due() -> list[int]:
    due = db.query(
        "SELECT id FROM subtopics WHERE status = 'planned' AND planned_for <= ? ORDER BY planned_for, id",
        (dt.date.today().isoformat(),),
    )
    produced = []
    for row in due:
        try:
            produced.append(produce_subtopic(row["id"]))
        except Exception:
            continue  # hata alt başlığa yazıldı; diğerleriyle devam
    return produced


def publish_approved() -> dict[int, dict]:
    if not publisher.connected_platforms():
        return {}  # henüz bağlı hesap yok; onaylılar panelde beklesin
    return {
        v["id"]: publisher.publish_video(v["id"])
        for v in db.query("SELECT id FROM videos WHERE status = 'approved' ORDER BY id")
    }


def daily() -> dict:
    """Günlük döngü: istatistik -> plan -> üretim (onaya) -> onaylıları yayınla."""
    report = {"stats": analyst.collect_all()}
    report["planned"] = ensure_plan()
    report["produced"] = produce_due()
    report["published"] = publish_approved()
    log.info("Günlük döngü bitti: %s", report)
    return report
