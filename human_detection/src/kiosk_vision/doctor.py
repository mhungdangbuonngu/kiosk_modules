from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .capture import open_camera
from .config import AppConfig
from .detector import YoloXOnnxDetector
from .head_pose import MediaPipeHeadPose
from .tracking import ByteTrackAdapter


def installation_report(config: AppConfig, check_camera: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": False,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "models": {},
    }
    detector = YoloXOnnxDetector(config.detector)
    detector.detect(np.zeros((config.camera.height, config.camera.width, 3), dtype=np.uint8))
    report["onnx_providers"] = detector.session.get_providers()
    report["detector_latency_ms"] = round(detector.last_latency_ms, 2)
    report["models"]["detector"] = detector.model_checksum

    tracker = ByteTrackAdapter(config.tracker.track_threshold, config.tracker.match_threshold,
                               config.tracker.track_buffer_frames, config.camera.fps)
    report["tracker"] = type(tracker._tracker).__name__

    head_pose = MediaPipeHeadPose(config.head_pose) if config.head_pose.enabled else None
    try:
        if head_pose:
            for name, path in {
                "face_detector": config.head_pose.face_detector_model_path,
                "head_pose": config.head_pose.model_path,
            }.items():
                report["models"][name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            report["head_pose"] = "loaded"
    finally:
        if head_pose:
            head_pose.close()

    if check_camera:
        capture = open_camera(config.camera)
        try:
            frames = sum(1 for _ in range(5) if capture.read()[0]) if capture.isOpened() else 0
            report["camera"] = {"opened": capture.isOpened(), "frames_read": frames}
            if frames == 0:
                report["error"] = "camera_open_or_read_failed"
                return report
        finally:
            capture.release()
    else:
        report["camera"] = "skipped"
    report["ok"] = True
    return report
