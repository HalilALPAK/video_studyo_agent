"""Komut satırı:  python -m agent <komut>

  panel                  Web panelini aç (http://127.0.0.1:5050)
  daily                  Günlük döngü: istatistik -> plan -> üretim -> onaylıları yayınla
  topic "Uzay" [--notes]  Ana konu ekle
  brand "bilgikutusu"    İsmi platformlarda kontrol et, gerekirse varyasyon öner
  plan [--count N]       N yeni alt başlık planla
  produce ID             Bir alt başlığın videosunu hemen üret
  stats                  İstatistikleri çek
  login PLATFORM         Bir platforma giriş yap (youtube, tiktok, instagram)
"""
import argparse
import json
import logging
import sys

from . import config, db, orchestrator
from .agents import analyst, brand, planner


def _login(platform: str) -> int:
    from .agents import publisher

    print("Chrome açılıyor; giriş yapınca oturum otomatik kaydedilecek...")
    print(publisher.login(platform))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.DATA_DIR / "agent.log", encoding="utf-8")],
    )
    db.init()

    parser = argparse.ArgumentParser(prog="python -m agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("panel")
    sub.add_parser("daily")
    p = sub.add_parser("topic")
    p.add_argument("title")
    p.add_argument("--notes", default="")
    p = sub.add_parser("brand")
    p.add_argument("name")
    p = sub.add_parser("plan")
    p.add_argument("--count", type=int, default=config.PLAN_AHEAD_DAYS)
    p = sub.add_parser("produce")
    p.add_argument("subtopic_id", type=int)
    sub.add_parser("stats")
    p = sub.add_parser("login")
    p.add_argument("platform", choices=["youtube", "tiktok", "instagram"])
    args = parser.parse_args()

    if args.cmd == "panel":
        from .web.app import run

        print(f"Panel: http://{config.PANEL_HOST}:{config.PANEL_PORT}")
        run()
    elif args.cmd == "daily":
        print(json.dumps(orchestrator.daily(), ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "topic":
        db.execute("INSERT OR IGNORE INTO topics(title, notes) VALUES(?, ?)", (args.title, args.notes))
        print(f"Konu eklendi: {args.title}")
    elif args.cmd == "brand":
        for row in brand.run(args.name):
            print(f"{row['handle']:<24}" + "  ".join(f"{k}: {v}" for k, v in row["results"].items()))
    elif args.cmd == "plan":
        for item in planner.plan(args.count):
            print(f"{item['planned_for']}  #{item['id']}  {item['title']}")
    elif args.cmd == "produce":
        print(f"Video hazır, onay bekliyor: video #{orchestrator.produce_subtopic(args.subtopic_id)}")
    elif args.cmd == "stats":
        print(analyst.collect_all())
    elif args.cmd == "login":
        return _login(args.platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
