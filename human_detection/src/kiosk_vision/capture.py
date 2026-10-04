from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import CameraConfig

CAMERA_BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
}


@dataclass(frozen=True)
class FramePacket:
    sequence: int
    timestamp_ms: int
    frame: np.ndarray


def normalize_frame_size(frame: np.ndarray, config: CameraConfig) -> np.ndarray:
    """Preserve native frames unless fixed-size processing was explicitly requested."""
    if config.resolution_mode == "native":
        return frame
    if frame.shape[1] == config.width and frame.shape[0] == config.height:
        return frame
    return cv2.resize(frame, (config.width, config.height), interpolation=cv2.INTER_LINEAR)


class RecordedVideoCapture:
    """Loop a local recording at its native FPS, including in the calibration UI."""

    def __init__(self, source: str, fallback_fps: int):
        self.capture = cv2.VideoCapture(source)
        fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.interval = 1 / (fps if math.isfinite(fps) and fps > 0 else fallback_fps)
        self.next_frame_at = time.monotonic()

    def isOpened(self) -> bool:
        return self.capture.isOpened()

    def get(self, prop: int) -> float:
        return self.capture.get(prop)

    def seek_frame(self, index: int) -> tuple[bool, np.ndarray | None]:
        """Return the requested frame immediately and resume playback after it."""
        count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        index = max(0, min(index, max(0, count - 1)))
        if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            return False, None
        ok, frame = self.capture.read()
        self.next_frame_at = time.monotonic() + self.interval
        return ok, frame

    def read(self) -> tuple[bool, np.ndarray | None]:
        delay = self.next_frame_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        # Resuming after a pause must not decode a burst of overdue frames.
        self.next_frame_at = max(self.next_frame_at, time.monotonic()) + self.interval
        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        return ok, frame

    def release(self) -> None:
        self.capture.release()


def open_camera(config: CameraConfig) -> cv2.VideoCapture | RecordedVideoCapture:
    if isinstance(config.source, str) and Path(config.source).is_file():
        return RecordedVideoCapture(config.source, config.fps)
    backend = CAMERA_BACKENDS[config.backend]
    if backend == cv2.CAP_ANY:
        return cv2.VideoCapture(config.source)
    return cv2.VideoCapture(config.source, backend)


def configure_capture(
    capture: cv2.VideoCapture | RecordedVideoCapture, config: CameraConfig,
) -> None:
    """Request a camera mode; native mode accepts the driver's negotiated dimensions."""
    if isinstance(capture, RecordedVideoCapture):
        return
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    capture.set(cv2.CAP_PROP_FPS, config.fps)


class LatestFrameCapture:
    """A one-slot buffer: producers overwrite stale frames instead of creating latency."""

    def __init__(self, config: CameraConfig):
        self.config = config
        self._packet: FramePacket | None = None
        self._sequence = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.online = False
        self.last_error: str | None = None
        self.frame_size: tuple[int, int] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def latest(self, after_sequence: int = -1) -> FramePacket | None:
        with self._lock:
            return self._packet if self._packet and self._packet.sequence > after_sequence else None

    def _run(self) -> None:
        while not self._stop.is_set():
            capture = open_camera(self.config)
            configure_capture(capture, self.config)
            self.online = capture.isOpened()
            if not self.online:
                self.last_error = "camera_open_failed"
                capture.release()
                self._stop.wait(self.config.reconnect_ms / 1000)
                continue
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    self.online, self.last_error = False, "camera_read_failed"
                    break
                frame = normalize_frame_size(frame, self.config)
                self.frame_size = (frame.shape[1], frame.shape[0])
                self._sequence += 1
                packet = FramePacket(self._sequence, time.monotonic_ns() // 1_000_000, frame)
                with self._lock:
                    self._packet = packet
            capture.release()
            self._stop.wait(self.config.reconnect_ms / 1000)
