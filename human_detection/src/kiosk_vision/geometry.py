from __future__ import annotations

import math

import cv2
import numpy as np

from .config import CalibrationConfig


class SpatialMapper:
    def __init__(self, config: CalibrationConfig):
        self.config = config
        self._homography = np.asarray(config.homography, dtype=np.float64)

    def image_to_floor(self, point: tuple[float, float]) -> tuple[float, float]:
        src = np.asarray([[point]], dtype=np.float64)
        x, y = cv2.perspectiveTransform(src, self._homography)[0, 0]
        return float(x), float(y)

    def distance_to_kiosk(self, point: tuple[float, float]) -> float:
        return math.dist(point, self.config.kiosk_xy_m)

    @staticmethod
    def contains(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
        contour = np.asarray(polygon, dtype=np.float32)
        return cv2.pointPolygonTest(contour, point, False) >= 0

    def zones(self, point: tuple[float, float]) -> tuple[bool, bool, bool]:
        return (
            self.contains(point, self.config.detection_polygon_m),
            self.contains(point, self.config.approach_polygon_m),
            self.contains(point, self.config.interaction_polygon_m),
        )

