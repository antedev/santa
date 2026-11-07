#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt
fi

export SECRET_SANTA_ADMIN_PASSWORD="${SECRET_SANTA_ADMIN_PASSWORD:-tomten}"
export SECRET_SANTA_DEV_MODE="${SECRET_SANTA_DEV_MODE:-0}"

echo "Startar Julklappsspelet på http://0.0.0.0:8000 ..."
exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
