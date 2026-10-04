"""Module quét tài liệu: YOLO pose (ONNX) tìm 4 góc + refine kéo vào mép giấy + cắt / nắn phẳng.

    from document_scan import DocumentScanService, DocScanConfig
    svc = DocumentScanService(DocScanConfig.load(onnx_threads=4))
    result = svc.detect(bgr, mode="live")

Gắn vào FastAPI: xem document_scan.api.create_router.
"""
from .config import DocScanConfig
from .geometry import warp_quad
from .service import DocumentScanService, crop_document

__all__ = ["DocScanConfig", "DocumentScanService", "crop_document", "warp_quad"]
