$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ModelsDirectory = Join-Path $ProjectRoot "models"
$Uv = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"

if (-not $Uv) {
    throw "uv was not found. Install it from https://docs.astral.sh/uv/getting-started/installation/"
}

Push-Location $ProjectRoot
try {
    & $Uv sync --locked --extra head-pose --extra visual-calibration
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $ModelsDirectory -Force | Out-Null
$Models = @(
    @{
        Name = "yolox_nano.onnx"
        Uri = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
        Sha256 = "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"
    },
    @{
        Name = "face_detection_yunet.onnx"
        Uri = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        Sha256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
    },
    @{
        Name = "face_landmarker.task"
        Uri = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
        Sha256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
    }
)

foreach ($Model in $Models) {
    $Destination = Join-Path $ModelsDirectory $Model.Name
    if (-not (Test-Path -LiteralPath $Destination)) {
        Invoke-WebRequest -Uri $Model.Uri -OutFile $Destination
    }
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
    if ($Actual -ne $Model.Sha256) {
        throw "Checksum mismatch for $($Model.Name): expected $($Model.Sha256), got $Actual"
    }
}

Push-Location $ProjectRoot
try {
    & $Uv pip check
    & $Uv run --locked --extra head-pose --extra visual-calibration pytest -q
    & $Uv run --locked --extra head-pose --extra visual-calibration kiosk-vision doctor config\kiosk.yaml
} finally {
    Pop-Location
}
