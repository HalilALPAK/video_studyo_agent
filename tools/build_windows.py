"""Windows paketini üretir: dist/VideoStudyosu.exe

PyInstaller ve Pillow kurulu bir ortamda, Windows'ta çalıştırılır:

    python tools/build_windows.py
"""
import datetime as dt
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from build_linux import DIST, ROOT, app_archive  # noqa: E402


def main() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv bulunamadı (pip install uv)")
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "app.tar.gz").write_bytes(app_archive())
        (work / "VERSION").write_text(dt.datetime.now().strftime("%Y%m%d%H%M"), encoding="utf-8")
        Image.open(ROOT / "assets/narrator/cuma_face.png").save(work / "icon.ico", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console", "--name", "VideoStudyosu",
            "--icon", str(work / "icon.ico"), "--distpath", str(DIST), "--workpath", str(work / "build"),
            "--specpath", str(work), "--add-data", f"{work / 'app.tar.gz'};.", "--add-data", f"{work / 'VERSION'};.",
            "--add-binary", f"{uv};.", str(ROOT / "packaging/windows/launcher.py"),
        ], check=True)
    out = DIST / "VideoStudyosu.exe"
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
