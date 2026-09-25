#!/usr/bin/env sh
# Linux launcher for the drag-and-drop UI (python -m src.app). Arguments pass through.
cd "$(dirname "$0")" || exit 1
[ -f .venv/bin/activate ] && . .venv/bin/activate
# UI_DETECTOR_PYTHON=/path/to/python in a local .env (gitignored) points at the YOLO venv.
if [ -f .env ]; then
    v=$(sed -n 's/^UI_DETECTOR_PYTHON=//p' .env | tail -n 1 | tr -d '\r"')
    [ -n "$v" ] && export UI_DETECTOR_PYTHON="$v"
fi
exec python -m src.app "$@"
