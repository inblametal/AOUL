#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

echo "🔨 Building RoboSage Native macOS Universal Binary (x86_64 + arm64)..."
mkdir -p RoboSage.app/Contents/MacOS
mkdir -p RoboSage.app/Contents/Resources/robosage

clang -O2 -framework Cocoa -framework WebKit \
    -arch x86_64 -arch arm64 \
    src_macos/main.m \
    -o RoboSage.app/Contents/MacOS/RoboSage

chmod +x RoboSage.app/Contents/MacOS/RoboSage

echo "📦 Synchronizing workspace assets to RoboSage.app bundle..."
rsync -av --exclude "__pycache__" --exclude "*.pyc" --exclude ".git" \
    robosage run.py requirements.txt pyproject.toml examples \
    RoboSage.app/Contents/Resources/robosage/

echo "✅ RoboSage.app built successfully!"
echo "   App location: $SCRIPT_DIR/RoboSage.app"
echo "   Binary type:  $(file RoboSage.app/Contents/MacOS/RoboSage | cut -d: -f2)"
