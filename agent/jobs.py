"""Panel için arka plan işleri. Her "şerit" kendi sırasıyla tek tek çalışır; farklı şeritler
paralel ilerler. Böylece isim taraması video üretimini beklemez, ama iki video üretimi
(veya iki yayın) aynı anda çalışıp birbirine karışmaz."""
import datetime as dt
import itertools
import logging
import queue
import threading

log = logging.getLogger(__name__)

_queues: dict[str, queue.Queue] = {}
_jobs: list[dict] = []
_ids = itertools.count(1)
_lock = threading.Lock()


def _run(q: queue.Queue) -> None:
    while True:
        job, fn, args = q.get()
        job["status"], job["started"] = "çalışıyor", dt.datetime.now().strftime("%H:%M:%S")
        try:
            result = fn(*args)
            job["status"], job["result"] = "bitti", "" if result is None else str(result)[:300]
        except Exception as e:
            log.exception("İş başarısız: %s", job["name"])
            job["status"], job["result"] = "hata", str(e)[:500]
        job["finished"] = dt.datetime.now().strftime("%H:%M:%S")


def submit(name: str, fn, *args, lane: str = "main") -> dict:
    job = {"id": next(_ids), "name": name, "lane": lane, "status": "sırada",
           "result": "", "started": "", "finished": ""}
    with _lock:
        _jobs.append(job)
        del _jobs[:-50]
        if lane not in _queues:
            _queues[lane] = queue.Queue()
            threading.Thread(target=_run, args=(_queues[lane],), daemon=True).start()
    _queues[lane].put((job, fn, args))
    return job


def recent() -> list[dict]:
    return list(reversed(_jobs))


def busy(lane: str | None = None) -> bool:
    return any(j["status"] in ("sırada", "çalışıyor") and (lane is None or j["lane"] == lane) for j in _jobs)


def last(lane: str) -> dict | None:
    return next((j for j in reversed(_jobs) if j["lane"] == lane), None)
