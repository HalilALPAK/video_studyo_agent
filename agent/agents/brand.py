"""İsim/Marka Ajanı: kullanıcı adının platformlarda boş olup olmadığını kontrol eder,
alınmışsa Claude'dan varyasyon ister ve onları da kontrol eder.

Not: Platformlar resmi bir "kullanıcı adı boş mu" API'si sunmuyor. Kontroller profil
sayfasına bakarak yapılır; giriş duvarı veya hız sınırı olduğunda sonuç "belirsiz" döner.
"""
import re
import time

import requests
from pydantic import BaseModel

from .. import db, llm

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Platform başına geçerli kullanıcı adı kuralı
RULES = {
    "youtube": (r"^[a-z0-9._-]{3,30}$", "3-30 karakter; harf, rakam, nokta, alt çizgi, tire"),
    "tiktok": (r"^[a-z0-9._]{2,24}$", "2-24 karakter; harf, rakam, nokta, alt çizgi"),
    "instagram": (r"^[a-z0-9._]{1,30}$", "1-30 karakter; harf, rakam, nokta, alt çizgi"),
}

PROFILE_URLS = {
    "youtube": "https://www.youtube.com/@{}",
    "tiktok": "https://www.tiktok.com/@{}",
    "instagram": "https://www.instagram.com/{}/",
}

AVAILABLE, TAKEN, UNKNOWN, INVALID = "boş", "alınmış", "belirsiz", "geçersiz"

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def normalize(name: str) -> str:
    return re.sub(r"\s+", "", name.translate(_TR).lower())


def _get(url: str, **kwargs) -> requests.Response | None:
    try:
        return requests.get(url, headers={"User-Agent": UA, **kwargs.pop("headers", {})}, timeout=15, **kwargs)
    except requests.RequestException:
        return None


def _check_youtube(h: str) -> str:
    r = _get(f"https://www.youtube.com/@{h}")
    if r is None:
        return UNKNOWN
    return AVAILABLE if r.status_code == 404 else TAKEN if r.status_code == 200 else UNKNOWN


def _check_tiktok(h: str) -> str:
    r = _get(f"https://www.tiktok.com/@{h}")
    if r is None or r.status_code != 200:
        return UNKNOWN
    if f'"uniqueId":"{h}"' in r.text:
        return TAKEN
    if '"statusCode":10221' in r.text or "Couldn't find this account" in r.text:
        return AVAILABLE
    return UNKNOWN


def _check_instagram(h: str) -> str:
    r = _get(
        "https://www.instagram.com/api/v1/users/web_profile_info/",
        params={"username": h},
        headers={"x-ig-app-id": "936619743392459"},
    )
    if r is None:
        return UNKNOWN
    if r.status_code == 404:
        return AVAILABLE
    if r.status_code == 200:
        try:
            return TAKEN if r.json().get("data", {}).get("user") else AVAILABLE
        except ValueError:
            return UNKNOWN
    return UNKNOWN


CHECKERS = {
    "youtube": _check_youtube,
    "tiktok": _check_tiktok,
    "instagram": _check_instagram,
}


def check_handle(handle: str) -> dict[str, str]:
    results = {}
    for platform, checker in CHECKERS.items():
        if not re.match(RULES[platform][0], handle):
            results[platform] = INVALID
            continue
        results[platform] = checker(handle)
        time.sleep(0.5)
    return results


class Candidates(BaseModel):
    candidates: list[str]


def suggest_variations(name: str, count: int = 8) -> list[str]:
    rules = "\n".join(f"- {p}: {desc}" for p, (_, desc) in RULES.items())
    result = llm.structured(
        system=(
            "Sosyal medya kanalları için kullanıcı adı önerileri üretiyorsun. Öneriler kısa, "
            "akılda kalıcı, Türkçe okunuşu doğal ve tüm platformların kurallarına uygun olmalı. "
            "Sadece küçük harf, rakam, nokta ve alt çizgi kullan; Türkçe karakter kullanma."
        ),
        prompt=(
            f"İstenen isim: {name}\nPlatform kuralları:\n{rules}\n\n"
            f"Bu isim alınmış olabilir. Markayı koruyan {count} varyasyon öner "
            "(ör. bilgikutusu -> bilgi_kutusu, bilgikutusutv, bilgikutusu.tr, thebilgikutusu)."
        ),
        schema=Candidates,
        effort="low",
    )
    seen, out = {normalize(name)}, []
    for c in result.candidates:
        c = normalize(c)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:count]


def run(name: str, with_variations: bool = True) -> list[dict]:
    """İsmi ve (gerekirse) varyasyonları kontrol eder; sonuçları veritabanına yazar."""
    handle = normalize(name)
    handles = [handle]
    first = check_handle(handle)
    rows = [{"handle": handle, "results": first}]
    if with_variations and any(v != AVAILABLE for v in first.values()):
        for h in suggest_variations(name):
            handles.append(h)
            rows.append({"handle": h, "results": check_handle(h)})

    db.execute("DELETE FROM brand_checks WHERE desired = ?", (name,))
    for row in rows:
        for platform, status in row["results"].items():
            db.execute(
                "INSERT INTO brand_checks(desired, handle, platform, status) VALUES(?, ?, ?, ?)",
                (name, row["handle"], platform, status),
            )
    return rows


def choose(handle: str, display_name: str = "") -> None:
    db.set_setting("brand_handle", handle)
    db.set_setting("brand_name", display_name or handle)
