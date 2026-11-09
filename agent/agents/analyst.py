"""İstatistik Ajanı: günlük istatistikleri toplar, panoya verir ve Planlama Ajanı'na
"hangi konular iyi gidiyor" özetini hazırlar.

YouTube istatistikleri resmi Data API ile (sadece okuma, API anahtarı yeterli) otomatik
çekilir. Instagram ve TikTok için şimdilik panelden elle giriş yapılır.
"""
import datetime as dt
import logging
from collections import defaultdict

import requests

from .. import config, db
from .scriptwriter import Script

log = logging.getLogger(__name__)
YT_API = "https://www.googleapis.com/youtube/v3"


def _yt(endpoint: str, **params) -> dict:
    r = requests.get(f"{YT_API}/{endpoint}", params={"key": config.YOUTUBE_API_KEY, **params}, timeout=20)
    r.raise_for_status()
    return r.json()


def collect_youtube() -> str:
    if not (config.YOUTUBE_API_KEY and config.YOUTUBE_CHANNEL_ID):
        return "YouTube istatistikleri atlandı (YOUTUBE_API_KEY / YOUTUBE_CHANNEL_ID yok)."
    channel = _yt("channels", part="contentDetails", id=config.YOUTUBE_CHANNEL_ID)
    if not channel.get("items"):
        return "YouTube kanalı bulunamadı; YOUTUBE_CHANNEL_ID'yi kontrol et."
    uploads = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    titles: dict[str, str] = {}  # başlık -> video id
    page_token = None
    for _ in range(4):  # en son 200 video yeterli
        page = _yt("playlistItems", part="snippet", playlistId=uploads, maxResults=50,
                   **({"pageToken": page_token} if page_token else {}))
        for item in page.get("items", []):
            snippet = item["snippet"]
            titles.setdefault(snippet["title"].strip(), snippet["resourceId"]["videoId"])
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    posts = db.query(
        "SELECT p.id, p.url, v.script FROM posts p JOIN videos v ON v.id = p.video_id "
        "WHERE p.platform = 'youtube' AND p.status = 'ok'"
    )
    matched = {}
    for post in posts:
        title = Script.model_validate_json(post["script"]).title[:100].strip()
        if title in titles:
            matched[titles[title]] = post

    today = dt.date.today().isoformat()
    ids = list(matched)
    for i in range(0, len(ids), 50):
        for item in _yt("videos", part="statistics", id=",".join(ids[i:i + 50])).get("items", []):
            s, post = item["statistics"], matched[item["id"]]
            save_stats(post["id"], int(s.get("viewCount", 0)), int(s.get("likeCount", 0)),
                       int(s.get("commentCount", 0)), source="youtube_api", day=today)
            if not post["url"]:
                db.execute("UPDATE posts SET url = ? WHERE id = ?",
                           (f"https://youtube.com/shorts/{item['id']}", post["id"]))
    return f"YouTube: {len(matched)}/{len(posts)} video eşleşti ve güncellendi."


def save_stats(post_id: int, views: int, likes: int, comments: int,
               source: str = "manual", day: str | None = None) -> None:
    db.execute(
        "INSERT INTO stats(post_id, day, views, likes, comments, source) VALUES(?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(post_id, day) DO UPDATE SET views = excluded.views, likes = excluded.likes, "
        "comments = excluded.comments, source = excluded.source",
        (post_id, day or dt.date.today().isoformat(), views, likes, comments, source),
    )


def collect_all() -> str:
    try:
        return collect_youtube()
    except requests.RequestException as e:
        log.exception("YouTube istatistikleri alınamadı")
        return f"YouTube istatistik hatası: {e}"


def performance_rows() -> list[dict]:
    """Her yayınlanmış alt başlık için platformların en güncel değerlerinin toplamı."""
    rows = db.query(
        """
        SELECT s.id sid, s.title, t.title topic, p.platform, st.views, st.likes, st.comments
        FROM posts p
        JOIN videos v ON v.id = p.video_id
        JOIN subtopics s ON s.id = v.subtopic_id
        JOIN topics t ON t.id = s.topic_id
        JOIN stats st ON st.post_id = p.id
             AND st.day = (SELECT MAX(day) FROM stats WHERE post_id = p.id)
        """
    )
    agg: dict[int, dict] = {}
    for r in rows:
        a = agg.setdefault(r["sid"], {"title": r["title"], "topic": r["topic"], "views": 0,
                                      "likes": 0, "comments": 0, "platforms": {}})
        a["views"] += r["views"]
        a["likes"] += r["likes"]
        a["comments"] += r["comments"]
        a["platforms"][r["platform"]] = r["views"]
    return sorted(agg.values(), key=lambda a: a["views"], reverse=True)


def topic_rows() -> list[dict]:
    by_topic = defaultdict(list)
    for r in performance_rows():
        by_topic[r["topic"]].append(r["views"])
    return sorted(
        ({"topic": t, "videos": len(v), "avg_views": round(sum(v) / len(v))} for t, v in by_topic.items()),
        key=lambda r: r["avg_views"], reverse=True,
    )


def performance_summary() -> str:
    rows = performance_rows()
    if not rows:
        return "Henüz istatistik yok."
    lines = ["Ana konu ortalamaları (izlenme):"]
    lines += [f"- {t['topic']}: {t['avg_views']} ({t['videos']} video)" for t in topic_rows()]
    lines.append("En iyi videolar:")
    lines += [f"- [{r['topic']}] {r['title']}: {r['views']} izlenme, {r['likes']} beğeni" for r in rows[:5]]
    if len(rows) > 5:
        lines.append("En zayıf videolar:")
        lines += [f"- [{r['topic']}] {r['title']}: {r['views']} izlenme" for r in rows[-3:]]
    return "\n".join(lines)
