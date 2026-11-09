"""Video yükleme yardımcısı: kullanıcının giriş yaptığı "Video Stüdyosu" Chrome'unda (CDP ile)
platformun kendi yükleme sayfasını kullanır. Ayrı/gizli tarayıcıya çerez kopyalamadığı için
Google'ın "desteklenmeyen tarayıcı" engeline ve oturum uyuşmazlıklarına takılmaz.
social-auto-upload'ın ortamında çalışır (playwright orada kurulu).

    python tools/studio_upload.py --platform tiktok --file video.mp4 --title ... --desc ... \
        --tags a,b --profile data/chrome-profile --port 9333 --chrome "C:/.../chrome.exe" [--dry-run]

--dry-run son "Paylaş/Yayınla" tıklamasına kadar her şeyi yapar, yayınlamaz.
Başarılıysa son satıra "URL: <bağlantı>" yazar; hata olursa ekran görüntüsünü --debug-dir'e kaydeder.
"""
import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from connect_account import ensure_chrome  # noqa: E402

# Arayüz Türkçe veya İngilizce olabilir
NOT_NOW = re.compile(r"^(şimdi değil|not now)$", re.I)
OK = re.compile(r"^(tamam|ok)$", re.I)
NEXT = re.compile(r"^(İleri|ileri|next)$", re.I)  # "İ" büyük/küçük harf duyarsız eşleşmede "i" ile eşleşmiyor
SHARE = re.compile(r"^(paylaş|share)$", re.I)
GOT_IT = re.compile(r"^(anladım|got it)$", re.I)


def caption(title: str, desc: str, tags: list[str], with_title: bool = True) -> str:
    parts = [title if with_title else "", desc, " ".join(f"#{t}" for t in tags)]
    return "\n\n".join(p for p in parts if p)


def replace_text(page: Page, box, text: str) -> None:
    """contenteditable kutunun içeriğini (dosya adıyla dolu gelir) metinle değiştirir."""
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    for i, line in enumerate(text.split("\n")):
        if i:
            page.keyboard.press("Shift+Enter")
        if line:
            page.keyboard.insert_text(line)


def pick_file(page: Page, trigger, path: str) -> None:
    """Sitenin kendi "Dosya seç" düğmesine basıp açılan pencereye dosyayı verir. Bazı siteler
    (TikTok) gizli input'a doğrudan verilen dosyayı yok sayıyor; gerçek tıklama ikisinde de çalışır."""
    trigger.wait_for(timeout=90_000)
    with page.expect_file_chooser(timeout=30_000) as chooser:
        trigger.click()
    chooser.value.set_files(path)


def dismiss(page: Page, name: re.Pattern) -> None:
    btn = page.get_by_role("button", name=name)
    if btn.count():
        try:
            btn.first.click(timeout=3000)
        except PlaywrightError:
            pass


# --- YouTube ---------------------------------------------------------------------------

def youtube(page: Page, a) -> str:
    page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded", timeout=90_000)
    page.locator("input[type=file][name=Filedata]").set_input_files(a.file, timeout=60_000)
    title = page.locator("#title-textarea #textbox")
    title.wait_for(timeout=120_000)
    replace_text(page, title, a.title[:100])
    replace_text(page, page.locator("#description-textarea #textbox"), caption("", a.desc, a.tags, with_title=False)[:4900])
    kids = "VIDEO_MADE_FOR_KIDS_MFK" if a.kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
    page.locator(f'tp-yt-paper-radio-button[name="{kids}"]').click()
    for _ in range(3):  # Ayrıntılar -> Video öğeleri -> Kontroller -> Görünürlük
        page.locator("#next-button").click()
        page.wait_for_timeout(1500)
    page.locator(f'tp-yt-paper-radio-button[name="{a.visibility.upper()}"]').click()
    link = page.locator("ytcp-video-info a[href*='youtu']").first
    url = link.get_attribute("href", timeout=60_000) or ""
    if a.dry_run:
        return url
    page.locator("#done-button").click()
    # Sonra gelen pencere duruma göre değişiyor ("Video yayınlandı" / "Video işleniyor"); ona bakmadan
    # yükleme yüzdesi bitene kadar bekle, yoksa sekme kapanınca yükleme yarıda kalır
    page.wait_for_timeout(5000)
    wait_youtube_upload(page, a.timeout)
    return url


