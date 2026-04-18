#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[setup] project root: $PROJECT_ROOT"

if [[ ! -x ".venv/bin/python" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="python"
  else
    echo "[setup] Python 3.10+ was not found. Install Python first, then rerun setup.sh." >&2
    exit 1
  fi
  echo "[setup] creating virtual environment at .venv"
  "$BOOTSTRAP_PYTHON" -m venv .venv
else
  echo "[setup] reusing existing virtual environment"
fi

VENV_PYTHON=".venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[setup] virtual environment creation failed." >&2
  exit 1
fi

echo "[setup] upgrading pip / setuptools / wheel"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

echo "[setup] installing runtime requirements"
"$VENV_PYTHON" -m pip install -r requirements.txt

if [[ -f "requirements-optional.txt" ]]; then
  echo "[setup] installing optional quality-of-life requirements"
  "$VENV_PYTHON" -m pip install -r requirements-optional.txt
fi

echo "[setup] installing Playwright Chromium runtime"
"$VENV_PYTHON" -m playwright install chromium

if [[ ! -f "config.local.json" ]]; then
  cp config.example.json config.local.json
  echo "[setup] created config.local.json from template"
fi

mkdir -p \
  demo_data \
  local_data \
  local_data/sources \
  local_data/sources/manual \
  local_data/sources/generated_exports \
  local_data/cache \
  local_data/exports \
  local_data/exports/content_packs \
  local_data/downloads \
  local_data/backups

echo "[setup] installation complete"
echo "[setup] launch with Start_ChipSeeker.bat on Windows or .venv/bin/python -m streamlit run app.py"
