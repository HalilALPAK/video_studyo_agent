"""Yerel web paneli.

Ana sayfa (/) 4 adımlı akıştır: Başla -> İsim -> Videolar -> Yayın.
/gelismis sayfası takvim, istatistik, konu yönetimi ve iş geçmişini gösterir.
"""
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from .. import config, db, jobs, omni, orchestrator, voices
from ..agents import analyst, brand, planner, publisher, reviewer
from ..agents.scriptwriter import Script

app = Flask(__name__)
app.secret_key = "local-panel"

STATUS_TR = {
    "planned": "Sırada", "producing": "Hazırlanıyor", "review": "Onayını bekliyor",
    "revising": "Düzeltiliyor", "approved": "Yayına hazır", "publishing": "Yükleniyor",
    "published": "Yayınlandı", "publish_failed": "Bazı hesaplara yüklenemedi", "failed": "Hata",
    "rejected": "Reddedildi", "ok": "Yüklendi", "pending": "Bekliyor", "deleted": "Kaldırıldı",
}
STAGES = ["Senaryo", "Gemini video", "Altyazı", "Birleştirme"]


@app.template_filter("script")
def _script(raw: str) -> Script:
    return Script.model_validate_json(raw)


@app.template_filter("meta")
def _meta(raw: str) -> dict:
    return json.loads(raw or "{}")


@app.template_filter("api_cost")
def _api_cost(video_id: int) -> float:
    return omni.video_cost(video_id)


@app.template_filter("tr")
def _tr(status: str) -> str:
    return STATUS_TR.get(status, status)


STAGE_KEYS = [("birleştir", 4), ("altyazı", 3), ("gemini", 2), ("senaryo", 1), ("notun", 1)]


def _stage(progress: str) -> int:
    """İlerleme metninden aşama numarası (0: sırada, 1-4: STAGES)."""
    text = (progress or "").lower()
    return next((n for key, n in STAGE_KEYS if key in text), 0)


def _back(anchor: str = ""):
    return redirect(url_for("index") + (f"#{anchor}" if anchor else ""))


# --- Durum hesaplama ----------------------------------------------------------------

def _brand_state() -> dict:
    rows = db.query("SELECT * FROM brand_checks ORDER BY id")
    desired = db.get_setting("brand_desired")
    table: dict[str, dict] = {}
    for r in rows:
        if r["desired"] == desired and r["platform"] in brand.CHECKERS:
            table.setdefault(r["handle"], {})[r["platform"]] = r["status"]
    candidates = [
        {"handle": h, "results": res, "free": sum(v == brand.AVAILABLE for v in res.values()),
         "taken": sum(v == brand.TAKEN for v in res.values())}
        for h, res in table.items()
    ]
    original = candidates[0] if candidates else None
    alternatives = sorted(candidates[1:], key=lambda c: (c["taken"], -c["free"]))
    return {
        "desired": desired,
        "chosen": db.get_setting("brand_handle"),
        "display": db.get_setting("brand_name"),
        "scanning": jobs.busy("brand"),
        "error": (j := jobs.last("brand")) and j["status"] == "hata" and j["result"],
        "original": original,
        "original_ok": bool(original) and original["taken"] == 0 and original["free"] > 0,
        "alternatives": alternatives,
    }


