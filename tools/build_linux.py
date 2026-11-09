"""Linux kurulum paketlerini üretir (dist/ altında):

  video-studyosu.deb         Ubuntu/Debian: çift tıkla kur, menüdeki simgeyle aç
  video-studyosu-linux.run   Diğer dağıtımlar: terminalden çalıştırılır

Paketler sadece izin listesindeki kod ve görselleri içerir; .env, data/ (veritabanı, API anahtarı,
Chrome profili), oturum çerezleri ve yapay zekâ modelleri kesinlikle girmez.

    python tools/build_linux.py
"""
import datetime as dt
import io
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
INCLUDE = ["agent", "assets/narrator", "packaging/linux", "tools/studio_upload.py", "tools/connect_account.py",
           "requirements.txt", ".env.example", "README.md", "cuma.jpeg"]
FORBIDDEN = (".env", "agent.db", "cookies", "chrome-profile", ".pt", ".safetensors")
EXECUTABLE = ("install.sh", "video-studyosu", "deb-launcher")
TEXT_LF = (".sh", ".env.example", "video-studyosu", "deb-launcher")

STUB = """#!/bin/sh
# Video Stüdyosu kurulum paketi. Kendini açar ve kurulumu başlatır; verilerine ve .env dosyana dokunmaz.
set -e
DEST="${VIDEO_STUDYOSU_HOME:-$HOME/.local/share/video-studyosu}"
mkdir -p "$DEST"
LINE=$(awk '/^__ARCHIVE_BELOW__$/ {print NR + 1; exit}' "$0")
tail -n +"$LINE" "$0" | tar xz -C "$DEST"
exec bash "$DEST/packaging/linux/install.sh" "$@"
__ARCHIVE_BELOW__
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Video Stüdyosu
Comment=Cuma Robot ile kısa video üret ve yayınla
Exec=/usr/bin/video-studyosu
Icon=video-studyosu
Terminal=false
Categories=AudioVideo;Video;
"""

CONTROL = """Package: video-studyosu
Version: {version}
Section: video
Priority: optional
Architecture: all
Maintainer: Video Studyosu <noreply@localhost>
Depends: python3 (>= 3.10), python3-venv, curl, tar, fonts-liberation, xdg-utils, zenity
Recommends: google-chrome-stable | chromium-browser | chromium
Installed-Size: {size}
Description: Cuma Robot ile kisa video uretim ve yayin paneli
 Konulardan Gemini API ile kisa dikey videolar uretir ve YouTube, TikTok ve
 Instagram hesaplarina yukler.
"""


def files() -> list[Path]:
    found = []
    for item in INCLUDE:
        path = ROOT / item
        found += [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    return [p for p in found if "__pycache__" not in p.parts]


def forbidden(name: str) -> bool:
    return name != ".env.example" and any(bad in name.split("/") or name.endswith(bad) for bad in FORBIDDEN)


def add_file(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    tar.addfile(info, io.BytesIO(data))


def add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
    tar.addfile(info)


def app_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in files():
            name = path.relative_to(ROOT).as_posix()
            if forbidden(name):
                raise SystemExit(f"Pakete girmemeli: {name}")
            data = path.read_bytes()
            if name.endswith(TEXT_LF):
                data = data.replace(b"\r\n", b"\n")
            add_file(tar, name, data, 0o755 if path.name in EXECUTABLE else 0o644)
    return buf.getvalue()


def ar_member(name: str, data: bytes) -> bytes:
    header = f"{name + '/':<16}{int(time.time()):<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode("ascii")
    return header + data + (b"\n" if len(data) % 2 else b"")


def tar_gz(fill) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        fill(tar)
    return buf.getvalue()


def build_deb(archive: bytes) -> Path:
    version = "1.0." + dt.datetime.now().strftime("%Y%m%d%H%M")
    launcher = (ROOT / "packaging/linux/deb-launcher").read_bytes().replace(b"\r\n", b"\n")
    icon = (ROOT / "assets/narrator/cuma_face.png").read_bytes()
    desktop = DESKTOP.encode("utf-8")

    def data(tar):
        for d in ("./opt", "./opt/video-studyosu", "./usr", "./usr/bin", "./usr/share",
                  "./usr/share/applications", "./usr/share/pixmaps"):
            add_dir(tar, d)
        add_file(tar, "./opt/video-studyosu/app.tar.gz", archive)
        add_file(tar, "./opt/video-studyosu/VERSION", f"{version}\n".encode())
        add_file(tar, "./usr/bin/video-studyosu", launcher, 0o755)
        add_file(tar, "./usr/share/applications/video-studyosu.desktop", desktop)
        add_file(tar, "./usr/share/pixmaps/video-studyosu.png", icon)

    size = (len(archive) + len(launcher) + len(icon) + len(desktop)) // 1024 + 1
    control = CONTROL.format(version=version, size=size).encode("utf-8")
    out = DIST / "video-studyosu.deb"
    out.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n")
                    + ar_member("control.tar.gz", tar_gz(lambda t: add_file(t, "./control", control)))
                    + ar_member("data.tar.gz", tar_gz(data)))
    return out


def main() -> None:
    DIST.mkdir(exist_ok=True)
    archive = app_archive()
    run = DIST / "video-studyosu-linux.run"
    run.write_bytes(STUB.encode("utf-8") + archive)
    for path in (build_deb(archive), run):
        print(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
