#!/usr/bin/env bash
# Cai dat human_detection lan dau (Linux/macOS): tao .venv Python 3.12 dung phien
# ban khoa trong uv.lock, tai 3 model con thieu roi kiem SHA-256, chay test.
# Windows: scripts\setup.ps1.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "Can uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv sync --locked --extra head-pose

# Nguon + SHA-256 giong models/MANIFEST.md.
fetch_model() {
    local name=$1 url=$2 sha=$3 dest="models/$1"
    if [ ! -f "$dest" ]; then
        echo "[human_detection] Tai $name ..."
        curl -fL --retry 3 -o "$dest.part" "$url"
        mv "$dest.part" "$dest"
    fi
    if ! echo "$sha  $dest" | sha256sum -c --quiet - >/dev/null 2>&1; then
        echo "[human_detection] SAI checksum: $dest — xoa file roi chay lai de tai lai." >&2
        exit 1
    fi
}
mkdir -p models
fetch_model yolox_nano.onnx \
    https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx \
    c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d
fetch_model face_detection_yunet.onnx \
    https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
fetch_model face_landmarker.task \
    https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
    64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff

uv run --locked --extra head-pose --group dev pytest -q
echo "[human_detection] Xong. Chay server: scripts/run.sh"
