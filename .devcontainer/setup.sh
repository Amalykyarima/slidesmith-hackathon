#!/usr/bin/env bash
# Runs once when the Codespace is created.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== LibreOffice + Office-compatible fonts (slide thumbnails) =="
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends \
  libreoffice-impress fonts-crosextra-carlito fonts-crosextra-caladea

echo "== Preview fonts =="
# Teachers' decks often use Gill Sans (a macOS/Office font Linux doesn't have). Preview it
# with Carlito, which has similar widths, so preview line breaks match PowerPoint.
mkdir -p ~/.config/fontconfig
cat > ~/.config/fontconfig/fonts.conf <<'XML'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <alias binding="same"><family>Gill Sans</family><prefer><family>Carlito</family></prefer></alias>
  <alias binding="same"><family>Gill Sans MT</family><prefer><family>Carlito</family></prefer></alias>
</fontconfig>
XML
fc-cache -f >/dev/null 2>&1 || true

echo "== Backend =="
cd "$ROOT/backend"
python -m venv .venv
.venv/bin/pip install -q -r requirements.txt pytest
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python tests/make_fixtures.py

echo "== Live avatar worker =="
cd "$ROOT/avatar"
python -m venv .venv
.venv/bin/pip install -q -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi

echo "== Frontend =="
cd "$ROOT/frontend"
npm ci --no-audit --no-fund

echo "== Claude Code =="
curl -fsSL https://claude.ai/install.sh | bash
grep -q '.local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

echo "Done. Open a new terminal and run: claude"
