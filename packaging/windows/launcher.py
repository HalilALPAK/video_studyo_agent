"""VideoStudyosu.exe: çift tıklanınca uygulamayı kullanıcının klasörüne hazırlar ve paneli açar.

Python gerektirmez: exe'nin içindeki uv, Python'u ve bağımlılıkları ilk açılışta indirir.
Uygulama ve veriler %LOCALAPPDATA%\\VideoStudyosu altında kalır; güncellemede veriler korunur.
"""
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import webbrowser
from pathlib import Path

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
APP = Path(os.environ.get("VIDEO_STUDYOSU_HOME") or Path(os.environ["LOCALAPPDATA"]) / "VideoStudyosu")
STAMP = APP / ".kurulu-surum"
PYTHON = APP / ".venv" / "Scripts" / "python.exe"
# PyInstaller'ın ortam değişkenleri alt süreçlere geçmesin
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "PYINSTALLER", "_MEIPASS"))}


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, env={**ENV, "UV_PYTHON_INSTALL_DIR": str(APP / "python")})


def setup(version: str) -> None:
    print("Video Stüdyosu ilk kez hazırlanıyor. İnternet hızına göre birkaç dakika sürebilir...\n")
    APP.mkdir(parents=True, exist_ok=True)
    with tarfile.open(BUNDLE / "app.tar.gz") as tar:
        tar.extractall(APP, filter="data")
    uv = str(BUNDLE / "uv.exe")
    if not PYTHON.exists():
        run(uv, "venv", "--python", "3.12", str(APP / ".venv"))
    run(uv, "pip", "install", "--python", str(PYTHON), "-r", str(APP / "requirements.txt"), "playwright")
    if not (APP / ".env").exists():
        shutil.copy2(APP / ".env.example", APP / ".env")
    STAMP.write_text(version, encoding="utf-8")


def missing_tools() -> list[str]:
    code = ("from agent import config, llm; from pathlib import Path; import os\n"
            "print('chrome' if not Path(config.CHROME_PATH).exists() else '')\n"
            "print('claude' if not (llm.find_claude_code() or os.getenv('ANTHROPIC_API_KEY')) else '')")
    out = subprocess.run([str(PYTHON), "-c", code], cwd=APP, env=ENV, capture_output=True, text=True).stdout
    messages = {"chrome": "Google Chrome'u kur (hesap bağlama ve yükleme için gerekli).",
                "claude": f"Claude Code kurup giriş yap ya da {APP / '.env'} dosyasına ANTHROPIC_API_KEY ekle (senaryolar için gerekli)."}
    return [messages[word] for word in out.split() if word in messages]


def port() -> int:
    if os.environ.get("PANEL_PORT"):
        return int(os.environ["PANEL_PORT"])
    for line in (APP / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("PANEL_PORT=") and line[11:].split("#")[0].strip().isdigit():
            return int(line[11:].split("#")[0])
    return 5050


def listening(number: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", number)) == 0


def pause() -> None:
    try:
        input("\nKapatmak için Enter'a bas...")
    except EOFError:
        pass


def main() -> int:
    version = (BUNDLE / "VERSION").read_text(encoding="utf-8").strip()
    first_run = not STAMP.exists() or STAMP.read_text(encoding="utf-8").strip() != version or not PYTHON.exists()
    try:
        if first_run:
            setup(version)
    except (OSError, subprocess.CalledProcessError, tarfile.TarError) as e:
        print(f"\nHazırlık tamamlanamadı: {e}\nİnternet bağlantını kontrol edip tekrar aç.")
        pause()
        return 1

    number = port()
    if not listening(number):
        (APP / "data").mkdir(exist_ok=True)
        log = open(APP / "data" / "panel.log", "ab")
        subprocess.Popen([str(PYTHON), "-m", "agent", "panel"], cwd=APP, env=ENV, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        for _ in range(80):
            if listening(number):
                break
            time.sleep(0.5)
        else:
            print(f"Panel açılamadı. Ayrıntı: {APP / 'data' / 'panel.log'}")
            pause()
            return 1

    url = f"http://127.0.0.1:{number}"
    print(f"Panel açık: {url}")
    if not os.environ.get("VIDEO_STUDYOSU_NO_BROWSER"):
        webbrowser.open(url)
    if first_run and (todo := missing_tools()):
        print("\nBaşlamadan önce:\n" + "\n".join(f"  - {item}" for item in todo))
        pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
