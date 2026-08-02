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

# Границы ниже — маркеры для tests/test_deploy_config.py: блок ВЫРЕЗАЕТСЯ и
# ИСПОЛНЯЕТСЯ в песочнице, поэтому права на файле проверяются по факту, а не
# по тексту скрипта.
# >>> env file
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> created .env — set BOT_TOKEN and ALLOWED_USER_IDS in it before starting"
fi
# 0600, как в `make secrets`. Обычная umask даёт 0644, а в .env лежат BOT_TOKEN
# и GEMINI_API_KEY: любому другому локальному пользователю на сервере хватает
# ЧТЕНИЯ токена, чтобы выпустить себе initData на ЛЮБОЙ Telegram id — подпись
# считается тем же токеном локально (webauth._secret_key), а api.current_user
# сверяет только число. Список допуска после этого не значит ничего.
# chmod стоит СНАРУЖИ проверки на существование: файл мог остаться с прежней
# раскатки, когда этой строки ещё не было.
chmod 600 .env
# <<< env file

echo "==> rendering systemd unit for this path/user"
sed -e "s|__DIR__|$DIR|g" \
    -e "s|__USER__|$(whoami)|g" \
    -e "s|__PY__|$DIR/.venv/bin/python|g" \
    deploy/pgbot.service.tmpl > deploy/pgbot.service

cat <<EOF

Done. Next steps:
  1. Edit .env: BOT_TOKEN (from @BotFather) and ALLOWED_USER_IDS (your Telegram
     id, comma-separated for more pilots). The mini app refuses every request
     while that list is empty — the chat keeps working either way.
  2. sudo cp deploy/pgbot.service /etc/systemd/system/pgbot.service
  3. sudo systemctl daemon-reload && sudo systemctl enable --now pgbot
  4. journalctl -u pgbot -f       # follow logs
EOF

# Предупреждение печатается ПОСЛЕ «Next steps» намеренно: всё, сказанное
# раньше, уезжает за край экрана на выводе pip install — там же теряется и
# проверка шрифтов выше. Отказ, о котором речь, оператору иначе не виден
# вовсе: чат и /api/health работают, 500 достаётся одному пилоту, нажавшему
# кнопку Web App.
#
# Границы ниже — не украшение: по ним tests/test_deploy_config.py вырезает
# блок и ИСПОЛНЯЕТ его в двух состояниях каталога (со сборкой и без). Блок
# самодостаточен, от остального скрипта ему ничего не нужно; форма записи
# внутри границ любая, тест смотрит только на вывод.
# >>> webapp-build check
if [ ! -f webapp/dist/index.html ]; then
  echo ""
  echo "!! The mini app is NOT built: the Web App button will answer 500 on every"
  echo "   open (api.py serves webapp/dist, a build artefact that is not in git)."
  echo "   The chat and /api/health keep working regardless. Build it:"
  echo "     make webapp-install && make webapp-build     # needs Node 22+"
fi
# <<< webapp-build check
