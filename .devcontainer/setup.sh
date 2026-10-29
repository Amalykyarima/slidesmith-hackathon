#!/usr/bin/env bash
# Runs once when the Codespace is created.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== LibreOffice + Office-compatible fonts (slide thumbnails) =="
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends \
  libreoffice-impress fonts-crosextra-carlito fonts-crosextra-caladea

echo "== Backend =="
cd "$ROOT/backend"
python -m venv .venv
.venv/bin/pip install -q -r requirements.txt pytest
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python tests/make_fixtures.py

echo "== Frontend =="
cd "$ROOT/frontend"
npm ci --no-audit --no-fund

echo "== Claude Code =="
curl -fsSL https://claude.ai/install.sh | bash
grep -q '.local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

echo "Done. Open a new terminal and run: claude"