def wait_youtube_upload(page: Page, timeout: int) -> None:
    """Studio'nun yükleme listesindeki ilerleme kaybolana (%100 olana) kadar bekler."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = page.evaluate("""() => [...document.querySelectorAll('ytcp-video-upload-progress, ytcp-multi-progress-monitor')]
            .some(e => /\\d+\\s*%/.test(e.innerText || '') && !/100\\s*%/.test(e.innerText || ''))""")
        if not pending:
            return
        page.wait_for_timeout(3000)
    raise TimeoutError("YouTube yüklemesi süre içinde bitmedi")


# --- TikTok ----------------------------------------------------------------------------

def tiktok_popups(page: Page) -> None:
    """Önce modal ("Otomatik içerik kontrolleri açılsın mı?" -> Aç; telif/içerik kontrolü
    açık kalsın), sonra arkasında kalan bilgi balonu ("Anladım")."""
    if page.get_by_text(re.compile(r"içerik kontrolleri açılsın|turn on automatic content", re.I)).count():
        dismiss(page, re.compile(r"^(aç|turn on)$", re.I))
        page.wait_for_timeout(1000)
    dismiss(page, GOT_IT)


def tiktok(page: Page, a) -> str:
    page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded", timeout=90_000)
    pick_file(page, page.locator('button[data-e2e="select_video_button"]'), a.file)
    editor = page.locator("[contenteditable=true]").first
    editor.wait_for(timeout=120_000)
    page.wait_for_timeout(3000)
    tiktok_popups(page)
    replace_text(page, editor, caption(a.title, a.desc, [])[:2000])
    for tag in a.tags[:8]:  # etiketler öneri listesi açtığı için tek tek yazılıp kapatılır
        page.keyboard.insert_text(f" #{tag}")
        page.wait_for_timeout(800)
        page.keyboard.press("Escape")
    post = page.locator('button[data-e2e="post_video_button"]')
    deadline = time.time() + a.timeout
    while post.get_attribute("aria-disabled", timeout=60_000) == "true" or post.is_disabled():
        if time.time() > deadline:
            raise TimeoutError("TikTok yüklemesi süre içinde bitmedi")
        page.wait_for_timeout(2000)
    tiktok_popups(page)
    if a.dry_run:
        return ""
    post.click()
    # İçerik kontrolü bitmeden paylaşılırsa "Paylaşmaya devam edilsin mi?" penceresi çıkıyor (ne zaman
    # çıkacağı belli değil); içerik sayfasına geçene kadar bu onayı vermeye devam et
    confirm = re.compile(r"^(hemen paylaş|şimdi paylaş|yine de paylaş|post now|post anyway)$", re.I)
    deadline = time.time() + 300
    while not re.search(r"tiktokstudio/content|/manage", page.url):
        if time.time() > deadline:
            raise TimeoutError("TikTok paylaşımı onaylanmadı (içerik sayfasına geçilmedi)")
        dismiss(page, confirm)
        page.wait_for_timeout(2000)
    return ""


# --- Instagram -------------------------------------------------------------------------

def instagram(page: Page, a) -> str:
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=90_000)
    create = page.locator("svg[aria-label='Yeni Gönderi' i], svg[aria-label='New post' i]").first
    create.wait_for(timeout=90_000)
    page.wait_for_timeout(2000)
    dismiss(page, NOT_NOW)  # "Bildirimleri aç" penceresi
    create.click()
    # Bazı hesaplarda önce "Gönderi / Canlı" alt menüsü açılır
    sub = page.get_by_role("link", name=re.compile(r"^(gönderi|post)$", re.I))
    if sub.count():
        sub.first.click()
    dialog = page.get_by_role("dialog").filter(has=page.locator("input[type=file]"))
    dialog.locator("input[type=file]").set_input_files(a.file, timeout=60_000)
    page.wait_for_timeout(2000)
    dismiss(page, OK)  # "Video gönderileri artık reels olarak paylaşılıyor"
    dialog = page.get_by_role("dialog").last
    # Varsayılan kare kırpma altyazıyı ve görselin üstünü keser; dikey videoyu olduğu gibi kullan
    dialog.locator("svg[aria-label='Kırpmayı seç' i], svg[aria-label='Select crop' i]").first.click(timeout=120_000)
    dialog.get_by_text(re.compile(r"^(orijinal|original)$", re.I)).first.click()
    page.wait_for_timeout(1000)
    for _ in range(2):  # Kırp -> Düzenle -> Açıklama ("İleri" düğme değil, düz yazı)
        dialog.get_by_text(NEXT).first.click(timeout=120_000)
        page.wait_for_timeout(2500)
    box = dialog.locator("[contenteditable=true][role=textbox]").first
    replace_text(page, box, caption(a.title, a.desc, a.tags)[:2200])
    share = dialog.get_by_text(SHARE).first
    share.wait_for(timeout=30_000)
    if a.dry_run:
        return ""
    share.click()
    done = page.get_by_text(re.compile(r"(paylaşıldı|has been shared|reel.*shared)", re.I)).first
    done.wait_for(timeout=a.timeout * 1000)
    return ""


UPLOADERS = {"youtube": youtube, "tiktok": tiktok, "instagram": instagram}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=list(UPLOADERS))
    parser.add_argument("--file", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--desc", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--visibility", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--kids", action="store_true", help="YouTube: çocuklara özel içerik")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    a = parser.parse_args()
    a.tags = [t.strip().lstrip("#") for t in a.tags.split(",") if t.strip()]
    a.file = str(Path(a.file).resolve())

    ensure_chrome(a.chrome, a.profile, a.port, "about:blank")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{a.port}")
        page = browser.contexts[0].new_page()
        page.bring_to_front()  # arka plandaki sekmeleri Chrome yavaşlatıyor
        page.set_default_timeout(60_000)
        try:
            url = UPLOADERS[a.platform](page, a)
        except Exception as e:
            if a.debug_dir:
                a.debug_dir.mkdir(parents=True, exist_ok=True)
                shot = a.debug_dir / f"{a.platform}.png"
                try:
                    page.screenshot(path=str(shot))
                    print(f"Ekran görüntüsü: {shot}", file=sys.stderr)
                except PlaywrightError:
                    pass
            print(f"{a.platform} yüklemesi başarısız ({page.url}): {str(e).splitlines()[0]}", file=sys.stderr)
            return 1
        finally:
            if not a.dry_run:
                try:
                    page.close()
                except PlaywrightError:
                    pass
    print("DRY-RUN OK" if a.dry_run else "Yüklendi")
    print(f"URL: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
