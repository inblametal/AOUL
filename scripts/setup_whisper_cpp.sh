#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo "🎙️ Setting up Whisper.cpp for Hands-Free Robotics Lab Copilot"
echo "=========================================================="

mkdir -p scratch
cd scratch

if [ ! -d "whisper.cpp" ]; then
    echo "⬇️ Cloning whisper.cpp repository..."
    git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git
fi

cd whisper.cpp
echo "🔨 Compiling whisper.cpp native binary..."
make -j4

if [ ! -f "models/ggml-tiny.en.bin" ]; then
    echo "⬇️ Downloading lightweight edge model: ggml-tiny.en.bin (75MB)..."
    bash ./models/download-ggml-model.sh tiny.en
fi

mkdir -p "$SCRIPT_DIR/aoul/bin"
cp main "$SCRIPT_DIR/aoul/bin/whisper-cli" 2>/dev/null || cp build/bin/whisper-cli "$SCRIPT_DIR/aoul/bin/whisper-cli"
mkdir -p "$SCRIPT_DIR/models"
cp models/ggml-tiny.en.bin "$SCRIPT_DIR/models/"

echo "=========================================================="
echo "✅ Whisper.cpp is ready!"
echo "   Binary: $SCRIPT_DIR/aoul/bin/whisper-cli"
echo "   Model:  $SCRIPT_DIR/models/ggml-tiny.en.bin"
echo "=========================================================="
