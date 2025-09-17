#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/root/gipsr_bot"
VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
SERVICE_UNIT="gipsrbot-bot.service"
SERVICE_SRC="$APP_DIR/scripts/gipsrbot-bot.service"
SERVICE_DEST="/etc/systemd/system/${SERVICE_UNIT}"
ENV_FILE="$APP_DIR/.env"
service_installed=false

log() {
    printf '[%s] %s\n' "$(date -Iseconds)" "$*"
}

read_env_value() {
    local key="$1"
    local file="$2"
    python3 - "$key" "$file" <<'PY'
import sys
from pathlib import Path

key = sys.argv[1]
path = Path(sys.argv[2])
value = ""
if path.exists():
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        current_key, current_value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        current_value = current_value.strip()
        if (
            current_value
            and current_value[0] == current_value[-1]
            and current_value[0] in "'\""
        ):
            current_value = current_value[1:-1]
        value = current_value.strip()
        break
print(value)
PY
}

log "Starting auto-deploy sequence"

cd "$APP_DIR"

log "Ensuring runtime directories exist"
install -d -m 755 "$APP_DIR/clients" "$APP_DIR/data" "$APP_DIR/logs"

migrate_data_file() {
    local src="$1"
    local dest_dir="$2"
    if [[ -f "$APP_DIR/$src" && ! -e "$dest_dir/$src" ]]; then
        log "Migrating $src to $dest_dir"
        mv "$APP_DIR/$src" "$dest_dir/$src"
    fi
}

migrate_data_file "orders.json" "$APP_DIR/data"
migrate_data_file "prices.json" "$APP_DIR/data"
migrate_data_file "user_logs.json" "$APP_DIR/data"
migrate_data_file "orders.xlsx" "$APP_DIR/data"

if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating Python virtual environment"
    python3 -m venv "$VENV_DIR"
fi

log "Updating pip and project dependencies"
"$PYTHON_BIN" -m pip install --upgrade pip wheel
"$PIP_BIN" install --no-input --upgrade -r "$APP_DIR/requirements.txt"

if [[ -f "$SERVICE_SRC" ]]; then
    log "Installing systemd unit $SERVICE_UNIT"
    install -m 0644 "$SERVICE_SRC" "$SERVICE_DEST"
    systemctl daemon-reload
    systemctl reset-failed "$SERVICE_UNIT" || true
    service_installed=true
else
    log "Warning: systemd unit definition $SERVICE_SRC not found"
fi

if [[ ! -f "$ENV_FILE" ]]; then
    log "Environment file (.env) not found. Skipping bot restart until credentials are provided."
    exit 0
fi

bot_token="$(read_env_value TELEGRAM_BOT_TOKEN "$ENV_FILE" | tr -d '\r')"
if [[ -z "$bot_token" ]]; then
    log "TELEGRAM_BOT_TOKEN is missing or empty in $ENV_FILE. Skipping bot restart."
    exit 0
fi

if [[ "$service_installed" != true ]]; then
    log "Systemd unit $SERVICE_UNIT is unavailable. Deployment finished without restarting the bot."
    exit 0
fi

log "Enabling and restarting $SERVICE_UNIT"
systemctl enable "$SERVICE_UNIT"
systemctl restart "$SERVICE_UNIT"

log "Auto-deploy sequence completed"
