from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import ClassVar

import cv2
import numpy as np

from .config import DetectorConfig
from .models import Detection


class YoloXOnnxDetector:
    """YOLOX ONNX inference restricted to COCO person class (class 0)."""

    PROVIDERS: ClassVar[dict[str, list[str]]] = {
        "cpu": ["CPUExecutionProvider"],
        "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "tensorrt": ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
        "openvino": ["OpenVINOExecutionProvider", "CPUExecutionProvider"],
    }

    def __init__(self, config: DetectorConfig):
        import onnxruntime as ort
        if not Path(config.model_path).is_file():
            raise FileNotFoundError(f"YOLOX ONNX model not found: {config.model_path}")
        self.model_checksum = hashlib.sha256(Path(config.model_path).read_bytes()).hexdigest()
        available = ort.get_available_providers()
        requested = self.PROVIDERS.get(config.provider, available)
        providers = [provider for provider in requested if provider in available]
        if not providers:
            providers = ["CPUExecutionProvider"]
        options = ort.SessionOptions()
        options.enable_profiling = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(config.model_path, options, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.config = config
        self.last_latency_ms = 0.0
        self._grids, self._strides = self._make_grids(config.input_size)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        tensor, ratio = self._preprocess(frame)
        start = time.perf_counter()
        output = self.session.run(None, {self.input_name: tensor})[0][0]
        self.last_latency_ms = (time.perf_counter() - start) * 1000
        output[..., :2] = (output[..., :2] + self._grids) * self._strides
        output[..., 2:4] = np.exp(output[..., 2:4]) * self._strides
        boxes = np.empty_like(output[:, :4])
        boxes[:, 0] = output[:, 0] - output[:, 2] / 2
        boxes[:, 1] = output[:, 1] - output[:, 3] / 2
        boxes[:, 2] = output[:, 0] + output[:, 2] / 2
        boxes[:, 3] = output[:, 1] + output[:, 3] / 2
        scores = output[:, 4] * output[:, 5]  # objectness * COCO person probability
        keep = scores >= self.config.confidence_threshold
        boxes, scores = boxes[keep] / ratio, scores[keep]
        nms_boxes = boxes.copy()
        nms_boxes[:, 2] -= nms_boxes[:, 0]
        nms_boxes[:, 3] -= nms_boxes[:, 1]
        indices = cv2.dnn.NMSBoxes(nms_boxes.tolist(), scores.tolist(),
                                  self.config.confidence_threshold, self.config.nms_threshold)
        return [Detection(tuple(map(float, boxes[int(i)])), float(scores[int(i)]))
                for i in np.asarray(indices).reshape(-1)]

    def _preprocess(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        width, height = self.config.input_size
        ratio = min(height / frame.shape[0], width / frame.shape[1])
        resized = cv2.resize(frame, (int(frame.shape[1] * ratio), int(frame.shape[0] * ratio)))
        padded = np.full((height, width, 3), 114, dtype=np.uint8)
        padded[:resized.shape[0], :resized.shape[1]] = resized
        tensor = padded.transpose(2, 0, 1)[None].astype(np.float32)
        return np.ascontiguousarray(tensor), ratio

    @staticmethod
    def _make_grids(input_size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        width, height = input_size
        grids, strides = [], []
        for stride in (8, 16, 32):
            yv, xv = np.meshgrid(np.arange(height // stride), np.arange(width // stride), indexing="ij")
            grids.append(np.stack((xv, yv), 2).reshape(1, -1, 2))
            strides.append(np.full((*grids[-1].shape[:2], 1), stride))
        return np.concatenate(grids, 1)[0], np.concatenate(strides, 1)[0]
