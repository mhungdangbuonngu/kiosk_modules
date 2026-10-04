"""Router FastAPI cho module document scan — gắn vào app có sẵn bằng một dòng:

    from document_scan.api import create_router
    app.include_router(create_router())                # prefix mặc định /api/docscan

Endpoint (prefix mặc định /api/docscan):
    GET  /status   model đã sẵn sàng chưa + cỡ ảnh model nhìn (frontend hỏi lần đầu)
    POST /detect   multipart: file (ảnh), mode=live|capture -> JSON 4 góc (đã refine)
    POST /scan     multipart: file (ảnh gốc), orientation, maxLongSide, quality
                   -> image/jpeg tài liệu đã cắt + nắn phẳng (cắt hoàn toàn ở backend)
"""
import asyncio
import json
import threading
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from .config import DocScanConfig
from .service import DocumentScanService

_service: Optional[DocumentScanService] = None
_service_lock = threading.Lock()


def get_service(config: Optional[DocScanConfig] = None) -> DocumentScanService:
    """Service dùng chung cho cả process (nạp model một lần)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = DocumentScanService(config)
        return _service


def create_router(prefix: str = "/api/docscan", config: Optional[DocScanConfig] = None,
                  preload: bool = True):
    """APIRouter của module. `preload` = nạp model + warm-up lúc app khởi động."""
    router = APIRouter(prefix=prefix, tags=["document-scan"])

    if preload:
        # Nạp ở thread nền ngay lúc tạo router (không phụ thuộc lifespan/on_event của app
        # chủ). Request đến sớm hơn thì get_service() chờ cùng một khoá, không nạp hai lần.
        threading.Thread(target=get_service, args=(config,), name="docscan-preload",
                         daemon=True).start()

    async def _read_bgr(file: UploadFile) -> np.ndarray:
        data = await file.read()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Không đọc được ảnh gửi lên")
        return img

    @router.get("/status")
    async def status():
        return (await asyncio.to_thread(get_service, config)).status()

    @router.post("/detect")
    async def detect(file: UploadFile = File(...), mode: Optional[str] = Form(None)):
        img = await _read_bgr(file)
        svc = await asyncio.to_thread(get_service, config)
        return await asyncio.to_thread(svc.detect, img, mode)

    @router.post("/scan")
    async def scan(file: UploadFile = File(...),
                   orientation: str = Form("document"),
                   maxLongSide: Optional[int] = Form(None),
                   quality: int = Form(95)):
        img = await _read_bgr(file)
        svc = await asyncio.to_thread(get_service, config)
        page, result = await asyncio.to_thread(svc.scan, img, orientation, maxLongSide)
        if page is None:
            raise HTTPException(status_code=404, detail="Không phát hiện tài liệu")
        ok, buf = cv2.imencode(".jpg", page, [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))])
        if not ok:
            raise HTTPException(status_code=500, detail="Không nén được ảnh")
        headers = {
            # Kết quả detect đi kèm trong header (JSON) để frontend biết quad đã dùng.
            "X-DocScan-Result": json.dumps({k: result[k] for k in ("quad", "score", "refine", "refined")}),
            "Access-Control-Expose-Headers": "X-DocScan-Result",
        }
        return Response(content=buf.tobytes(), media_type="image/jpeg", headers=headers)

    return router
