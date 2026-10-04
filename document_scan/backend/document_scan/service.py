"""Dịch vụ quét tài liệu: YOLO pose -> refine -> (tuỳ chọn) cắt / nắn phẳng.

Không phụ thuộc web framework nào — dùng trực tiếp được từ Flask, Django, script...
(router FastAPI có sẵn ở api.py).

    from document_scan import DocumentScanService
    svc = DocumentScanService()                     # nạp model + warm-up một lần
    result = svc.detect(bgr, mode="live")           # 4 góc (đã refine) cho khung live
    page, result = svc.scan(bgr)                    # ảnh tài liệu đã cắt + nắn phẳng
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from . import refine as quad_refine
from .config import DocScanConfig
from .detector import YoloPoseDocumentDetector
from .geometry import order_clockwise, resize_long_side, warp_quad

MODES = ("live", "capture")


class DocumentScanService:
    def __init__(self, config: DocScanConfig | None = None):
        self.config = cfg = config or DocScanConfig.load()
        self.detector = YoloPoseDocumentDetector(
            cfg.weights_path(),
            imgsz=cfg.imgsz,
            conf=cfg.conf,
            iou=cfg.iou,
            min_area_frac=cfg.min_area_frac,
            onnx_threads=cfg.onnx_threads,
        )
        self.imgsz_capture = self.detector.effective_imgsz(cfg.imgsz)
        self.imgsz_live = self.detector.effective_imgsz(cfg.imgsz_live or cfg.imgsz)
        self.warmup_ms = (self.detector.warmup(sorted({self.imgsz_live, self.imgsz_capture}))
                          if cfg.warmup else 0.0)
        # Model dùng chung -> mỗi lần một request (refine cũng nằm trong khoá cho gọn).
        self._lock = threading.Lock()

    # ---------- trạng thái ----------

    def status(self) -> dict:
        """Frontend hỏi cái này để biết gửi ảnh cỡ nào (imgsz / imgszLive)."""
        cfg = self.config
        return {
            "ready": True,
            "engine": "yolo-pose-onnx",
            "weights": self.detector.weights.replace("\\", "/").rsplit("/", 1)[-1],
            "imgsz": self.imgsz_capture,
            "imgszLive": self.imgsz_live,
            "fixedImgsz": self.detector.fixed_imgsz,
            "onnxThreads": self.detector.onnx_threads,
            "warmupMs": round(self.warmup_ms, 1),
            "refine": cfg.refine,
            "refineLive": cfg.refine_live,
        }

    # ---------- detect ----------

    def detect(self, bgr: np.ndarray, mode: str | None = None) -> dict:
        """4 góc tài liệu theo toạ độ của chính ảnh truyền vào.

        `mode` = "live" (khung trên màn hình) | "capture" (lúc bấm Chụp). Hai mode chỉ
        khác cỡ ảnh model và việc có refine hay không.

        Trả về:
            found      : có tài liệu không
            quad       : 4 góc CUỐI CÙNG (sau refine nếu refine thành công), thứ tự
                         TL, TR, BR, BL của chính tài liệu. Đây là khung để vẽ và để cắt.
            quadModel  : 4 góc thô của model (trước refine) — chỉ để gỡ lỗi.
            refine     : "refined" | lý do giữ góc model ("unchanged", "area_change"...)
                         | None khi không chạy refine.
            refined    : True nếu quad đã được kéo vào mép giấy.
            score, ms, mode, frame{width, height}, timing{...}
        """
        mode = mode if mode in MODES else "capture"
        cfg = self.config
        h, w = bgr.shape[:2]
        t_wait = time.perf_counter()
        with self._lock:
            t0 = time.perf_counter()
            small, s = resize_long_side(bgr, cfg.max_frame_side)
            imgsz = self.imgsz_live if mode == "live" else self.imgsz_capture
            quad, score = self.detector.detect(small, imgsz=imgsz)
            t_model = time.perf_counter()
            raw_quad, refine_status = quad, None
            do_refine = cfg.refine_live if mode == "live" else cfg.refine
            if quad is not None and do_refine:
                refined, info = quad_refine.refine_quad(small, quad)
                quad = np.asarray(refined, np.float32)
                refine_status = info["status"]
            t_end = time.perf_counter()

        base = {
            "found": quad is not None,
            "mode": mode,
            "frame": {"width": int(w), "height": int(h)},
            "ms": round((t_end - t0) * 1000, 1),
            "timing": {
                "waitMs": round((t0 - t_wait) * 1000, 1),
                "modelMs": round((t_model - t0) * 1000, 1),
                "refineMs": round((t_end - t_model) * 1000, 1),
                "processedSize": "%dx%d" % (small.shape[1], small.shape[0]),
            },
        }
        if quad is None:
            return base

        inv = np.float32(1.0 / s)
        return {
            **base,
            "quad": _points(np.asarray(quad, np.float32) * inv),
            "quadModel": _points(np.asarray(raw_quad, np.float32) * inv),
            "score": round(float(score), 3),
            "refine": refine_status,
            "refined": refine_status == "refined",
        }

    # ---------- cắt ảnh ở backend (tuỳ chọn; frontend cũng tự cắt được) ----------

    def scan(self, bgr: np.ndarray, orientation: str = "document",
             max_long_side: int | None = None) -> tuple[np.ndarray | None, dict]:
        """Detect (mode capture, có refine) rồi cắt + nắn phẳng ở ĐỘ PHÂN GIẢI GỐC.

        Trả (ảnh BGR đã cắt hoặc None, kết quả detect).
        """
        result = self.detect(bgr, mode="capture")
        if not result["found"]:
            return None, result
        quad = np.float32([[p["x"], p["y"]] for p in result["quad"]])
        page = crop_document(bgr, quad, orientation=orientation, max_long_side=max_long_side)
        return page, result


def crop_document(bgr: np.ndarray, quad, orientation: str = "document",
                  max_long_side: int | None = None) -> np.ndarray | None:
    """Nắn phẳng tài liệu theo 4 góc.

    orientation:
        "document" — giữ thứ tự góc của model (TL của trang in) -> ảnh tự đứng đúng chiều
                     kể cả khi tài liệu đặt xoay / lộn ngược.
        "portrait" — sắp góc theo hình học rồi ép khổ dọc (ngang thì xoay 90° chiều kim
                     đồng hồ) — giống hệt frontend kiosk cũ.
    """
    quad = np.asarray(quad, np.float32).reshape(4, 2)
    if orientation == "portrait":
        quad = order_clockwise(quad)
    page = warp_quad(bgr, quad)
    if page is None:
        return None
    if orientation == "portrait" and page.shape[1] > page.shape[0]:
        page = cv2.rotate(page, cv2.ROTATE_90_CLOCKWISE)
    if max_long_side:
        page, _ = resize_long_side(page, int(max_long_side))
    return page


def _points(quad: np.ndarray) -> list[dict]:
    return [{"x": float(x), "y": float(y)} for x, y in quad]
