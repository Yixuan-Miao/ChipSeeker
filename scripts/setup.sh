#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[setup] project root: $PROJECT_ROOT"

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium

if [ ! -f "config.local.json" ]; then
  cp config.example.json config.local.json
  echo "[setup] created config.local.json from template"
fi

mkdir -p \
  local_data \
  local_data/sources \
  local_data/sources/manual \
  local_data/sources/generated_exports \
  local_data/cache \
  local_data/exports \
  local_data/downloads \
  local_data/backups

echo "[setup] done"
echo "[setup] next: streamlit run app.py"
