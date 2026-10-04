import numpy as np

from kiosk_vision.capture import (
    FramePacket,
    LatestFrameCapture,
    RecordedVideoCapture,
    configure_capture,
    normalize_frame_size,
    open_camera,
)
from kiosk_vision.config import CameraConfig


def test_latest_frame_buffer_never_builds_backlog():
    capture = LatestFrameCapture(CameraConfig())
    capture._packet = FramePacket(1, 10, np.zeros((1, 1, 3), dtype=np.uint8))
    capture._packet = FramePacket(2, 20, np.ones((1, 1, 3), dtype=np.uint8))
    assert capture.latest().sequence == 2
    assert capture.latest(after_sequence=2) is None


def test_native_camera_frame_is_not_resized():
    native_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    normalized = normalize_frame_size(native_frame, CameraConfig(resolution_mode="native"))
    assert normalized is native_frame


def test_fixed_camera_frame_is_normalized_to_configured_resolution():
    config = CameraConfig(width=1920, height=1080, resolution_mode="fixed")
    native_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    normalized = normalize_frame_size(native_frame, config)
    assert normalized.shape == (1080, 1920, 3)


def test_native_mode_requests_preferred_driver_properties_without_resizing():
    class FakeCapture:
        def __init__(self):
            self.calls = []

        def set(self, prop, value):
            self.calls.append((prop, value))

    capture = FakeCapture()
    configure_capture(
        capture,
        CameraConfig(width=1920, height=1080, fps=30, resolution_mode="native"),
    )
    assert [value for _property, value in capture.calls] == [1920, 1080, 30]


def test_recording_uses_file_backend_and_native_pacing_and_loops(monkeypatch, tmp_path):
    import cv2

    import kiosk_vision.capture as module

    source = tmp_path / "camera.mp4"
    source.touch()
    frames = [np.full((2, 3, 3), value, dtype=np.uint8) for value in (1, 2)]

    class FakeVideo:
        index = 0

        def get(self, prop):
            return 25.0

        def isOpened(self):
            return True

        def read(self):
            if self.index >= len(frames):
                return False, None
            frame = frames[self.index]
            self.index += 1
            return True, frame

        def set(self, prop, value):
            assert prop == cv2.CAP_PROP_POS_FRAMES and value == 0
            self.index = 0

        def release(self):
            pass

    clock = [0.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(module.cv2, "VideoCapture", lambda path: FakeVideo())
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", sleep)
    config = CameraConfig(source=str(source), backend="dshow", fps=30)
    capture = open_camera(config)
    assert isinstance(capture, RecordedVideoCapture)
    configure_capture(capture, config)  # Must not set hardware properties on the file.
    assert [int(capture.read()[1][0, 0, 0]) for _ in range(3)] == [1, 2, 1]
    np.testing.assert_allclose(sleeps, [0.04, 0.04])
    clock[0] += 10  # A calibration pause must not cause catch-up bursts.
    capture.read()
    capture.read()
    np.testing.assert_allclose(sleeps, [0.04, 0.04, 0.04])


def test_recording_falls_back_to_configured_fps(monkeypatch):
    import kiosk_vision.capture as module

    class FakeVideo:
        def get(self, prop):
            return float("nan")

    monkeypatch.setattr(module.cv2, "VideoCapture", lambda source: FakeVideo())
    capture = RecordedVideoCapture("recording.mp4", fallback_fps=20)
    assert capture.interval == 0.05


def test_seek_returns_exact_frame_clamps_and_resumes_after_it(tmp_path):
    import cv2

    source = tmp_path / "seek.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 25, (64, 48))
    assert writer.isOpened()
    for value in (20, 60, 100, 140, 180):
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()
    capture = RecordedVideoCapture(str(source), 25)
    try:
        ok, frame = capture.seek_frame(2)
        assert ok and abs(float(frame.mean()) - 100) < 5
        assert capture.get(cv2.CAP_PROP_POS_FRAMES) == 3
        ok, frame = capture.read()
        assert ok and abs(float(frame.mean()) - 140) < 5
        assert abs(float(capture.seek_frame(-10)[1].mean()) - 20) < 5
        assert abs(float(capture.seek_frame(100)[1].mean()) - 180) < 5
    finally:
        capture.release()
