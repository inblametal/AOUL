#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

echo "🔨 Building AOUL Native macOS Universal Binary (x86_64 + arm64)..."
mkdir -p AOUL.app/Contents/MacOS
mkdir -p AOUL.app/Contents/Resources/robosage

# Compile universal native Cocoa/WebKit binary
clang -O2 -framework Cocoa -framework WebKit \
    -arch x86_64 -arch arm64 \
    src_macos/main.m \
    -o AOUL.app/Contents/MacOS/AOUL

chmod +x AOUL.app/Contents/MacOS/AOUL

# Copy icon if available
if [ -f RoboSage.app/Contents/Resources/AppIcon.icns ]; then
    cp RoboSage.app/Contents/Resources/AppIcon.icns AOUL.app/Contents/Resources/AppIcon.icns
fi

# Write Info.plist
cat << 'EOF' > AOUL.app/Contents/Info.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>AOUL</string>
    <key>CFBundleExecutable</key>
    <string>AOUL</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>ai.aoul.copilot</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>AOUL</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0.0</string>
    <key>CFBundleVersion</key>
    <string>2.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
    <key>NSMicrophoneUsageDescription</key>
    <string>AOUL Hands-Free Lab Copilot requires microphone access for offline voice commands at the robotics bench.</string>
    <key>NSSpeechRecognitionUsageDescription</key>
    <string>AOUL Hands-Free Lab Copilot requires speech recognition for hands-free robot telemetry and diagnostics.</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
EOF

echo "📦 Synchronizing workspace assets to AOUL.app bundle..."
rsync -av --exclude "__pycache__" --exclude "*.pyc" --exclude ".git" \
    robosage run.py requirements.txt pyproject.toml examples \
    AOUL.app/Contents/Resources/robosage/

echo "✅ AOUL.app built successfully!"
echo "   App location: $SCRIPT_DIR/AOUL.app"
echo "   Binary type:  $(file AOUL.app/Contents/MacOS/AOUL | cut -d: -f2)"
