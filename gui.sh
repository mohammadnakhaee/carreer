#!/usr/bin/env bash
# Launch the career-ops Streamlit GUI. Creates .venv on first run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQS="streamlit_app/requirements.txt"

have_uv() { command -v uv >/dev/null 2>&1; }

if [[ ! -d "$VENV_DIR" ]]; then
  echo "→ Creating venv at $VENV_DIR ..."
  if have_uv; then
    uv venv "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
fi

# Install / refresh deps if streamlit isn't importable.
if ! "$VENV_DIR/bin/python" -c "import streamlit" >/dev/null 2>&1; then
  echo "→ Installing dependencies from $REQS ..."
  if have_uv; then
    uv pip install --python "$VENV_DIR/bin/python" -r "$REQS"
  else
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$REQS"
  fi
fi

# Per-row download links rely on Streamlit's static server. Streamlit checks
# the static folder existence at boot, so pre-create it and seed hardlinks
# from output/. The app re-syncs on each render to pick up new artifacts.
mkdir -p streamlit_app/static/output
"$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, 'streamlit_app')
from pathlib import Path
import career_data as cd
cd.sync_static_output(Path('.').resolve())
"

exec "$VENV_DIR/bin/streamlit" run streamlit_app/app.py \
  --server.enableStaticServing=true \
  "$@"
