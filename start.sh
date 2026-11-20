#!/usr/bin/env sh
# Linux launcher for the drag-and-drop UI (python -m src.app). Arguments pass through.
cd "$(dirname "$0")" || exit 1
# setup.sh creates .venv (main) and .venv-detector (YOLO); both must exist.
if [ ! -x .venv/bin/python ] || [ ! -d .venv-detector ]; then
    echo "Setup has not been run on this computer."
    echo "Run ./setup.sh (needs internet, ~10-20 min once), then start UI Compare again."
    exit 1
fi
if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "The .venv does not work here: the .venv was made on another computer."
    echo "Run ./setup.sh again (needs internet, ~10-20 min once), then start UI Compare again."
    exit 1
fi
# The detector python is found automatically (.venv-detector). Optional override:
# UI_DETECTOR_PYTHON=/path/to/python in a local .env (gitignored).
if [ -f .env ]; then
    v=$(sed -n 's/^UI_DETECTOR_PYTHON=//p' .env | tail -n 1 | tr -d '\r"')
    [ -n "$v" ] && export UI_DETECTOR_PYTHON="$v"
fi
exec .venv/bin/python -m src.app "$@"
