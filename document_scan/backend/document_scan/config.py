"""Cấu hình module document scan.

Thứ tự ưu tiên (sau ghi đè trước):
    1. giá trị mặc định trong DocScanConfig
    2. file JSON (DocScanConfig.load("đường/dẫn.json") hoặc biến môi trường DOCSCAN_CONFIG)
    3. biến môi trường DOCSCAN_* (xem ENV_KEYS)

Đường dẫn tương đối (vd `weights`) tính từ thư mục `backend/` của module — tức thư mục
chứa package `document_scan` — chứ KHÔNG phụ thuộc thư mục đang đứng khi chạy. Nhờ vậy
chép cả thư mục sang máy khác là chạy được.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

# .../backend/document_scan/config.py -> .../backend
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WEIGHTS = os.path.join("models", "docscan.onnx")


@dataclass
class DocScanConfig:
    # File model YOLO pose (.onnx). Tương đối = tính từ thư mục backend/ của module.
    weights: str = DEFAULT_WEIGHTS
    # Cỡ ảnh đưa vào mạng. Model kèm theo có input cố định 960 nên 2 giá trị này bị bỏ qua.
    imgsz: int = 960
    imgsz_live: int = 640
    # Độ tin cậy tối thiểu, ngưỡng IoU của NMS.
    conf: float = 0.25
    iou: float = 0.7
    # Bỏ tứ giác nhỏ hơn tỉ lệ này của khung (chỉ loại mảnh suy biến; thẻ CCCD ~1% khung).
    min_area_frac: float = 0.002
    # Số luồng ONNX Runtime. 0 = tự chọn (nửa số CPU logic, tối đa 8). Đừng để mặc định
    # của ONNX Runtime (dùng hết nhân): máy nhiều nhân chậm gấp ~10 lần.
    onnx_threads: int = 0
    # Hậu xử lý refine: kéo 4 cạnh của model vào mép giấy thật (~10-20ms/ảnh).
    # Frontend vẽ khung bằng quad SAU refine nên mặc định bật cho cả live.
    refine: bool = True
    refine_live: bool = True
    # Frame lớn hơn cỡ này bị thu nhỏ trước khi detect (YOLO tự letterbox về imgsz
    # nên không mất độ chính xác, chỉ đỡ tốn RAM / thời gian refine).
    max_frame_side: int = 1280
    # Chạy thử model lúc khởi tạo để request đầu tiên không phải chờ.
    warmup: bool = True

    def weights_path(self) -> str:
        return resolve_path(self.weights)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | None = None, **overrides) -> "DocScanConfig":
        """Mặc định <- file JSON (nếu có) <- biến môi trường DOCSCAN_* <- overrides."""
        cfg = cls()
        path = path or os.environ.get("DOCSCAN_CONFIG")
        if path:
            with open(resolve_path(path), "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        cfg.update_from_env()
        cfg.update(overrides)
        return cfg

    def update(self, values: dict) -> None:
        """Nhận cả khoá snake_case lẫn camelCase (imgszLive, minAreaFrac...). Bỏ khoá lạ / '_ghiChu'."""
        known = {f.name: f for f in fields(self)}
        for key, value in (values or {}).items():
            name = _snake(key)
            if name in known and value is not None:
                setattr(self, name, _cast(known[name].type, value))

    def update_from_env(self) -> None:
        for f in fields(self):
            raw = os.environ.get("DOCSCAN_" + f.name.upper())
            if raw is not None and raw != "":
                setattr(self, f.name, _cast(f.type, raw))


def resolve_path(path: str) -> str:
    """Đường dẫn tương đối -> tuyệt đối, tính từ thư mục backend/ của module."""
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(BACKEND_DIR, path))


def _snake(key: str) -> str:
    out = []
    for ch in key:
        if ch.isupper():
            out.append("_" + ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _cast(type_name, value):
    t = type_name if isinstance(type_name, str) else getattr(type_name, "__name__", "")
    if t == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if t == "int":
        return int(value)
    if t == "float":
        return float(value)
    return str(value)
