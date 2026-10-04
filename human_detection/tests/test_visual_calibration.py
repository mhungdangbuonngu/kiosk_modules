from pathlib import Path

import numpy as np

from kiosk_vision.config import load_config
from kiosk_vision.visual_calibration import (
    floor_to_image_points,
    parse_floor_point,
    write_calibration_outputs,
)


def test_floor_to_image_points_inverts_homography():
    homography = [[0.01, 0, -6.4], [0, -0.01, 7.2], [0, 0, 1]]
    projected = floor_to_image_points(homography, [(-3, 0), (3, 4)])
    np.testing.assert_allclose(projected, [[340, 720], [940, 320]])


def test_parse_floor_point_accepts_comma_or_space():
    assert parse_floor_point("-1.5, 2.0") == (-1.5, 2.0)
    assert parse_floor_point("0 3.25") == (0.0, 3.25)


def test_write_calibration_outputs_creates_valid_config_and_points(tmp_path: Path):
    output = tmp_path / "kiosk.calibrated.yaml"
    points = tmp_path / "kiosk.calibrated.points.json"
    image_points = [(300, 650), (980, 650), (450, 400), (830, 400)]
    floor_points = [(-1.5, 0.5), (1.5, 0.5), (-1.5, 3.0), (1.5, 3.0)]

    matrix = write_calibration_outputs(
        "config/kiosk.example.yaml", output, points, image_points, floor_points
    )

    config, _checksum = load_config(output)
    np.testing.assert_allclose(config.calibration.homography, matrix)
    assert '"image_points"' in points.read_text(encoding="utf-8")


def test_video_controls_seek_and_point_entry_freezes_displayed_frame(monkeypatch):
    import cv2

    import kiosk_vision.visual_calibration as module
    from kiosk_vision.capture import RecordedVideoCapture

    class FakeRecording(RecordedVideoCapture):
        interval = 1 / 25
        position = 0
        reads = 0
        released = False

        def __init__(self):
            pass

        def isOpened(self):
            return True

        def get(self, prop):
            return 10 if prop == cv2.CAP_PROP_FRAME_COUNT else self.position

        def read(self):
            self.reads += 1
            self.position += 1
            return True, np.full((1080, 1920, 3), self.position, dtype=np.uint8)

        def seek_frame(self, index):
            self.position = max(0, min(9, index))
            return self.read()

        def release(self):
            self.released = True

    capture = FakeRecording()
    shown = []
    point_states = []
    callbacks = {}
    calls = [0]
    monkeypatch.setattr(module, "require_highgui", lambda: None)
    monkeypatch.setattr(module, "open_camera", lambda config: capture)
    monkeypatch.setattr(module.cv2, "namedWindow", lambda *a: None)
    monkeypatch.setattr(module.cv2, "resizeWindow", lambda *a: None)
    monkeypatch.setattr(module.cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(module.cv2, "getWindowProperty", lambda *a: 1)
    monkeypatch.setattr(module.cv2, "setMouseCallback",
                        lambda name, callback: callbacks.update(mouse=callback))
    monkeypatch.setattr(module.cv2, "imshow",
                        lambda name, image: shown.append(int(image[500, 500, 0])))
    monkeypatch.setattr(module, "_draw_hud",
                        lambda *args: point_states.append(args[5]))

    def wait_key(delay):
        index = calls[0]
        calls[0] += 1
        if index == 0:
            # Seek to last frame; this must not add an image point.
            callbacks["mouse"](cv2.EVENT_LBUTTONDOWN, 1896, 1164, 0, None)
            callbacks["mouse"](cv2.EVENT_LBUTTONUP, 1896, 1164, 0, None)
        elif index == 1:
            return ord(",")  # Previous frame, still paused.
        elif index == 2:
            return ord(" ")  # Play.
        elif index == 3:
            callbacks["mouse"](cv2.EVENT_LBUTTONDOWN, 500, 500, 0, None)
        elif index == 4:
            # Seeking while a point is being entered must be ignored.
            callbacks["mouse"](cv2.EVENT_LBUTTONDOWN, 24, 1164, 0, None)
            return ord("1")
        elif index == 5:
            return ord(",")
        elif index == 6:
            return ord("2")
        elif index == 7:
            return 13  # Confirm (1, 2).
        elif index == 8:
            return ord("q")
        return 255

    monkeypatch.setattr(module.cv2, "waitKey", wait_key)
    config, _ = load_config("config/kiosk.video.yaml")
    module.run_visual_calibration(config, "config/kiosk.video.yaml")
    assert shown == [1, 10, 9, 10, 10, 10, 10, 10, 10]
    assert capture.reads == 4
    assert point_states[:4] == [None] * 4
    assert point_states[4:8] == [(500.0, 500.0)] * 4
    assert capture.released
