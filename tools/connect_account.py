"""Hesap bağlama yardımcısı. social-auto-upload'ın ortamında çalışır (playwright orada kurulu).

Gerçek Chrome'u kalıcı bir "Video Stüdyosu" profiliyle açar (otomasyon izi olmadan; Google
girişi, şifre önerileri ve senkronizasyon normal çalışır). Kullanıcı giriş yapınca bunu
çerezlerden algılar ve oturumu social-auto-upload'ın beklediği storage_state dosyasına yazar.
Profil kalıcı olduğu için bir kez giriş yapılan hesap sonraki bağlamalarda hazır gelir.

--signup ile kayıt sayfası açılır. --fill verilirse stdin'den JSON (email, password, name,
username) okunur ve sayfadaki boş alanlar bununla doldurulur; doğrulama kodu, captcha, doğum
tarihi ve "Gönder" kullanıcıdadır. Bilgiler diske yazılmaz.

    python tools/connect_account.py --platform youtube --out cookies/youtube_main.json \
        --profile data/chrome-profile --port 9333 --chrome "C:/.../chrome.exe"
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

# platform: (giriş adresi, giriş yapılınca oluşan çerez, oturum dosyasına alınacak alan adları)
LOGINS = {
    "youtube": ("https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fstudio.youtube.com%2F",
                ("youtube.com", "LOGIN_INFO"), ["youtube.com", "google.com"]),
    "instagram": ("https://www.instagram.com/accounts/login/",
                  ("instagram.com", "sessionid"), ["instagram.com"]),
    "tiktok": ("https://www.tiktok.com/login",
               ("tiktok.com", "sessionid"), ["tiktok.com"]),
}
SIGNUPS = {
    "youtube": "https://accounts.google.com/signup/v2/createaccount?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2Fcreate_channel",
    "instagram": "https://www.instagram.com/accounts/emailsignup/",
    "tiktok": "https://www.tiktok.com/signup/phone-or-email/email",
}

# Boş ve görünür alanları bir kez doldurur (kullanıcının yazdığını ezmez). React'ın değişikliği
# görmesi için değer yerel setter ile atanıp input/change olayı tetiklenir.
FILL_JS = """(d) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const rules = [
    [el => el.type === 'password', d.password],
    [(el, k) => el.type === 'email' || /e-?mail|e-posta|emailorphone|identifier|reg_email|phone_or_email/.test(k), d.email],
    [(el, k) => /fullname|full name|ad soyad|adı soyadı|tam ad/.test(k), d.name],
    [(el, k) => /lastname|last name|last_name|surname|soyad/.test(k), d.last],
    [(el, k) => /firstname|first name|first_name|adın/.test(k), d.first],
    [(el, k) => /username|user name|kullanıcı adı/.test(k), d.username],
  ];
  let n = 0;
  for (const el of document.querySelectorAll('input')) {
    if (el.dataset.vsFilled || el.value || el.disabled || el.readOnly || !visible(el)) continue;
    if (!['text', 'email', 'password', 'tel', ''].includes(el.type)) continue;
    const k = [el.name, el.id, el.autocomplete, el.placeholder, el.getAttribute('aria-label')]
      .join(' ').toLowerCase();
    const hit = rules.find(([test]) => test(el, k));
    if (!hit || !hit[1]) continue;
    el.dataset.vsFilled = '1';
    setter.call(el, hit[1]);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    n++;
  }
  return n;
}"""


def cdp_alive(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return True
    except OSError:
        return False


def ensure_chrome(chrome: str, profile: Path, port: int, url: str) -> bool:
    """Chrome kapalıysa açar (bu betik bitince kapanmasın diye ayrı süreç olarak). Açtıysa True."""
    if cdp_alive(port):
        return False
    profile.mkdir(parents=True, exist_ok=True)
    # Betik bitince kapanmasın; çıktıları da devralmasın, yoksa bizi çağıran süreç Chrome kapanana kadar bekler
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    subprocess.Popen(
        [chrome, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
         "--no-first-run", "--no-default-browser-check",
         # Google ile giriş yapınca eklentiler de senkronlanıyor; arka plan sayfaları CDP bağlantısını
         # dakikalarca kilitliyor. Bu profil sadece yükleme için, eklentiye gerek yok (şifreler yine gelir).
         "--disable-extensions", url],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **detach,
    )
    for _ in range(60):
        if cdp_alive(port):
            return True
        time.sleep(0.5)
    raise RuntimeError("Chrome açılamadı.")


def _matches(domain: str, allowed: list[str]) -> bool:
    domain = domain.lstrip(".")
    return any(domain == a or domain.endswith("." + a) for a in allowed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=list(LOGINS))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--signup", action="store_true", help="giriş yerine kayıt sayfasını aç")
    parser.add_argument("--fill", action="store_true", help="stdin'deki JSON ile form alanlarını doldur")
    args = parser.parse_args()

    url, (cookie_domain, cookie_name), keep = LOGINS[args.platform]
    if args.signup:
        url = SIGNUPS[args.platform]
    fill = json.loads(sys.stdin.read() or "{}") if args.fill else {}
    if fill.get("name") and not fill.get("first"):
        first, _, last = fill["name"].partition(" ")
        fill.update(first=first, last=last or first)
    launched = ensure_chrome(args.chrome, args.profile, args.port, url)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        context = browser.contexts[0]
        if launched:
            page = next((pg for pg in context.pages if pg.url.startswith("http")), None) or context.pages[0]
        else:
            page = context.new_page()
            try:  # bazı siteler (TikTok) "load" olayını çok geç tetikler; sayfa zaten açılıyor
                page.goto(url, wait_until="commit", timeout=60_000)
            except PlaywrightError:
                pass
        page.bring_to_front()

        def logged_in() -> bool:
            return any(c["name"] == cookie_name and _matches(c["domain"], [cookie_domain]) for c in context.cookies())

        def autofill() -> None:
            for pg in list(context.pages):
                if _matches(pg.url.split("://")[-1].split("/")[0], keep):
                    try:
                        pg.evaluate(FILL_JS, fill)
                    except PlaywrightError:
                        pass  # sayfa o sırada yönleniyor; 2 sn sonra tekrar denenir

        deadline = time.time() + args.timeout
        try:
            while not logged_in():
                if time.time() > deadline:
                    print("Süre doldu (15 dk): giriş yapılmadı. Tekrar \"Bağlan\"a basabilirsin.", file=sys.stderr)
                    return 1
                if fill:
                    autofill()
                time.sleep(2)
        except PlaywrightError:
            if not browser.is_connected():
                print("Video Stüdyosu Chrome penceresi kapatıldı. Giriş bitene kadar açık bırakıp "
                      "tekrar \"Bağlan\"a bas.", file=sys.stderr)
                return 1
            raise

        time.sleep(4)  # yönlendirmeler bitsin, kalan oturum çerezleri de yazılsın
        state = context.storage_state()
        state["cookies"] = [c for c in state["cookies"] if _matches(c["domain"], keep)]
        state["origins"] = [o for o in state["origins"] if _matches(o["origin"].split("://")[-1], keep)]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        try:
            page.close()  # pencere açık kalır; sadece bu sekme kapanır
        except Exception:
            pass
    print(f"Bağlandı: {args.platform} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
