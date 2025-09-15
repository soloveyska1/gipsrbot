#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="$APP_DIR/logs"

mkdir -p "$LOG_DIR"
source "$VENV_DIR/bin/activate"
exec python "$APP_DIR/bot.py"

