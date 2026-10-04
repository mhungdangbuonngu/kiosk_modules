# Chay server human_detection tren Windows (mac dinh config\kiosk.yaml, 127.0.0.1:8765).
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1 --port 8766
# Chay scripts\setup.ps1 truoc mot lan (tao .venv + tai model).
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
Push-Location $ProjectRoot
try {
    & uv run --frozen --extra head-pose human-detection @args
} finally {
    Pop-Location
}
