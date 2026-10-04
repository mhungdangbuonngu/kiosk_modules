#!/usr/bin/env bash
# Chạy server mẫu (API + trang demo). HOST/PORT ghi đè được:  PORT=9000 ./run.sh
set -e
cd "$(dirname "$0")"
exec "${PYTHON:-python3}" server.py --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
