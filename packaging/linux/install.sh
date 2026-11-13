#!/usr/bin/env bash
# Video Stüdyosu Linux kurulumu. .run paketi veya .deb'in ilk açılışı bunu çalıştırır.
#   --from-deb      Sistem paketlerini ve kısayolları .deb halletti; sadece Python ortamını kur
#   --no-start      Kurulum bitince paneli açma
#   --yes           Soru sorma (sistem paketleri ve Chrome için evet say)
set -euo pipefail

APP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
START=1 YES=0 FROM_DEB=0
for arg in "$@"; do
  case "$arg" in
    --no-start) START=0 ;;
    --from-deb) FROM_DEB=1 ;;
    --yes) YES=1 ;;
    *) echo "Bilinmeyen seçenek: $arg" >&2; exit 2 ;;
  esac
done

confirm() {  # confirm "soru": --yes ile evet; terminal yoksa hayır
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  read -r -p "$1 [e/H] " reply
  case "$reply" in e|E|y|Y|evet|Evet) return 0 ;; *) return 1 ;; esac
}

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

find_chrome() { command -v google-chrome-stable || command -v google-chrome || command -v chromium || command -v chromium-browser || true; }

if [ "$FROM_DEB" = 0 ]; then
echo "==> Sistem gereksinimleri kontrol ediliyor"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10 veya üstü gerekli." >&2; exit 1; }

missing=()
python3 -c 'import ensurepip, venv' 2>/dev/null || missing+=(python3-venv)
command -v curl >/dev/null || missing+=(curl)
[ -f /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf ] || [ -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ] || missing+=(fonts-liberation)
if [ "${#missing[@]}" -gt 0 ]; then
  command -v apt-get >/dev/null || { echo "Şu paketleri kurup tekrar çalıştır: ${missing[*]}" >&2; exit 1; }
  echo "Gerekli sistem paketleri: ${missing[*]}"
  confirm "Kurulsun mu? (sudo şifresi istenebilir)" || { echo "Kurulum durduruldu." >&2; exit 1; }
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq "${missing[@]}"
fi

if [ -z "$(find_chrome)" ]; then
  echo "Google Chrome bulunamadı (hesap bağlama ve yükleme için gerekli)."
  if command -v apt-get >/dev/null && [ "$(uname -m)" = x86_64 ] && confirm "Google Chrome indirilip kurulsun mu?"; then
    deb="$(mktemp --suffix=.deb)"
    curl -fsSL -o "$deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    chmod 644 "$deb"
    $SUDO apt-get install -y -qq "$deb"
    rm -f "$deb"
  else
    echo "UYARI: Chrome'u sonra kendin kur; kurulmadan hesap bağlanamaz ve video yüklenemez."
  fi
fi

fi

echo "==> Python ortamı hazırlanıyor"
cd "$APP_HOME"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check --upgrade pip
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt playwright
[ -f .env ] || cp .env.example .env
chmod 600 .env
mkdir -p data
chmod 700 data

[ "$FROM_DEB" = 1 ] && exit 0

echo "==> Kısayollar oluşturuluyor"
chmod +x packaging/linux/video-studyosu
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
cat > "$HOME/.local/bin/video-studyosu" <<EOF
#!/usr/bin/env bash
export VIDEO_STUDYOSU_HOME="$APP_HOME"
exec "$APP_HOME/packaging/linux/video-studyosu" "\$@"
EOF
chmod +x "$HOME/.local/bin/video-studyosu"
desktop_file="$HOME/.local/share/applications/video-studyosu.desktop"
cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=Video Stüdyosu
Comment=Cuma Robot ile kısa video üret ve yayınla
Exec=$HOME/.local/bin/video-studyosu
Icon=$APP_HOME/assets/narrator/cuma_face.png
Terminal=false
Categories=AudioVideo;
EOF
chmod +x "$desktop_file"
desktop_dir="$(command -v xdg-user-dir >/dev/null && xdg-user-dir DESKTOP || echo "$HOME/Desktop")"
if [ -d "$desktop_dir" ]; then
  cp "$desktop_file" "$desktop_dir/"
  command -v gio >/dev/null && gio set "$desktop_dir/video-studyosu.desktop" metadata::trusted true 2>/dev/null || true
fi

echo
echo "Kurulum tamam: $APP_HOME"
if ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ] && ! grep -q '^ANTHROPIC_API_KEY=.' .env; then
  echo "SON BİR ADIM: Senaryoları Claude yazıyor. Şunlardan birini yap:"
  echo "  - Claude Code kur ve bir kez 'claude' yazıp giriş yap"
  echo "  - veya $APP_HOME/.env dosyasına ANTHROPIC_API_KEY=... ekle"
fi
echo "Ücretsiz yerel üretim için ek ayar gerekmez; Gemini isteğe bağlıdır (panelde 3. adım)."
echo "Açmak için uygulama menüsünden 'Video Stüdyosu'nu seç ya da: video-studyosu"
[ "$START" = 1 ] && exec "$HOME/.local/bin/video-studyosu"
exit 0
