from __future__ import annotations

import cv2
import numpy as np


class PlaybackBar:
    """Controls below the image, so their clicks never become calibration points."""

    height = 112
    padding = 24

    def __init__(self, frame_count: int, fps: float):
        self.frame_count = max(1, frame_count)
        self.fps = fps
        self.dragging = False

    def mouse_action(self, event: int, x: int, y: int, width: int, image_height: int):
        """Return play, previous, next, or a frame index; scrubbing clamps at edges."""
        local_y = y - image_height
        if event == cv2.EVENT_LBUTTONUP:
            was_dragging = self.dragging
            self.dragging = False
            if was_dragging:
                return self.frame_at_x(x, width)
        if event == cv2.EVENT_MOUSEMOVE and self.dragging:
            return self.frame_at_x(x, width)
        if event != cv2.EVENT_LBUTTONDOWN:
            return None
        if 64 <= local_y <= 104:
            self.dragging = True
            return self.frame_at_x(x, width)
        if 12 <= local_y <= 52:
            if 24 <= x <= 124:
                return "play"
            if 140 <= x <= 240:
                return "previous"
            if 256 <= x <= 356:
                return "next"
        return None

    def frame_at_x(self, x: int, width: int) -> int:
        fraction = (x - self.padding) / max(1, width - 2 * self.padding)
        return round(min(1.0, max(0.0, fraction)) * (self.frame_count - 1))

    @staticmethod
    def format_time(seconds: float) -> str:
        minutes, seconds = divmod(max(0.0, seconds), 60)
        return f"{int(minutes):02d}:{seconds:05.2f}"

    def render(self, image: np.ndarray, index: int, paused: bool, editing: bool) -> np.ndarray:
        width = image.shape[1]
        bar = np.full((self.height, width, 3), (28, 25, 23), dtype=np.uint8)
        text = (245, 241, 235)
        accent = (150, 215, 110)
        for x, label in ((24, "Play" if paused else "Pause"), (140, "< Frame"),
                         (256, "Frame >")):
            cv2.rectangle(bar, (x, 12), (x + 100, 52), (65, 59, 53), -1)
            cv2.putText(bar, label, (x + 10, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, text if not editing else (150, 150, 150), 1, cv2.LINE_AA)
        position = self.format_time(index / self.fps)
        end = self.format_time((self.frame_count - 1) / self.fps)
        label = f"{position} / {end}   Frame {index + 1}/{self.frame_count}"
        cv2.putText(bar, label, (380, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text, 1,
                    cv2.LINE_AA)
        if width >= 1550:
            hint = "Confirm or cancel point to seek" if editing else "Space: play/pause   , / .: step"
            cv2.putText(bar, hint, (width - 480, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, text, 1, cv2.LINE_AA)
        left, right, y = self.padding, width - self.padding, 84
        fraction = index / max(1, self.frame_count - 1)
        cursor = round(left + fraction * (right - left))
        cv2.line(bar, (left, y), (right, y), (110, 101, 94), 4, cv2.LINE_AA)
        cv2.line(bar, (left, y), (cursor, y), accent, 4, cv2.LINE_AA)
        cv2.circle(bar, (cursor, y), 8, accent, -1, cv2.LINE_AA)
        return np.concatenate((image, bar), axis=0)
