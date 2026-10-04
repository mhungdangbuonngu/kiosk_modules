from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CameraConfig(StrictModel):
    source: int | str = 0
    backend: Literal["auto", "dshow", "msmf"] = "auto"
    width: int = Field(1920, gt=0)
    height: int = Field(1080, gt=0)
    fps: int = Field(30, gt=0)
    reconnect_ms: int = Field(1000, ge=100)
    resolution_mode: Literal["native", "fixed"] = "native"


class CalibrationConfig(StrictModel):
    homography: list[list[float]]
    kiosk_xy_m: tuple[float, float] = (0.0, 0.0)
    detection_polygon_m: list[tuple[float, float]]
    approach_polygon_m: list[tuple[float, float]]
    interaction_polygon_m: list[tuple[float, float]]

    @model_validator(mode="after")
    def validate_geometry(self) -> CalibrationConfig:
        matrix = np.asarray(self.homography, dtype=float)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            raise ValueError("homography must be a finite 3x3 matrix")
        if abs(np.linalg.det(matrix)) < 1e-12:
            raise ValueError("homography must be invertible")
        for name in ("detection_polygon_m", "approach_polygon_m", "interaction_polygon_m"):
            if len(getattr(self, name)) < 3:
                raise ValueError(f"{name} must contain at least three points")
        return self


class DetectorConfig(StrictModel):
    model_path: str = "models/yolox_nano.onnx"
    input_size: tuple[int, int] = (416, 416)
    confidence_threshold: float = Field(0.3, ge=0, le=1)
    nms_threshold: float = Field(0.45, ge=0, le=1)
    inference_interval_ms: int = Field(67, ge=1)
    provider: Literal["auto", "cpu", "cuda", "tensorrt", "openvino"] = "cpu"


class TrackerConfig(StrictModel):
    track_threshold: float = Field(0.4, ge=0, le=1)
    match_threshold: float = Field(0.8, ge=0, le=1)
    track_buffer_frames: int = Field(30, gt=0)
    max_history: int = Field(30, gt=1)


class HeadPoseConfig(StrictModel):
    enabled: bool = False
    face_detector_model_path: str = "models/face_detection_yunet.onnx"
    model_path: str = "models/face_landmarker.task"
    max_yaw_deg: float = Field(35.0, gt=0, le=90)
    max_pitch_deg: float = Field(30.0, gt=0, le=90)
    observation_ttl_ms: int = Field(500, gt=0)
    process_interval_ms: int = Field(100, gt=0)


class EngagementConfig(StrictModel):
    bbox_enter_ratio: float = Field(0.18, gt=0, le=1)
    bbox_exit_ratio: float = Field(0.12, ge=0, lt=1)
    stable_track_ms: int = Field(500, ge=0)
    dwell_ms: int = Field(600, ge=0)
    hold_ms: int = Field(1200, ge=0)
    lost_track_ms: int = Field(1000, gt=0)
    switch_margin: float = Field(0.25, ge=0)
    approaching_speed_mps: float = Field(0.12, ge=0)
    departing_speed_mps: float = Field(0.15, ge=0)
    max_lateral_speed_mps: float = Field(0.8, gt=0)
    facing_threshold: float = Field(0.55, ge=0, le=1)

    @model_validator(mode="after")
    def validate_bbox_thresholds(self) -> EngagementConfig:
        if self.bbox_exit_ratio >= self.bbox_enter_ratio:
            raise ValueError("bbox_exit_ratio must be smaller than bbox_enter_ratio")
        return self


class ServiceConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    diagnostic_media: bool = False
    log_level: str = "INFO"


class AppConfig(StrictModel):
    version: int = Field(1, ge=1)
    camera: CameraConfig = CameraConfig()
    calibration: CalibrationConfig
    detector: DetectorConfig = DetectorConfig()
    tracker: TrackerConfig = TrackerConfig()
    head_pose: HeadPoseConfig = HeadPoseConfig()
    engagement: EngagementConfig = EngagementConfig()
    service: ServiceConfig = ServiceConfig()


def load_config(path: str | Path) -> tuple[AppConfig, str]:
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    config = AppConfig.model_validate(data)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()
