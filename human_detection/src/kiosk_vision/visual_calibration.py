from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
import yaml

from .calibration import solve_homography
from .capture import RecordedVideoCapture, configure_capture, normalize_frame_size, open_camera
from .config import AppConfig
from .playback import PlaybackBar
from .preview import require_highgui

WINDOW_NAME = "Kiosk Vision - Visual Calibration"
ZONE_STYLES = (
    ("detection", "detection_polygon_m", (80, 210, 80)),
    ("approach", "approach_polygon_m", (0, 190, 255)),
    ("interaction", "interaction_polygon_m", (80, 80, 255)),
)


def floor_to_image_points(
    homography: Sequence[Sequence[float]],
    floor_points_m: Sequence[Sequence[float]],
) -> np.ndarray:
    """Project floor-plane coordinates back into camera pixel coordinates."""
    matrix = np.asarray(homography, dtype=np.float64)
    inverse = np.linalg.inv(matrix)
    points = np.asarray(floor_points_m, dtype=np.float64).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(points, inverse).reshape(-1, 2)
    if not np.isfinite(projected).all():
        raise ValueError("Zone projection produced non-finite image coordinates")
    return projected


def write_calibration_outputs(
    config_path: str | Path,
    output_path: str | Path,
    correspondences_path: str | Path,
    image_points: Sequence[Sequence[float]],
    floor_points_m: Sequence[Sequence[float]],
) -> list[list[float]]:
    """Solve the homography and persist a validated config plus reusable point pairs."""
    matrix = solve_homography(list(image_points), list(floor_points_m))
    source = Path(config_path)
    output = Path(output_path)
    correspondences = Path(correspondences_path)

    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["calibration"]["homography"] = matrix
    AppConfig.model_validate(data)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    correspondences.parent.mkdir(parents=True, exist_ok=True)
    correspondences.write_text(
        json.dumps(
            {
                "image_points": [list(point) for point in image_points],
                "floor_points_m": [list(point) for point in floor_points_m],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return matrix


def _default_output_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.stem}.calibrated{config_path.suffix}")


def parse_floor_point(raw: str) -> tuple[float, float]:
    values = raw.replace(",", " ").split()
    if len(values) != 2:
        raise ValueError("Enter exactly two numbers, for example: -1.5, 2.0")
    try:
        return float(values[0]), float(values[1])
    except ValueError as error:
        raise ValueError("Enter exactly two numbers, for example: -1.5, 2.0") from error


def _draw_zones(frame: np.ndarray, config: AppConfig, matrix: list[list[float]]) -> None:
    translucent = frame.copy()
    outlines: list[tuple[str, np.ndarray, tuple[int, int, int]]] = []
    for label, attribute, color in ZONE_STYLES:
        floor_polygon = getattr(config.calibration, attribute)
        try:
            projected = floor_to_image_points(matrix, floor_polygon)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if np.max(np.abs(projected)) > 1_000_000:
            continue
        polygon = np.rint(projected).astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(translucent, [polygon], color)
        outlines.append((label, polygon, color))
    cv2.addWeighted(translucent, 0.16, frame, 0.84, 0, frame)
    for label, polygon, color in outlines:
        cv2.polylines(frame, [polygon], True, color, 2, cv2.LINE_AA)
        anchor = tuple(polygon[0, 0])
        cv2.putText(frame, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2,
                    cv2.LINE_AA)


def _draw_hud(
    frame: np.ndarray,
    image_points: list[tuple[float, float]],
    floor_points: list[tuple[float, float]],
    paused: bool,
    has_solution: bool,
    pending_point: tuple[float, float] | None,
    coordinate_buffer: str,
    input_error: str | None,
) -> None:
    for index, (image_point, floor_point) in enumerate(zip(image_points, floor_points), start=1):
        pixel = tuple(np.rint(image_point).astype(int))
        cv2.circle(frame, pixel, 6, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, pixel, 8, (30, 30, 30), 2, cv2.LINE_AA)
        label = f"{index}: ({floor_point[0]:.2f}, {floor_point[1]:.2f})m"
        cv2.putText(frame, label, (pixel[0] + 10, pixel[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 2, cv2.LINE_AA)

    lines = [
        f"Points: {len(image_points)} (minimum 4) | {'PAUSED' if paused else 'LIVE'}",
        "Left click: add point | P/Space: pause | U: undo | R: reset",
        "S: save calibrated config | Q/Esc: quit",
    ]
    if not has_solution:
        lines.append("Add at least 4 non-collinear floor points to show zone overlays")
    if pending_point is not None:
        lines.extend([
            f"Floor x,y (metres): {coordinate_buffer}_",
            "Type in this window | Enter: confirm | Esc: cancel point",
        ])
        if input_error:
            lines.append(input_error)
        pending_pixel = tuple(np.rint(pending_point).astype(int))
        cv2.drawMarker(frame, pending_pixel, (255, 255, 0), cv2.MARKER_CROSS, 24, 2,
                       cv2.LINE_AA)
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (min(frame.shape[1] - 8, 850), 28 + 26 * len(lines)),
                  (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (20, 32 + index * 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.58, (240, 240, 240), 1, cv2.LINE_AA)


def run_visual_calibration(
    config: AppConfig,
    config_path: str | Path,
    output_path: str | Path | None = None,
    correspondences_path: str | Path | None = None,
) -> None:
    """Run a local live-camera point picker and zone-overlay calibration session."""
    require_highgui()
    source_path = Path(config_path)
    output = Path(output_path) if output_path else _default_output_path(source_path)
    correspondences = (
        Path(correspondences_path)
        if correspondences_path
        else output.with_suffix(".points.json")
    )

    capture = open_camera(config.camera)
    configure_capture(capture, config.camera)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open camera source {config.camera.source!r}")

    ok, current_frame = capture.read()
    if not ok or current_frame is None:
        capture.release()
        raise RuntimeError("Camera opened but did not return a frame")

    native_height, native_width = current_frame.shape[:2]
    current_frame = normalize_frame_size(current_frame, config.camera)
    calibration_height, calibration_width = current_frame.shape[:2]
    print(f"Camera native: {native_width}x{native_height}; calibration frame: "
          f"{calibration_width}x{calibration_height}; mode: {config.camera.resolution_mode}")
    if (native_width, native_height) != (config.camera.width, config.camera.height):
        print(f"Camera khong chap nhan mode uu tien {config.camera.width}x"
              f"{config.camera.height}; dang dung native {native_width}x{native_height}.")
    print("Bam chuot trai vao moc san, go x,y ngay trong cua so camera, roi nhan Enter.")
    print(f"Tep cau hinh se luu: {output}")
    print(f"Tep diem doi chieu se luu: {correspondences}")

    image_points: list[tuple[float, float]] = []
    floor_points: list[tuple[float, float]] = []
    pending_click: list[tuple[int, int]] = []
    pending_point: tuple[float, float] | None = None
    coordinate_buffer = ""
    input_error: str | None = None
    playback = (PlaybackBar(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 1 / capture.interval)
                if isinstance(capture, RecordedVideoCapture) else None)
    paused = playback is not None
    pending_seek: int | None = None
    matrix: list[list[float]] | None = None

    def frame_index() -> int:
        return max(0, round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1)

    def on_mouse(event: int, x: int, y: int, _flags: int, _parameter: object) -> None:
        nonlocal paused, pending_seek
        if playback is not None:
            if pending_point is not None or pending_click:
                playback.dragging = False
            else:
                action = playback.mouse_action(
                    event, x, y, calibration_width, calibration_height)
                if action == "play":
                    paused = not paused
                elif action in ("previous", "next"):
                    paused = True
                    pending_seek = frame_index() + (-1 if action == "previous" else 1)
                elif isinstance(action, int):
                    paused = True
                    pending_seek = action
            if y >= calibration_height or playback.dragging:
                return
        if (event == cv2.EVENT_LBUTTONDOWN and pending_point is None and not pending_click
                and pending_seek is None and 0 <= x < calibration_width
                and 0 <= y < calibration_height):
            paused = True  # Freeze the exact displayed frame before the next read.
            pending_click.append((x, y))

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, round(
        (calibration_height + (PlaybackBar.height if playback else 0)) * 1280 / calibration_width))
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    try:
        while True:
            if pending_seek is not None and isinstance(capture, RecordedVideoCapture):
                ok, frame = capture.seek_frame(pending_seek)
                pending_seek = None
                if ok and frame is not None:
                    current_frame = normalize_frame_size(frame, config.camera)
                else:
                    print("Could not seek to the requested video frame.")
            elif not paused:
                ok, frame = capture.read()
                if ok and frame is not None:
                    current_frame = normalize_frame_size(frame, config.camera)

            if pending_click and pending_point is None:
                click = pending_click.pop(0)
                pending_point = (float(click[0]), float(click[1]))
                coordinate_buffer = ""
                input_error = None

            display = current_frame.copy()
            if matrix is not None:
                _draw_zones(display, config, matrix)
            _draw_hud(
                display,
                image_points,
                floor_points,
                paused,
                matrix is not None,
                pending_point,
                coordinate_buffer,
                input_error,
            )
            if playback is not None:
                display = playback.render(display, frame_index(), paused,
                                          pending_point is not None or bool(pending_click))
            cv2.imshow(WINDOW_NAME, display)
            key = cv2.waitKey(15) & 0xFF
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break

            if pending_click:
                continue

            if pending_point is not None:
                if key in (10, 13):
                    try:
                        floor_point = parse_floor_point(coordinate_buffer)
                    except ValueError as error:
                        input_error = str(error)
                        continue
                    image_points.append(pending_point)
                    floor_points.append(floor_point)
                    pending_point = None
                    coordinate_buffer = ""
                    input_error = None
                    if len(image_points) >= 4:
                        try:
                            matrix = solve_homography(image_points, floor_points)
                        except ValueError as error:
                            matrix = None
                            print(f"Chua the tinh homography: {error}")
                elif key == 27:
                    pending_point = None
                    coordinate_buffer = ""
                    input_error = None
                elif key in (8, 127):
                    coordinate_buffer = coordinate_buffer[:-1]
                    input_error = None
                elif key != 255 and chr(key) in "0123456789-+., ":
                    coordinate_buffer += chr(key)
                    input_error = None
                continue

            if key in (ord("q"), 27):
                break
            if key in (ord("p"), ord(" ")):
                paused = not paused
            elif playback is not None and key in (ord(","), ord(".")):
                paused = True
                pending_seek = frame_index() + (-1 if key == ord(",") else 1)
            elif key == ord("u") and image_points:
                image_points.pop()
                floor_points.pop()
                try:
                    matrix = (solve_homography(image_points, floor_points)
                              if len(image_points) >= 4 else None)
                except ValueError:
                    matrix = None
            elif key == ord("r"):
                image_points.clear()
                floor_points.clear()
                matrix = None
            elif key == ord("s"):
                if matrix is None:
                    print("Can it nhat 4 diem hop le truoc khi luu.")
                    continue
                matrix = write_calibration_outputs(
                    source_path,
                    output,
                    correspondences,
                    image_points,
                    floor_points,
                )
                print(f"Da luu cau hinh: {output}")
                print(f"Da luu cac diem: {correspondences}")
    except KeyboardInterrupt:
        pass
    finally:
        capture.release()
        cv2.destroyAllWindows()
