# Calibrate with the installed-camera recording

Current source: `example/WIN_20260930_16_18_37_Pro.mp4` (1920×1080,
approximately 25 FPS, 59.73 seconds). Run commands from the repository root.
`config/kiosk.video.yaml` is the CLI default for serve, doctor, validate-config,
and calibrate-visual. Files loop at native FPS; timestamps remain monotonic across
loops. The runtime keeps its latest-frame buffer and can skip frames under load.
Tracks are not reset at the loop boundary, so judge events within each pass rather
than at the artificial last-to-first transition.

## Tune engagement first

```powershell
uv run kiosk-vision doctor --camera
uv run kiosk-vision serve --preview
```

Watch the `% frame` label on each detected person and compare it with when the
person actually starts and stops using the kiosk. Write down those video times.
The ratio is clipped box area divided by full frame area, not person height.

Edit `engagement.bbox_enter_ratio` and `engagement.bbox_exit_ratio` in
`config/kiosk.video.yaml`. Current values are 0.30 and 0.25: enter at 30%,
remain engaged at 25% or above, and leave below 25%. Choose an enter threshold that
separates actual users from passers-by, and a smaller exit threshold to prevent
flicker. Restart the service after edits and review `/events` and `/tracks` at
`http://127.0.0.1:8765`. Validate several loops, including approaches, departures,
occlusion, and multiple people if present. Missing tracks leave after
`lost_track_ms`; dwell/hold settings do not gate this direct occupancy decision.
If users and passers-by have overlapping box sizes, thresholds alone cannot
separate them; capture that failure before changing the engagement logic.

## Save the rendered preview

```powershell
uv run kiosk-vision serve --preview --record-preview diagnostics/preview.mp4
```

The MP4 contains the same rendered image as the window: boxes, anonymous IDs,
occupancy percentages, states, floor zones, and the compact status panel. Omit
`--preview` to record without a window. Press Ctrl+C to stop the service and finalize
the file. Closing the preview window leaves recording and the service running.
Recording continues across video loops until you stop the service. Use a new
output filename each time; the source and existing files are protected.

The output uses `camera.fps` (25 for this recording) and repeats the last rendered
frame when inference skips frames, preserving elapsed playback time. It contains
video only, without audio. Recording adds rendering/encoding work and is enabled
only by the explicit `--record-preview` option.

Head-pose inference is disabled in this config. The model is not loaded or run,
and score calculation is skipped. `facing_score: null` remains in the API for
compatibility; engagement uses occupancy alone.

## Calibrate floor coordinates separately

Floor geometry currently provides diagnostics, not the engagement decision.
The video config contains illustrative geometry. To obtain metres, identify at
least four non-collinear visible floor landmarks and measure their real `(x,y)`
coordinates relative to the kiosk. Use more points spread across the floor when
possible. A recording alone does not supply those measurements. Existing point
files are only reusable if verified for this exact camera view and resolution.

```powershell
uv run kiosk-vision calibrate-visual --output config/kiosk.video.yaml --correspondences config/kiosk.video.points.json
```

The video opens paused on its first frame. Use the bottom **Play/Pause** button
or `P` / Space to play and pause. Click or drag the timeline to any point in the
recording; seeking leaves it paused. The time display shows your position and the
current frame number. Use **< Frame** / **Frame >** or `,` / `.` to step a single
frame backward or forward. Playback controls sit below the image and do not change
calibration pixel coordinates.

Clicking a floor landmark automatically freezes the displayed frame. While you
enter its coordinates, playback and seeking stay locked until Enter confirms the
point or Esc cancels it. Collected landmarks remain visible when you seek.

Pause on a clear frame. Click each measured landmark, type its
`x,y` in metres, and press Enter. After at least four points, check the projected
zones and press `S` to save into the current default config. `U` undoes a point,
`R` resets, and `Q` exits. Set the zone polygons from actual measurements in the
saved config and check positions withheld from the homography fit.

```powershell
uv run kiosk-vision validate-config
uv run kiosk-vision serve --preview
```

Keep the camera view, crop, and resolution identical when transferring these
settings to hardware. To explicitly run an existing hardware config, supply its
path, for example `uv run kiosk-vision serve config/kiosk.production.calibrated.yaml`.
