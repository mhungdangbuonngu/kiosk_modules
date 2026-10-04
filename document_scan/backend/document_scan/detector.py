"""Nhận diện 4 góc tài liệu bằng YOLO pose (1 lớp `document`, 4 keypoint), chạy bằng
ONNX Runtime thuần — KHÔNG cần ultralytics / PyTorch.

Keypoint ra theo thứ tự TL, TR, BR, BL của CHÍNH TÀI LIỆU (góc trên-trái của trang in),
không phải theo toạ độ ảnh. Nhờ vậy ảnh cắt ra tự đứng thẳng kể cả khi tài liệu đặt
xoay 90/180 độ.

Tiền/hậu xử lý làm giống hệt Ultralytics (letterbox nền 114, NMS IoU 0.7) nên kết quả
khớp với `YOLO(weights).predict(...)`.

Output ONNX: (1, 4 + nc + nk*3, N) — xywh tâm, điểm lớp, rồi (x, y, conf) mỗi keypoint,
toạ độ theo ảnh đã letterbox.
"""
from __future__ import annotations

import ast
import os
import threading
import time

import cv2
import numpy as np

from .geometry import is_convex, order_clockwise, polygon_area


def auto_threads(n: int | None) -> int:
    """Số luồng cho ONNX Runtime. 0 = tự chọn: nửa số CPU logic, tối đa 8.

    Mặc định của ONNX Runtime là dùng HẾT nhân: trên máy nhiều nhân chi phí điều phối
    ăn hết thời gian (đo được chậm ~10 lần), nên luôn giới hạn.
    """
    n = int(n or 0)
    if n > 0:
        return n
    return max(1, min(8, (os.cpu_count() or 2) // 2))


class YoloPoseDocumentDetector:
    def __init__(self, weights: str, imgsz: int = 960, conf: float = 0.25, iou: float = 0.7,
                 min_area_frac: float = 0.002, onnx_threads: int = 0, providers=None):
        if not os.path.exists(weights):
            raise FileNotFoundError("Không thấy file model YOLO: %s" % weights)
        import onnxruntime as ort

        t0 = time.time()
        so = ort.SessionOptions()
        self.onnx_threads = auto_threads(onnx_threads)
        so.intra_op_num_threads = self.onnx_threads
        so.inter_op_num_threads = 1
        self.session = ort.InferenceSession(weights, so, providers=providers or ["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.weights = weights
        self.conf = float(conf)
        self.iou = float(iou)
        self.min_area_frac = float(min_area_frac)

        meta = self.session.get_modelmeta().custom_metadata_map
        self.num_kpts = int(ast.literal_eval(meta.get("kpt_shape", "[4, 3]"))[0])
        self.num_classes = len(ast.literal_eval(meta.get("names", "{0: 'document'}")))

        # Model export không kèm dynamic=True có input cố định (vd 1x3x960x960).
        h, w = self.session.get_inputs()[0].shape[2:4]
        self.fixed_imgsz = max(h, w) if isinstance(h, int) and isinstance(w, int) else None
        self.imgsz = self.fixed_imgsz or int(imgsz)
        # Session không an toàn khi gọi đồng thời từ nhiều thread.
        self._lock = threading.Lock()
        self.load_ms = (time.time() - t0) * 1000

    def effective_imgsz(self, imgsz: int | None = None) -> int:
        """Cỡ ảnh thực sự đưa vào mạng: model có input cố định thì luôn là cỡ đó."""
        size = self.fixed_imgsz or int(imgsz or self.imgsz)
        return int(np.ceil(size / 32) * 32)

    def warmup(self, sizes=None) -> float:
        """Chạy thử một lần trên ảnh đen ở mỗi cỡ sẽ dùng, để request thật không phải chờ."""
        total = 0.0
        for size in sorted({self.effective_imgsz(s) for s in (sizes or (self.imgsz,))}):
            t0 = time.time()
            self.predict(np.zeros((size * 9 // 16, size, 3), np.uint8), imgsz=size)
            total += (time.time() - t0) * 1000
        return total

    # ---------- tiền / hậu xử lý kiểu Ultralytics ----------

    @staticmethod
    def _letterbox(bgr: np.ndarray, size: int):
        h, w = bgr.shape[:2]
        r = min(size / h, size / w)
        nw, nh = int(round(w * r)), int(round(h * r))
        dw, dh = (size - nw) / 2, (size - nh) / 2
        img = bgr if (w, h) == (nw, nh) else cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        blob = img[..., ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        return np.ascontiguousarray(blob), r, (left, top)

    def predict(self, bgr: np.ndarray, imgsz: int | None = None) -> list[tuple[np.ndarray, float]]:
        """Tất cả ứng viên sau NMS: list (quad (4, 2) float32 TL,TR,BR,BL, score)."""
        size = self.effective_imgsz(imgsz)
        blob, r, (padx, pady) = self._letterbox(bgr, size)
        with self._lock:
            out = self.session.run(None, {self.input_name: blob})[0][0].T   # (N, C)

        nc = self.num_classes
        scores = out[:, 4:4 + nc].max(1)
        keep = scores >= self.conf
        out, scores = out[keep], scores[keep]
        if len(out) == 0:
            return []

        boxes = out[:, :4].copy()                     # cx, cy, w, h -> x, y, w, h
        boxes[:, 0] -= boxes[:, 2] / 2
        boxes[:, 1] -= boxes[:, 3] / 2
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.conf, self.iou, top_k=300)
        idx = np.asarray(idx, int).reshape(-1)

        h, w = bgr.shape[:2]
        res = []
        for i in idx:
            k = out[i, 4 + nc:4 + nc + self.num_kpts * 3].reshape(self.num_kpts, 3)[:4, :2]
            quad = (k - np.float32([padx, pady])) / r
            quad[:, 0] = np.clip(quad[:, 0], 0, w)
            quad[:, 1] = np.clip(quad[:, 1], 0, h)
            res.append((quad.astype(np.float32), float(scores[i])))
        return res

    def detect(self, bgr: np.ndarray, imgsz: int | None = None) -> tuple[np.ndarray | None, float]:
        """Tài liệu tốt nhất trong ảnh -> (quad, score) hoặc (None, 0.0).

        Chọn theo score × diện tích thay vì chỉ score: khay chỉ có một tài liệu, mà độ
        tin cậy của trang bị che một phần có thể thấp hơn một phát hiện nhỏ linh tinh.
        """
        frame_area = float(bgr.shape[0] * bgr.shape[1])
        best, best_score, best_rank = None, 0.0, -1.0
        for quad, score in self.predict(bgr, imgsz):
            area = abs(polygon_area(quad))
            # Chỉ bỏ mảnh suy biến. Giữ ngưỡng NHỎ: thẻ CCCD trên khay chỉ ~1% khung.
            if area < self.min_area_frac * frame_area:
                continue
            rank = score * area
            if rank > best_rank:
                best, best_score, best_rank = quad, score, rank
        if best is None:
            return None, 0.0
        if not is_convex(best):
            best = order_clockwise(best)
        return best, best_score
