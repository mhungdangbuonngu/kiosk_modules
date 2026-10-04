# Kiosk Intent

A local, privacy-preserving vision subsystem that turns anonymous person tracks into kiosk
engagement events. A person's bounding-box share of the camera frame is the authoritative
engagement signal; calibrated floor geometry remains available for diagnostics.

Current development commands default to the installed-camera recording in
`config/kiosk.video.yaml`, played continuously at native FPS. Start it with
`uv run kiosk-vision serve --preview`. See [video calibration](docs/VIDEO_CALIBRATION.md)
for engagement tuning and measured floor calibration. Supply a config path explicitly
to use hardware.

To save the same annotated view as an MP4, run
`uv run kiosk-vision serve --preview --record-preview diagnostics/preview.mp4`.
Press Ctrl+C to finalize the recording. The current video config engages at 30%
frame occupancy and disengages below 25%.

## What is implemented

- Latest-frame camera capture with automatic reconnect and no inference backlog.
- Native camera-resolution mode by default; no software resize unless `resolution_mode: fixed`.
- YOLOX ONNX person-only inference with selectable ONNX Runtime providers.
- Detector-agnostic Apache-2.0 ByteTrack adapter, plus a development-only IoU tracker.
- Image-foot-point to floor-coordinate homography and polygonal zones.
- Per-track world position, distance, bounding-box occupancy, and state.
- Direct `PRESENT`/`ENGAGED` decision using configurable enter/exit occupancy thresholds.
- Sticky single active-user selection using the largest qualifying box.
- Optional YuNet/MediaPipe head-pose diagnostics, disabled by default.
- `USER_ENGAGED` and `USER_LEFT` events via REST history and WebSocket.
- Health, checksums, rolling latency/FPS/error telemetry, and JSONL offline replay.
- Raw diagnostic media disabled by default.
- CPU-only inference by default; GPU providers must be selected explicitly.
- MediaPipe is capped at 0.10.21 to avoid the undocumented telemetry behavior added to newer wheels.

This repository intentionally does **not** include model weights or customer recordings.

## Install

The project uses [uv](https://docs.astral.sh/uv/) for Python installation, dependency resolution,
locking, and command execution. On Windows, the reproducible setup script synchronizes the locked
Python 3.12 environment, downloads and verifies the three model artifacts, runs the tests, and
executes the installation doctor:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

For a manual installation:

```powershell
uv sync --extra head-pose
```

Python 3.10–3.12 is supported. This upper bound follows the native-wheel availability of the
local inference stack (notably MediaPipe), and avoids source-building numerical dependencies on
newer interpreters.

ByteTrack is installed with the project through the lightweight `supervision` package. The
`--development-tracker` switch selects the simpler IoU tracker for troubleshooting only.

Place these deployment artifacts at the configured paths:

- a YOLOX Nano/Tiny ONNX export (COCO output layout), such as `models/yolox_nano.onnx`;
- the YuNet ONNX face detector, such as `models/face_detection_yunet.onnx`;
- the MediaPipe Face Landmarker task model, such as `models/face_landmarker.task`.

Model files should be provisioned by the release pipeline and checksummed there. They are ignored
by Git to avoid accidentally committing large or ambiguously licensed binaries.

## Calibrate a kiosk

Lock camera resolution, lens, height, and tilt before calibration. Measure four or more visible
floor points and enter matching image pixels and floor coordinates (metres) in a file based on
`config/calibration-points.example.json`:

```powershell
uv run kiosk-vision calibrate config/calibration-points.json config/homography.json
```

Copy the resulting matrix into a site-specific configuration based on
`config/kiosk.example.yaml`, then set physically measured detection, approach, and interaction
polygons. The example homography is only illustrative and must not be deployed.

For an interactive workflow with a live camera preview and projected zone overlays, run:

```powershell
uv run --extra visual-calibration kiosk-vision calibrate-visual config/kiosk.example.yaml
```

The visual tool writes a separate `config/kiosk.example.calibrated.yaml` by default and never
saves camera frames. See the [Vietnamese visual-calibration tutorial](docs/CALIBRATION_VI.md) for
marker placement, controls, validation, and troubleshooting.

Validate configuration and record its release checksum:

```powershell
uv run kiosk-vision validate-config config/kiosk.yaml
```

Verify the environment and all model runtimes without a camera:

```powershell
uv run --extra head-pose kiosk-vision doctor config/kiosk.example.yaml
```

After connecting a camera, also verify capture:

```powershell
uv run --extra head-pose kiosk-vision doctor config/kiosk.example.yaml --camera
```

## Run

```powershell
uv run --extra head-pose kiosk-vision serve config/kiosk.yaml
```

For a development smoke test without the official ByteTrack package:

```powershell
uv run --extra head-pose kiosk-vision serve config/kiosk.yaml --development-tracker
```

To show a local live diagnostic window with person boxes, frame occupancy, calibrated coordinates,
engagement state, zones, FPS, and latency:

```powershell
uv run --extra visual-calibration kiosk-vision serve `
  config/kiosk.calibrated.yaml --preview
```

The preview is opt-in, stays local, and does not save frames. Press `Q` or `Esc` in the preview
window to close it while leaving the API service running.

Endpoints:

- `GET /health` — readiness, configuration checksum, active track, and performance counters.
- `GET /tracks` — current anonymous track state for diagnostics.
- `GET /events` — bounded recent event history.
- `WS /events/ws` — live event stream with a one-event subscriber buffer.

The API binds to loopback by default. Put authentication and transport security at the kiosk's
IPC boundary before exposing it to any network.

## Offline regression

Replay precomputed anonymous observations without retaining video:

```powershell
uv run kiosk-vision replay config/kiosk.yaml tests/data/scenario.jsonl
```

Each JSONL row has a monotonic timestamp and tracker/head observations:

```json
{"timestamp_ms":1200,"tracks":[{"track_id":31,"bbox":[500,100,1100,1000],"confidence":0.92}]}
```

Build site-specific labeled scenarios around direct/diagonal approaches, passers-by, groups,
occlusion, varied heights and mobility, face coverings, lighting extremes, and active-user
contention. CI should compare emitted events and latency to explicit release gates. Numeric
telemetry should remain the default; enable diagnostic media only through a site-approved privacy
procedure.

## Operational notes

- Camera timestamps use a monotonic clock. Never replace them with frame counts.
- Detector failures are isolated per frame and counted; camera reads reconnect automatically.
- The enter/exit threshold gap prevents a session from flickering near the boundary.
- Track IDs are process-local, anonymous, and ephemeral. Restarting the service resets them.
- Use a process supervisor (Windows Service, systemd, or container restart policy) as the outer
  watchdog. `/health` supplies the liveness data for that supervisor.

Run verification with:

```powershell
uv run pytest -q
uv run ruff check .
```
