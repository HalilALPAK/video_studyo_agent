"""SQLite deposu. Her çağrı kendi bağlantısını açar; panel thread'leriyle güvenli."""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    title TEXT UNIQUE NOT NULL,
    notes TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- status: planned -> producing -> review -> approved -> published | failed
CREATE TABLE IF NOT EXISTS subtopics (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    title TEXT NOT NULL,
    angle TEXT DEFAULT '',
    planned_for TEXT,
    status TEXT DEFAULT 'planned',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Her düzeltme yeni bir sürüm (version) satırı açar.
-- status: producing -> review -> approved -> publishing -> published | rejected | failed
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    subtopic_id INTEGER NOT NULL REFERENCES subtopics(id),
    version INTEGER NOT NULL,
    script TEXT NOT NULL,
    meta TEXT DEFAULT '{}',
    workdir TEXT,
    path TEXT,
    status TEXT DEFAULT 'producing',
    feedback TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    platform TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    url TEXT DEFAULT '',
    log TEXT DEFAULT '',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, platform)
);

CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    source TEXT DEFAULT 'manual',
    UNIQUE(post_id, day)
);

CREATE TABLE IF NOT EXISTS brand_checks (
    id INTEGER PRIMARY KEY,
    desired TEXT NOT NULL,
    handle TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Ücretli API çağrıları (Gemini Omni anlatıcı klipleri); panel maliyet özetini buradan gösterir
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY,
    video_id INTEGER,
    model TEXT NOT NULL,
    seconds REAL DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


MIGRATIONS = [
    "ALTER TABLE subtopics ADD COLUMN progress TEXT DEFAULT ''",
]


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for sql in MIGRATIONS:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # zaten uygulanmış


def set_progress(subtopic_id: int, text: str) -> None:
    execute("UPDATE subtopics SET progress = ? WHERE id = ?", (text, subtopic_id))


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    """Yazma sorgusu; INSERT için lastrowid, diğerleri için etkilenen satır sayısı döner."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def get_setting(key: str, default: str = "") -> str:
    row = one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
