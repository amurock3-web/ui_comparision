#!/usr/bin/env bash
# One-time setup on Ubuntu: creates .venv (main, paddle) and .venv-detector (YOLO),
# installs the pinned requirements into each, then runs the setup doctor.
# Safe to re-run: existing healthy venvs are kept and pip skips what is installed.
# Run:  bash setup.sh   (or chmod +x setup.sh && ./setup.sh)
set -euo pipefail
cd "$(dirname "$0")"
trap 'echo; echo "ERROR: setup failed (line $LINENO). Fix the error above and re-run setup.sh - it is safe to re-run." >&2' ERR

echo "Setting up UI Comparison in $PWD"
echo "Needs internet, about 10-20 min the first time; re-running is safe and fast."
echo

if ! command -v python3.11 >/dev/null 2>&1; then
    trap - ERR
    echo "ERROR: python3.11 was not found. Install it with:"
    echo "  sudo add-apt-repository ppa:deadsnakes/ppa   # Ubuntu 22.04/24.04 do not ship 3.11"
    echo "  sudo apt install python3.11 python3.11-venv"
    exit 1
fi

# opencv (main venv) needs libGL at import time; minimal/server installs lack it.
if ! ldconfig -p 2>/dev/null | grep 'libGL.so.1' >/dev/null; then
    echo "WARNING: libGL.so.1 not found; OpenCV will fail to import. Fix: sudo apt install libgl1 libglib2.0-0"
fi

# Keeps a healthy venv; recreates one whose python does not run here
# (e.g. copied from another machine) or is not 3.11.
ensure_venv() {
    local v=$1
    if [ -x "$v/bin/python" ] &&
       "$v/bin/python" -c 'import sys, pip; sys.exit(sys.version_info[:2] != (3, 11))' >/dev/null 2>&1; then
        echo "$v is ready."
        return 0
    fi
    if [ -e "$v" ]; then
        echo "$v exists but its Python does not run here (copied from another machine?). Recreating it."
        rm -rf "$v"
    fi
    echo "Creating $v"
    python3.11 -m venv "$v" || {
        trap - ERR
        echo "ERROR: could not create $v. Install the venv module: sudo apt install python3.11-venv" >&2
        rm -rf "$v"
        exit 1
    }
}

ensure_venv .venv
ensure_venv .venv-detector

echo; echo "[1/4] Upgrading pip in .venv"
.venv/bin/python -m pip install --upgrade pip
echo; echo "[2/4] Installing requirements.txt into .venv"
.venv/bin/python -m pip install -r requirements.txt
echo; echo "[3/4] Upgrading pip in .venv-detector"
.venv-detector/bin/python -m pip install --upgrade pip
echo; echo "[4/4] Installing requirements-detector.txt into .venv-detector (CPU torch)"
.venv-detector/bin/python -m pip install -r requirements-detector.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

echo; echo "Running the setup check"
trap - ERR
exec .venv/bin/python -m scripts.check_setup
