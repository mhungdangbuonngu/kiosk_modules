from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from .config import AppConfig
from .models import PersonTrack, TrackState

WINDOW_NAME = "Kiosk Vision - Live Detection"
STATE_COLORS = {
    TrackState.PRESENT: (180, 180, 180),
    TrackState.APPROACHING: (0, 180, 255),
    TrackState.CANDIDATE: (255, 190, 60),
    TrackState.ENGAGED: (70, 220, 90),
    TrackState.ENGAGED_HOLD: (70, 220, 220),
    TrackState.DEPARTING: (210, 100, 220),
}
ZONE_STYLES = (
    ("DETECTION", "detection_polygon_m", (80, 210, 80)),
    ("APPROACH", "approach_polygon_m", (0, 190, 255)),
    ("INTERACTION", "interaction_polygon_m", (80, 80, 255)),
)


def require_highgui() -> None:
    """Fail early when a headless OpenCV wheel has replaced the GUI build."""
    gui_lines = [
        line.strip() for line in cv2.getBuildInformation().splitlines()
        if line.strip().startswith("GUI:")
    ]
    if gui_lines and gui_lines[0].upper().endswith("NONE"):
        raise RuntimeError(
            "OpenCV GUI is unavailable (GUI: NONE). Reinstall the project environment "
            "with the visual-calibration extra; do not install opencv-python-headless."
        )


def _draw_label(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
    scale: float = 0.58,
) -> None:
    (width, height), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2
    )
    x, y = origin
    y = max(height + baseline + 4, y)
    cv2.rectangle(frame, (x, y - height - baseline - 6), (x + width + 10, y + 4),
                  (18, 18, 18), -1)
    cv2.putText(frame, text, (x + 5, y - baseline), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, 2, cv2.LINE_AA)


def _draw_zones(frame: np.ndarray, config: AppConfig) -> None:
    try:
        inverse = np.linalg.inv(np.asarray(config.calibration.homography, dtype=np.float64))
    except np.linalg.LinAlgError:
        return
    translucent = frame.copy()
    outlines: list[tuple[str, np.ndarray, tuple[int, int, int]]] = []
    for label, attribute, color in ZONE_STYLES:
        points = np.asarray(getattr(config.calibration, attribute), dtype=np.float64)
        projected = cv2.perspectiveTransform(points.reshape(-1, 1, 2), inverse).reshape(-1, 2)
        if not np.isfinite(projected).all() or np.max(np.abs(projected)) > 1_000_000:
            continue
        polygon = np.rint(projected).astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(translucent, [polygon], color)
        outlines.append((label, polygon, color))
    cv2.addWeighted(translucent, 0.08, frame, 0.92, 0, frame)
    for label, polygon, color in outlines:
        cv2.polylines(frame, [polygon], True, color, 2, cv2.LINE_AA)
        anchor = tuple(polygon[0, 0])
        cv2.putText(frame, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1,
                    cv2.LINE_AA)


def render_preview(
    frame: np.ndarray,
    tracks: Sequence[PersonTrack],
    active_track_id: int | None,
    telemetry: dict[str, float | int] | None = None,
    config: AppConfig | None = None,
) -> np.ndarray:
    """Render diagnostic annotations without mutating the captured frame."""
    display = frame.copy()
    if config is not None:
        _draw_zones(display, config)

    visible_tracks = list(tracks)
    for track in visible_tracks:
        color = STATE_COLORS[track.state]
        x1, y1, x2, y2 = (round(value) for value in track.bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(display.shape[1] - 1, x2), min(display.shape[0] - 1, y2)
        active = track.id == active_track_id
        cv2.rectangle(display, (x1, y1), (x2, y2), color, 4 if active else 2,
                      cv2.LINE_AA)

        distance = "?" if track.distance_to_kiosk is None else f"{track.distance_to_kiosk:.2f}m"
        occupancy = f"{track.bbox_area_ratio * 100:.1f}% frame"
        active_text = " | ACTIVE" if active else ""
        _draw_label(display, f"ID {track.id} | {track.state.value} | {occupancy} | "
                    f"{distance}{active_text}",
                    (x1, y1), color)

        if track.foot_point is not None:
            foot = tuple(np.rint(track.foot_point).astype(int))
            cv2.circle(display, foot, 7, color, -1, cv2.LINE_AA)
            cv2.line(display, (foot[0] - 12, foot[1]), (foot[0] + 12, foot[1]), color, 2,
                     cv2.LINE_AA)
        if track.world_xy is not None:
            world_label = f"x={track.world_xy[0]:.2f}  y={track.world_xy[1]:.2f}"
            cv2.putText(display, world_label, (x1, min(display.shape[0] - 10, y2 + 24)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA)

    active = next((track for track in visible_tracks if track.id == active_track_id), None)
    if active is not None and active.state == TrackState.ENGAGED:
        status = f"KIOSK IN USE - ID {active.id} ({active.bbox_area_ratio * 100:.1f}%)"
        status_color = STATE_COLORS[active.state]
    elif visible_tracks:
        status, status_color = f"PERSON DETECTED - {len(visible_tracks)}", (0, 210, 255)
    else:
        status, status_color = "NO PERSON DETECTED", (170, 170, 170)

    panel = display.copy()
    cv2.rectangle(panel, (12, 12), (min(display.shape[1] - 12, 560), 90),
                  (16, 16, 16), -1)
    cv2.addWeighted(panel, 0.74, display, 0.26, 0, display)
    cv2.putText(display, status, (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.56, status_color, 1,
                cv2.LINE_AA)
    values = telemetry or {}
    detail = (
        f"FPS {float(values.get('processing_fps', 0)):.1f} | "
        f"Latency p50 {float(values.get('latency_median_ms', 0)):.1f}ms | "
        f"Frame {frame.shape[1]}x{frame.shape[0]}"
    )
    cv2.putText(display, detail, (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                (235, 235, 235), 1, cv2.LINE_AA)
    cv2.putText(display, "Q/Esc: close preview (service keeps running)", (24, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (190, 190, 190), 1, cv2.LINE_AA)
    return display


class PreviewWindow:
    def __init__(self, config: AppConfig):
        require_highgui()
        self.config = config
        self.open = True
        self._created = False

    def show(
        self,
        frame: np.ndarray,
        tracks: Sequence[PersonTrack],
        active_track_id: int | None,
        telemetry: dict[str, float | int],
    ) -> bool:
        if not self.open:
            return False
        annotated = render_preview(frame, tracks, active_track_id, telemetry, self.config)
        return self.show_rendered(annotated)

    def show_rendered(self, annotated: np.ndarray) -> bool:
        """Display the same annotation image that can also be written to video."""
        if not self.open:
            return False
        if not self._created:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            self._created = True
        cv2.imshow(WINDOW_NAME, annotated)
        key = cv2.waitKey(1) & 0xFF
        try:
            visible = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            visible = False
        if key in (ord("q"), 27) or not visible:
            self.close()
        return self.open

    def close(self) -> None:
        if self._created:
            try:
                cv2.destroyWindow(WINDOW_NAME)
            except cv2.error:
                pass
        self._created = False
        self.open = False
