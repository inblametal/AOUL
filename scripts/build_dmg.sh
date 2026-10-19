#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "📦 Packaging AOUL macOS DMG Installer..."
echo "=========================================="

# Ensure AOUL.app is fresh
bash scripts/build_app.sh

mkdir -p dist
STAGING_DIR="scratch/dmg_staging"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

echo "📂 Staging AOUL.app and Applications symlink..."
cp -R AOUL.app "$STAGING_DIR/AOUL.app"
ln -s /Applications "$STAGING_DIR/Applications"

DMG_OUT="dist/AOUL.dmg"
rm -f "$DMG_OUT"

echo "💿 Creating compressed UDZO Disk Image ($DMG_OUT)..."
hdiutil create -volname "AOUL" \
    -srcfolder "$STAGING_DIR" \
    -ov -format UDZO \
    "$DMG_OUT"

rm -rf "$STAGING_DIR"

echo "=========================================="
echo "✅ AOUL.dmg successfully created!"
echo "   File: $DMG_OUT"
echo "   Size: $(ls -lh "$DMG_OUT" | awk '{print $5}')"
echo "=========================================="
