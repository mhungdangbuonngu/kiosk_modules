from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


class PreviewVideoWriter:
    """Write annotated MP4 frames at wall-clock speed despite skipped inference frames."""

    def __init__(self, path: str | Path, fps: float, source: int | str):
        self.path = Path(path)
        if isinstance(source, str) and self.path.resolve() == Path(source).resolve():
            raise ValueError("Recording output must differ from the camera source")
        if self.path.suffix.lower() != ".mp4":
            raise ValueError("Preview recording requires an .mp4 output path")
        if self.path.exists():
            raise FileExistsError(f"Recording output already exists: {self.path}")
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Recording FPS must be positive and finite")
        self.fps = fps
        self.writer: cv2.VideoWriter | None = None
        self.size: tuple[int, int] | None = None
        self.start_ms: int | None = None
        self.frames_written = 0
        self.previous: np.ndarray | None = None

    def write(self, frame: np.ndarray, timestamp_ms: int) -> None:
        size = (frame.shape[1], frame.shape[0])
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = cv2.VideoWriter(
                str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, size)
            if not self.writer.isOpened():
                self.close()
                raise RuntimeError(f"Could not create preview recording: {self.path}")
            self.size, self.start_ms = size, timestamp_ms
        if size != self.size:
            raise ValueError("Frame dimensions changed during preview recording")
        slot = max(0, int((timestamp_ms - self.start_ms) * self.fps / 1000))
        # Repeat the last displayed image in gaps, rather than speeding up the video.
        while self.frames_written < slot and self.previous is not None:
            self.writer.write(self.previous)
            self.frames_written += 1
        if self.frames_written <= slot:
            self.writer.write(frame)
            self.frames_written += 1
        self.previous = frame

    def close(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        self.previous = None
