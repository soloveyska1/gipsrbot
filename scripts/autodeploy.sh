#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "[gipsr_bot] Скрипт autodeploy нужно запускать от имени root." >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/autodeploy.log"
ENV_FILE="$APP_DIR/.env"

mkdir -p "$LOG_DIR"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log() {
  local message="$1"
  printf '[%s] %s\n' "$(timestamp)" "$message" | tee -a "$LOG_FILE"
}

log "Запуск автоматической установки GIPSR Bot..."

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  log "Обновляем список пакетов..."
  apt-get update -y >>"$LOG_FILE" 2>&1
  log "Устанавливаем python3-venv, python3-pip и systemd-tools..."
  apt-get install -y python3 python3-venv python3-pip systemd >>"$LOG_FILE" 2>&1
else
  log "apt-get не найден. Предполагаем, что зависимости уже установлены."
fi

if [[ ! -f "$ENV_FILE" ]]; then
  log "Файл .env не найден. Загрузите его вместе с проектом и повторите установку."
  exit 1
fi

if grep -Eq 'PASTE_TELEGRAM_BOT_TOKEN_HERE|REPLACE_ME|0000000000' "$ENV_FILE"; then
  log "В .env все еще стоит шаблон TELEGRAM_BOT_TOKEN. Замените его на реальный токен бота."
  exit 1
fi

log "Создаем виртуальное окружение и ставим зависимости..."
bash "$APP_DIR/scripts/install.sh" >>"$LOG_FILE" 2>&1

SERVICE_PATH="/etc/systemd/system/gipsrbot.service"
log "Создаем systemd unit $SERVICE_PATH"
cat <<SYSTEMD >"$SERVICE_PATH"
[Unit]
Description=GIPSR Telegram bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SYSTEMD

log "Перезапускаем systemd и включаем службу..."
systemctl daemon-reload
systemctl enable gipsrbot.service >>"$LOG_FILE" 2>&1
systemctl restart gipsrbot.service

log "Текущий статус службы:"
systemctl status gipsrbot.service --no-pager >>"$LOG_FILE" 2>&1 || true
systemctl status gipsrbot.service --no-pager || true

log "Последние строки журнала сервиса:"
journalctl -u gipsrbot.service -n 20 --no-pager || true

log "Готово! Бот запущен и будет стартовать автоматически при перезагрузке."
