from __future__ import annotations

import math
from collections.abc import Sequence

import cv2
import numpy as np

from .config import HeadPoseConfig
from .models import HeadObservation, PersonTrack


class MediaPipeHeadPose:
    """Runs Face Landmarker only on upper-body crops belonging to relevant tracks."""

    def __init__(self, config: HeadPoseConfig):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError("Install kiosk-intent[head-pose] to enable Face Landmarker") from exc
        base = mp.tasks.BaseOptions(model_asset_path=config.model_path)
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=base,
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            output_facial_transformation_matrixes=True,
        )
        self._mp = mp
        self._face_detector = cv2.FaceDetectorYN.create(
            config.face_detector_model_path, "", (320, 320), score_threshold=0.8,
            nms_threshold=0.3, top_k=20)
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

    def observe(self, frame: np.ndarray, tracks: Sequence[PersonTrack],
                timestamp_ms: int) -> dict[int, HeadObservation]:
        observations: dict[int, HeadObservation] = {}
        height, width = frame.shape[:2]
        for track in tracks:
            if not (track.in_interaction_zone or track.in_approach_zone):
                continue
            x1, y1, x2, y2 = track.bbox
            left, top = max(0, int(x1)), max(0, int(y1))
            right = min(width, int(x2))
            bottom = min(height, int(y1 + 0.55 * (y2 - y1)))
            if right - left < 20 or bottom - top < 20:
                continue
            upper_body = frame[top:bottom, left:right]
            self._face_detector.setInputSize((upper_body.shape[1], upper_body.shape[0]))
            _, faces = self._face_detector.detect(upper_body)
            if faces is None or len(faces) == 0:
                continue
            face = max(faces, key=lambda item: float(item[-1]))
            fx, fy, fw, fh = map(float, face[:4])
            padding = 0.2
            face_left = max(0, int(fx - fw * padding))
            face_top = max(0, int(fy - fh * padding))
            face_right = min(upper_body.shape[1], int(fx + fw * (1 + padding)))
            face_bottom = min(upper_body.shape[0], int(fy + fh * (1 + padding)))
            if face_right - face_left < 20 or face_bottom - face_top < 20:
                continue
            face_crop = upper_body[face_top:face_bottom, face_left:face_right]
            crop = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                                   data=np.ascontiguousarray(crop))
            result = self._landmarker.detect(image)
            if not result.facial_transformation_matrixes:
                continue
            rotation = np.asarray(result.facial_transformation_matrixes[0], dtype=np.float64)[:3, :3]
            pitch = math.degrees(math.atan2(rotation[2, 1], rotation[2, 2]))
            yaw = math.degrees(math.atan2(-rotation[2, 0],
                                          math.hypot(rotation[2, 1], rotation[2, 2])))
            observations[track.id] = HeadObservation(timestamp_ms, yaw, pitch, 1.0)
        return observations

    def close(self) -> None:
        self._landmarker.close()
