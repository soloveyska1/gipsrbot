#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[%s] %s\n' "$(date -Iseconds)" "$*"
}

trap 'log "Auto-deploy failed on line $LINENO"; exit 1' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_APP_DIR="${APP_DIR:-}"
APP_DIR="${GIPSRBOT_APP_DIR:-${ENV_APP_DIR:-$DEFAULT_APP_DIR}}"

log "Using application directory: $APP_DIR"

if [[ ! -d "$APP_DIR" ]]; then
    log "Application directory $APP_DIR does not exist. Aborting."
    exit 1
fi

log "Starting auto-deploy sequence"

VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
SERVICE_UNIT="gipsrbot-bot.service"
SERVICE_SRC="$APP_DIR/scripts/gipsrbot-bot.service"
SERVICE_DEST="/etc/systemd/system/${SERVICE_UNIT}"
ENV_FILE="$APP_DIR/.env"
service_installed=false
SYSTEMCTL_AVAILABLE=false
JOURNALCTL_AVAILABLE=false

if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    SYSTEMCTL_AVAILABLE=true
    if command -v journalctl >/dev/null 2>&1; then
        JOURNALCTL_AVAILABLE=true
    fi
else
    log "systemd is unavailable. Service management will be skipped."
fi

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

declare -a DATA_FILES=(
    "orders.json"
    "prices.json"
    "user_logs.json"
    "orders.xlsx"
    "users.json"
    "referrals.json"
    "feedbacks.json"
    "bonuses.json"
)

for data_file in "${DATA_FILES[@]}"; do
    migrate_data_file "$data_file" "$APP_DIR/data"
done

if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating Python virtual environment"
    python3 -m venv "$VENV_DIR"
fi

log "Updating pip and project dependencies"
"$PYTHON_BIN" -m pip install --upgrade pip wheel
"$PIP_BIN" install --no-input --upgrade -r "$APP_DIR/requirements.txt"

log "Validating bot source"
"$PYTHON_BIN" -m compileall "$APP_DIR/bot.py"

if [[ -f "$SERVICE_SRC" ]]; then
    log "Installing systemd unit $SERVICE_UNIT"
    install -m 0644 "$SERVICE_SRC" "$SERVICE_DEST"
    if [[ "$SYSTEMCTL_AVAILABLE" == true ]]; then
        systemctl daemon-reload
        systemctl reset-failed "$SERVICE_UNIT" || true
    fi
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

restart_service() {
    local unit="$1"
    if [[ "$SYSTEMCTL_AVAILABLE" != true ]]; then
        log "systemd is unavailable. Skipping restart for $unit."
        return 0
    fi

    log "Enabling $unit"
    if ! systemctl enable "$unit"; then
        log "Failed to enable $unit"
        systemctl status "$unit" --no-pager || true
        return 1
    fi

    log "Restarting $unit"
    if ! systemctl restart "$unit"; then
        log "Failed to restart $unit"
        systemctl status "$unit" --no-pager || true
        if [[ "$JOURNALCTL_AVAILABLE" == true ]]; then
            journalctl -u "$unit" -n 50 --no-pager || true
        fi
        return 1
    fi

    if systemctl --quiet is-active "$unit"; then
        log "$unit is active"
        return 0
    fi

    log "$unit is not running after restart"
    systemctl status "$unit" --no-pager || true
    if [[ "$JOURNALCTL_AVAILABLE" == true ]]; then
        journalctl -u "$unit" -n 50 --no-pager || true
    fi
    return 1
}

if [[ "$service_installed" != true ]]; then
    log "Systemd unit $SERVICE_UNIT is unavailable. Deployment finished without restarting the bot."
    exit 0
fi

restart_service "$SERVICE_UNIT"

log "Auto-deploy sequence completed"
