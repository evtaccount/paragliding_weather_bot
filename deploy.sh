#!/usr/bin/env bash
# Bootstrap the bot on a Linux server (venv + systemd path).
# For the Docker path use `docker compose up -d --build` instead.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "==> Python venv + dependencies"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "==> checking fonts (needed for Cyrillic chart labels)"
if ! fc-list 2>/dev/null | grep -qi dejavu; then
  echo "!! DejaVu fonts not found. Install them, or chart text will be broken:"
  echo "   sudo apt-get install -y fonts-dejavu-core     # Debian/Ubuntu"
fi

echo "==> checking the mini app build (needed for the Web App button)"
if [ ! -f webapp/dist/index.html ]; then
  echo "!! webapp is not built. The bot chat works, /api/health answers 200, but"
  echo "   the Web App button returns 500 on every open (api.py serves webapp/dist,"
  echo "   which is a build artefact and is not in git). Build it:"
  echo "   make webapp-install && make webapp-build     # needs Node 22+"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> created .env — set BOT_TOKEN in it before starting"
fi

echo "==> rendering systemd unit for this path/user"
sed -e "s|__DIR__|$DIR|g" \
    -e "s|__USER__|$(whoami)|g" \
    -e "s|__PY__|$DIR/.venv/bin/python|g" \
    deploy/pgbot.service.tmpl > deploy/pgbot.service

cat <<EOF

Done. Next steps:
  1. Edit .env and set BOT_TOKEN (from @BotFather)
  2. sudo cp deploy/pgbot.service /etc/systemd/system/pgbot.service
  3. sudo systemctl daemon-reload && sudo systemctl enable --now pgbot
  4. journalctl -u pgbot -f       # follow logs
EOF
