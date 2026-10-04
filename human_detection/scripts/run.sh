#!/usr/bin/env bash
# Chay server human_detection (mac dinh config/kiosk.yaml, 127.0.0.1:8765).
#   scripts/run.sh
#   scripts/run.sh --config config/kiosk_cua_toi.yaml --port 8766 --calibration-frame 1920x1080
#   scripts/run.sh --cors-origin http://localhost:3000     # trang web goi thang
# Chay scripts/setup.sh truoc mot lan (tao .venv + tai model).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --frozen --extra head-pose human-detection "$@"
