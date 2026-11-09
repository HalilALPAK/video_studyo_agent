"""Konu Planlama Ajanı: ana konuları alt başlıklara böler, günlere dağıtır,
daha önce işlenenleri tekrarlamaz ve istatistik geri bildirimini dikkate alır."""
import datetime as dt
import re

from pydantic import BaseModel

from .. import config, db, llm
from . import analyst


class PlannedItem(BaseModel):
    topic: str
    title: str
    angle: str


class Plan(BaseModel):
    items: list[PlannedItem]


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _next_free_dates(count: int) -> list[str]:
    """Bugünden itibaren günde VIDEOS_PER_DAY kapasiteyle boş tarihleri döndürür."""
    used = {
        r["planned_for"]: r["n"]
        for r in db.query(
            "SELECT planned_for, COUNT(*) n FROM subtopics WHERE planned_for >= ? GROUP BY planned_for",
            (dt.date.today().isoformat(),),
        )
    }
    dates, day = [], dt.date.today()
    while len(dates) < count:
        key = day.isoformat()
        free = config.VIDEOS_PER_DAY - used.get(key, 0)
        dates.extend([key] * max(free, 0))
        day += dt.timedelta(days=1)
    return dates[:count]


def plan(count: int) -> list[dict]:
    topics = db.query("SELECT id, title, notes FROM topics WHERE active = 1")
    if not topics:
        raise RuntimeError("Önce en az bir ana konu ekle.")
    done = db.query("SELECT s.title, t.title topic FROM subtopics s JOIN topics t ON t.id = s.topic_id")
    done_text = "\n".join(f"- [{d['topic']}] {d['title']}" for d in done) or "(henüz yok)"
    topics_text = "\n".join(f"- {t['title']}" + (f"  [not: {t['notes']}]" if t["notes"] else "") for t in topics)

    result = llm.structured(
        system=(
            "Kısa dikey bilgi videoları (Shorts/Reels/TikTok) yayınlayan bir Türkçe kanalın içerik "
            "planlayıcısısın. Her alt başlık tek bir 30-90 saniyelik videoda anlatılabilecek kadar dar, "
            "merak uyandırıcı ve doğruluğu kontrol edilebilir olmalı. Daha önce işlenen başlıkları ve "
            "onların çok yakın benzerlerini asla tekrar önerme. Performans verisi varsa iyi giden "
            "konu ve açılara ağırlık ver, kötü gidenlerden uzaklaş ama çeşitliliği koru."
        ),
        prompt=(
            f"Ana konular:\n{topics_text}\n\n"
            f"Daha önce planlanan/işlenen başlıklar:\n{done_text}\n\n"
            f"Performans özeti:\n{analyst.performance_summary()}\n\n"
            f"{count} yeni alt başlık öner. 'topic' alanı yukarıdaki ana konulardan birinin adıyla "
            "birebir aynı olsun. 'angle' videonun kancasını/bakış açısını bir cümleyle anlatsın."
        ),
        schema=Plan,
        effort="medium",
    )

    def match_topic(name: str) -> int | None:
        # Claude bazen konu adına not veya parantez ekler; baştaki ad yeterli
        key = _norm(re.split(r"[(\[]", name)[0])
        for t in topics:
            if key == _norm(t["title"]) or key.startswith(_norm(t["title"])):
                return t["id"]
        return topics[0]["id"] if len(topics) == 1 else None

    seen = {_norm(d["title"]) for d in done}
    accepted = []
    for item in result.items:
        topic_id = match_topic(item.topic)
        if topic_id is None or _norm(item.title) in seen:
            continue
        seen.add(_norm(item.title))
        accepted.append((topic_id, item))

    created = []
    for (topic_id, item), day in zip(accepted[:count], _next_free_dates(len(accepted[:count]))):
        sid = db.execute(
            "INSERT INTO subtopics(topic_id, title, angle, planned_for) VALUES(?, ?, ?, ?)",
            (topic_id, item.title, item.angle, day),
        )
        created.append({"id": sid, "title": item.title, "planned_for": day})
    return created