def _signature() -> str:
    """Panel durumunun özeti; değişince sayfa kendini yeniler."""
    parts = [
        json.dumps([(j["id"], j["status"]) for j in jobs.recent()]),
        json.dumps(db.query("SELECT id, status, progress FROM subtopics")),
        json.dumps(db.query("SELECT id, status FROM videos")),
        json.dumps(db.query("SELECT id, status FROM posts")),
        str(db.one("SELECT COUNT(*) n FROM brand_checks")["n"]),
        json.dumps([a["connected"] for a in publisher.accounts()]),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


@app.get("/")
def index():
    topics = db.query("SELECT * FROM topics WHERE active = 1 ORDER BY id")
    brand_state = _brand_state()
    in_progress = db.query(
        "SELECT s.*, t.title topic FROM subtopics s JOIN topics t ON t.id = s.topic_id "
        "WHERE s.status = 'producing' OR (s.status = 'planned' AND s.progress = 'Sırada') ORDER BY s.id"
    )
    for s in in_progress:
        s["stage"] = _stage(s["progress"])
    failed = db.query(
        "SELECT s.*, t.title topic FROM subtopics s JOIN topics t ON t.id = s.topic_id "
        "WHERE s.status = 'failed' ORDER BY s.id DESC LIMIT 5"
    )
    review = db.query(
        "SELECT v.*, s.title sub_title, t.title topic FROM videos v JOIN subtopics s ON s.id = v.subtopic_id "
        "JOIN topics t ON t.id = s.topic_id WHERE v.status = 'review' ORDER BY v.id"
    )
    ready = db.query(
        "SELECT v.*, s.title sub_title FROM videos v JOIN subtopics s ON s.id = v.subtopic_id "
        "WHERE v.status IN ('approved', 'publishing', 'publish_failed', 'published') ORDER BY v.id DESC LIMIT 20"
    )
    for v in ready:
        v["posts"] = db.query("SELECT * FROM posts WHERE video_id = ? ORDER BY id", (v["id"],))

    accounts = publisher.accounts()
    started = bool(brand_state["desired"] and topics)
    waiting_publish = any(v["status"] != "published" for v in ready)
    # Her adım: "done" (tamam), "active" (şimdi senin/sistemin sırası) veya "waiting" (henüz değil)
    step = {
        1: "done" if started else "active",
        2: "waiting" if not started else "done" if brand_state["chosen"] else "active",
        3: "waiting" if not started else "active" if (in_progress or review or failed or not ready) else "done",
        4: "waiting" if not ready else "active" if waiting_publish else "done",
    }

    return render_template(
        "index.html",
        topics=topics,
        brand=brand_state,
        platforms=list(brand.CHECKERS),
        platform_labels=publisher.PLATFORM_LABELS,
        profile_urls=brand.PROFILE_URLS,
        in_progress=in_progress,
        stages=STAGES,
        failed=failed,
        review=review,
        ready=ready,
        accounts=accounts,
        login_busy=jobs.busy("login"),
        login_job=jobs.last("login"),
        saved_email=_credentials.get("email", ""),
        producing=jobs.busy("main"),
        main_error=(j := jobs.last("main")) and j["status"] == "hata" and j["result"],
        publishing=jobs.busy("publish"),
        step=step,
        lengths=voices.LENGTHS,
        current_length=db.get_setting("video_length", voices.DEFAULT_LENGTH),
        price_per_second=omni.TOKENS_PER_SECOND * omni.PRICE_OUTPUT,
        key_hint=(k := omni.api_key()) and f"…{k[-4:]}",
        api_usage=omni.usage_summary(),
        signature=_signature(),
    )


def _save_settings(form) -> str | None:
    """Süre ve Gemini anahtarını kaydeder. Sorun varsa kullanıcıya gösterilecek mesajı döndürür."""
    if form.get("length") in voices.LENGTHS:
        db.set_setting("video_length", form["length"])
    if form.get("forget_key"):
        db.set_setting("gemini_api_key", "")
    key = form.get("gemini_api_key", "").strip()
    if key:
        try:
            omni.verify(key)
        except omni.OmniError as e:
            return str(e)
        db.set_setting("gemini_api_key", key)
    return None


@app.post("/settings")
def settings():
    error = _save_settings(request.form)
    flash(error or "Ayarlar kaydedildi; bundan sonraki videolarda kullanılacak.")
    return _back("adim3")


@app.get("/api/signature")
def api_signature():
    return jsonify(signature=_signature())


# --- 1. Başla -----------------------------------------------------------------------

def _set_topics(titles: list[str]) -> list[str]:
    """Konu listesini verilenle değiştirir: listede olmayanlar pasif olur (geçmişleri tekrar önlemek için
    silinmez), henüz başlamamış alt başlıkları iptal edilir. Pasif kalan konuların adlarını döndürür."""
    wanted = {t.casefold(): t for t in titles}
    removed = []
    for t in db.query("SELECT id, title, active FROM topics"):
        keep = t["title"].casefold() in wanted
        if t["active"] and not keep:
            removed.append(t["title"])
        db.execute("UPDATE topics SET active = ? WHERE id = ?", (int(keep), t["id"]))
        wanted.pop(t["title"].casefold(), None)
    for title in wanted.values():
        db.execute("INSERT INTO topics(title) VALUES(?)", (title,))
    db.execute("UPDATE subtopics SET status = 'deleted', progress = '' WHERE status = 'planned' "
               "AND topic_id IN (SELECT id FROM topics WHERE active = 0)")
    return removed


@app.post("/start")
def start():
    """1. adım: ilk kurulum ve sonradan "Değiştir" ile düzenleme aynı formu kullanır."""
    name = request.form.get("name", "").strip()
    topics = [t.strip() for t in request.form.get("topics", "").splitlines() if t.strip()]
    count = max(1, min(int(request.form.get("count") or 1), 5))
    if not name or not topics:
        flash("Kanal adını ve en az bir konuyu yazmalısın.")
        return _back("adim1")
    messages = [error] if (error := _save_settings(request.form)) else []
    if name != db.get_setting("brand_desired"):
        db.set_setting("brand_desired", name)
        db.set_setting("brand_name", name)  # isim seçilene kadar senaryolarda bu kullanılır
        db.set_setting("brand_handle", "")
        jobs.submit(f"İsim taraması: {name}", brand.run, name, lane="brand")
        messages.append(f"'{name}' platformlarda taranıyor.")
    removed = _set_topics(topics)
    if removed:
        messages.append(f"Çıkarılan konular ({', '.join(removed)}) için sırada bekleyen videolar iptal edildi.")
    if request.form.get("produce") and not omni.api_key():
        messages.append("Video üretimi başlamadı: önce Gemini API anahtarını gir.")
    elif request.form.get("produce"):
        jobs.submit(f"{count} video", orchestrator.kickoff, count, lane="main")
        messages.append(f"{count} video hazırlanmaya başladı.")
    else:
        messages.append("Kaydedildi. Videoları hazır olduğunda 3. adımdan başlatabilirsin.")
    flash(" ".join(messages))
    return _back("adim2" if not db.get_setting("brand_handle") else "adim3")


# --- 2. İsim ------------------------------------------------------------------------

@app.post("/brand")
def brand_check():
    name = request.form.get("name", "").strip()
    if name:
        db.set_setting("brand_desired", name)
        db.set_setting("brand_handle", "")
        jobs.submit(f"İsim taraması: {name}", brand.run, name, lane="brand")
    return _back("adim2")


@app.post("/brand/choose")
def brand_choose():
    handle = request.form["handle"]
    brand.choose(handle, request.form.get("display_name", "").strip() or db.get_setting("brand_desired"))
    flash(f"Kanal adın @{handle} olarak kaydedildi. Hesapları açarken bu kullanıcı adını al.")
    return _back("adim3")


@app.post("/brand/reset")
def brand_reset():
    db.set_setting("brand_handle", "")
    return _back("adim2")


# --- 3. Videolar --------------------------------------------------------------------

@app.get("/media/<int:video_id>")
def media(video_id: int):
    v = db.one("SELECT path FROM videos WHERE id = ?", (video_id,))
    if not v or not v["path"] or not Path(v["path"]).exists():
        abort(404)
    return send_file(v["path"], mimetype="video/mp4", conditional=True)


@app.post("/videos/<int:video_id>/approve")
def approve(video_id: int):
    reviewer.approve(video_id)
    flash("Video onaylandı. Yayın adımından paylaşabilirsin.")
    return _back("adim4")


@app.post("/videos/<int:video_id>/revise")
def revise(video_id: int):
    feedback = request.form.get("feedback", "").strip()
    if not feedback:
        flash("Neyi beğenmediğini yazmalısın.")
        return _back("adim3")
    v = db.one("SELECT subtopic_id FROM videos WHERE id = ?", (video_id,))
    db.execute("UPDATE videos SET status = 'revising' WHERE id = ? AND status = 'review'", (video_id,))
    db.execute("UPDATE subtopics SET status = 'producing', progress = 'Notun yorumlanıyor' WHERE id = ?",
               (v["subtopic_id"],))
    jobs.submit(f"Düzeltme: video {video_id}", reviewer.revise, video_id, feedback, lane="main")
    flash("Notunu aldım; sadece gereken kısımlar yeniden hazırlanıyor.")
    return _back("adim3")


def _remove_subtopic(subtopic_id: int) -> str | None:
    """Alt başlığı ve tüm video sürümlerini kaldırır; olmuyorsa nedenini döndürür. Başlık 'deleted'
    olarak kalır ki planlayıcı aynı başlığı bir daha önermesin."""
    s = db.one("SELECT status FROM subtopics WHERE id = ?", (subtopic_id,))
    if s is None:
        return "Video bulunamadı."
    if s["status"] in ("producing", "publishing"):
        return "Şu an üzerinde çalışılıyor; bitince kaldırabilirsin."
    if db.one("SELECT 1 FROM posts p JOIN videos v ON v.id = p.video_id WHERE v.subtopic_id = ? AND p.status = 'ok'",
              (subtopic_id,)):
        return "Bu video en az bir hesapta yayınlandı; önce oradan silmen gerekir."
    db.execute("DELETE FROM posts WHERE video_id IN (SELECT id FROM videos WHERE subtopic_id = ?)", (subtopic_id,))
    db.execute("DELETE FROM videos WHERE subtopic_id = ?", (subtopic_id,))
    db.execute("UPDATE subtopics SET status = 'deleted', progress = '', error = '' WHERE id = ?", (subtopic_id,))
    folder = (config.VIDEO_DIR / str(subtopic_id)).resolve()
    if folder.parent == config.VIDEO_DIR.resolve():
        shutil.rmtree(folder, ignore_errors=True)
    return None


@app.post("/subtopics/<int:subtopic_id>/remove")
def remove_subtopic(subtopic_id: int):
    title = (db.one("SELECT title FROM subtopics WHERE id = ?", (subtopic_id,)) or {}).get("title", "")
    error = _remove_subtopic(subtopic_id)
    flash(error or f"'{title}' kaldırıldı; bu başlık bir daha önerilmeyecek.")
    return _back(request.form.get("anchor", "adim3"))


@app.post("/more")
def more():
    if not omni.api_key():
        flash("Önce 1. adımdaki Değiştir bölümünden Gemini API anahtarını gir.")
        return _back("adim1")
    count = max(1, min(int(request.form.get("count") or 1), 5))
    jobs.submit(f"{count} yeni video", orchestrator.kickoff, count, lane="main")
    flash(f"{count} yeni video hazırlanıyor.")
    return _back("adim3")


@app.post("/subtopics/<int:subtopic_id>/produce")
def produce(subtopic_id: int):
    if not omni.api_key():
        flash("Önce 1. adımdaki Değiştir bölümünden Gemini API anahtarını gir.")
        return _back("adim1")
    db.set_progress(subtopic_id, "Sırada")
    db.execute("UPDATE subtopics SET status = 'planned', error = '' WHERE id = ?", (subtopic_id,))
    jobs.submit(f"Üretim: alt başlık {subtopic_id}", orchestrator.produce_subtopic, subtopic_id, lane="main")
    return _back("adim3")


# --- 4. Yayın -----------------------------------------------------------------------

# Form doldurma için e-posta/şifre sadece panel açıkken bellekte tutulur, diske yazılmaz.
_credentials: dict[str, str] = {}


@app.post("/accounts/credentials")
def account_credentials():
    if request.form.get("clear"):
        _credentials.clear()
        flash("E-posta ve şifre bellekten silindi.")
    else:
        _credentials["email"] = request.form.get("email", "").strip()
        if request.form.get("password"):  # boş bırakılırsa önceki şifre kalır
            _credentials["password"] = request.form["password"]
        flash("Kaydedildi (sadece bu oturum için). Artık Giriş/Kayıt formları otomatik doldurulacak.")
    return _back("adim4")


@app.post("/accounts/<platform>/login")
def account_login(platform: str):
    if platform not in config.PLATFORMS:
        abort(404)
    signup = request.form.get("mode") == "signup"
    fill = None
    if _credentials.get("email"):
        handle = db.get_setting("brand_handle") or brand.normalize(db.get_setting("brand_desired") or "")
        fill = {**_credentials, "name": db.get_setting("brand_name") or handle, "username": handle}
    label = publisher.PLATFORM_LABELS.get(platform, platform)
    jobs.submit(f"{label} {'kaydı' if signup else 'girişi'}", publisher.login, platform, signup, fill, lane="login")
    flash(f"Video Stüdyosu Chrome penceresinde {label} {'kayıt' if signup else 'giriş'} sayfası açılıyor.")
    return _back("adim4")


@app.post("/videos/<int:video_id>/publish")
def publish(video_id: int):
    if not publisher.connected_platforms():
        flash("Önce en az bir hesabı bağlamalısın.")
        return _back("adim4")
    jobs.submit(f"Yayın: video {video_id}", publisher.publish_video, video_id, lane="publish")
    flash("Yükleme başladı; her hesap için birkaç dakika sürebilir.")
    return _back("adim4")


# --- Gelişmiş sayfa -----------------------------------------------------------------

@app.get("/gelismis")
def advanced():
    today = dt.date.today().isoformat()
    review = db.query(
        "SELECT v.*, s.title sub_title, t.title topic FROM videos v JOIN subtopics s ON s.id = v.subtopic_id "
        "JOIN topics t ON t.id = s.topic_id WHERE v.status = 'review' ORDER BY v.id"
    )
    calendar = db.query(
        "SELECT s.*, t.title topic FROM subtopics s JOIN topics t ON t.id = s.topic_id "
        "WHERE s.planned_for >= ? OR s.status NOT IN ('published') ORDER BY s.planned_for, s.id LIMIT 60",
        ((dt.date.today() - dt.timedelta(days=3)).isoformat(),),
    )
    posts = db.query(
        "SELECT p.*, s.title sub_title, v.status video_status, "
        "(SELECT views FROM stats WHERE post_id = p.id ORDER BY day DESC LIMIT 1) views "
        "FROM posts p JOIN videos v ON v.id = p.video_id JOIN subtopics s ON s.id = v.subtopic_id "
        "ORDER BY p.id DESC LIMIT 60"
    )
    failed_videos = db.query(
        "SELECT v.id, s.title FROM videos v JOIN subtopics s ON s.id = v.subtopic_id WHERE v.status = 'publish_failed'"
    )
    brand_rows = db.query("SELECT * FROM brand_checks ORDER BY id")
    brand_table: dict[str, dict] = {}
    for r in brand_rows:
        brand_table.setdefault(r["handle"], {})[r["platform"]] = r["status"]
    return render_template(
        "advanced.html",
        today=today,
        review=review,
        calendar=calendar,
        posts=posts,
        failed_videos=failed_videos,
        topics=db.query("SELECT * FROM topics ORDER BY id"),
        performance=analyst.performance_rows(),
        topic_perf=analyst.topic_rows(),
        brand_table=brand_table,
        brand_desired=brand_rows[0]["desired"] if brand_rows else "",
        brand_platforms=list(brand.CHECKERS),
        profile_urls=brand.PROFILE_URLS,
        brand_name=db.get_setting("brand_name"),
        brand_handle=db.get_setting("brand_handle"),
        jobs=jobs.recent(),
        busy=jobs.busy(),
        config=config,
    )


@app.post("/subtopics/<int:subtopic_id>/delete")
def delete_subtopic(subtopic_id: int):
    db.execute("DELETE FROM subtopics WHERE id = ? AND status IN ('planned', 'failed') "
               "AND NOT EXISTS (SELECT 1 FROM videos WHERE subtopic_id = ?)", (subtopic_id, subtopic_id))
    return redirect(request.referrer or url_for("advanced"))


@app.post("/topics")
def add_topic():
    title = request.form.get("title", "").strip()
    if title:
        db.execute("INSERT OR IGNORE INTO topics(title, notes) VALUES(?, ?)",
                   (title, request.form.get("notes", "").strip()))
    return redirect(request.referrer or url_for("advanced"))


@app.post("/topics/<int:topic_id>/toggle")
def toggle_topic(topic_id: int):
    db.execute("UPDATE topics SET active = 1 - active WHERE id = ?", (topic_id,))
    return redirect(request.referrer or url_for("advanced"))


@app.post("/plan")
def plan():
    count = int(request.form.get("count") or config.PLAN_AHEAD_DAYS)
    jobs.submit(f"Planlama: {count} alt başlık", planner.plan, count, lane="main")
    return redirect(request.referrer or url_for("advanced"))


@app.post("/stats/manual")
def stats_manual():
    analyst.save_stats(int(request.form["post_id"]), int(request.form.get("views") or 0),
                       int(request.form.get("likes") or 0), int(request.form.get("comments") or 0))
    return redirect(request.referrer or url_for("advanced"))


@app.post("/stats/collect")
def stats_collect():
    jobs.submit("İstatistik topla", analyst.collect_all, lane="stats")
    return redirect(request.referrer or url_for("advanced"))


@app.post("/daily")
def daily():
    jobs.submit("Günlük döngü", orchestrator.daily, lane="main")
    return redirect(request.referrer or url_for("advanced"))


def run() -> None:
    db.init()
    app.run(host=config.PANEL_HOST, port=config.PANEL_PORT, debug=False, threaded=True)
