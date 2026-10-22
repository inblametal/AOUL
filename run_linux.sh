#!/usr/bin/env bash
# ===================================================================
#   AOUL - AI Robotics Copilot (Linux Launcher)
#   Actuator • Orientation • Undefined-behavior • Locator
# ===================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

echo "🚀 Starting AOUL Robotics Copilot on Linux..."

if command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python run.py "$@"
else
    echo "❌ Error: Python 3 not found in PATH."
    echo "Please install Python with: sudo apt update && sudo apt install -y python3"
    exit 1
fi
