from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def solve_homography(image_points: list[tuple[float, float]],
                     floor_points_m: list[tuple[float, float]]) -> list[list[float]]:
    if len(image_points) != len(floor_points_m) or len(image_points) < 4:
        raise ValueError("At least four matching image and floor points are required")
    matrix, mask = cv2.findHomography(np.asarray(image_points, dtype=np.float64),
                                      np.asarray(floor_points_m, dtype=np.float64), cv2.RANSAC)
    if matrix is None or mask is None or int(mask.sum()) < 4:
        raise ValueError("Could not solve a valid homography from these correspondences")
    return matrix.tolist()


def calibrate_file(correspondences_path: str | Path, output_path: str | Path) -> None:
    source = json.loads(Path(correspondences_path).read_text(encoding="utf-8"))
    matrix = solve_homography(source["image_points"], source["floor_points_m"])
    Path(output_path).write_text(json.dumps({"homography": matrix}, indent=2), encoding="utf-8")

