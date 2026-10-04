import cv2
import numpy as np
import pytest

from kiosk_vision.recording import PreviewVideoWriter


def test_recording_preserves_timing_and_finalizes_playable_mp4(tmp_path):
    output = tmp_path / "preview.mp4"
    recorder = PreviewVideoWriter(output, fps=10, source="input.mp4")
    dark = np.full((48, 64, 3), 20, dtype=np.uint8)
    bright = np.full((48, 64, 3), 180, dtype=np.uint8)
    recorder.write(dark, 1000)
    recorder.write(bright, 1300)  # Skipped frames must not make playback run faster.
    assert recorder.frames_written == 4
    recorder.close()
    capture = cv2.VideoCapture(str(output))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FPS) == 10
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 4
        means = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape == (48, 64, 3)
            means.append(float(frame.mean()))
        assert max(means[:3]) < 30
        assert means[3] > 160
    finally:
        capture.release()


def test_recording_protects_source_and_existing_output(tmp_path):
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"source")
    with pytest.raises(ValueError, match="differ"):
        PreviewVideoWriter(source, 25, str(source))
    with pytest.raises(FileExistsError):
        PreviewVideoWriter(source, 25, "other.mp4")
    with pytest.raises(ValueError, match=".mp4"):
        PreviewVideoWriter(tmp_path / "output.txt", 25, "other.mp4")
    assert source.read_bytes() == b"source"


def test_recording_rejects_dimension_changes(tmp_path):
    recorder = PreviewVideoWriter(tmp_path / "preview.mp4", 25, "input.mp4")
    try:
        recorder.write(np.zeros((48, 64, 3), dtype=np.uint8), 0)
        with pytest.raises(ValueError, match="dimensions"):
            recorder.write(np.zeros((96, 128, 3), dtype=np.uint8), 40)
    finally:
        recorder.close()
