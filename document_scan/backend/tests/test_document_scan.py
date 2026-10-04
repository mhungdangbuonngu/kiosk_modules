"""Kiểm tra nhanh module: nạp model, detect ảnh trống / ảnh có tài liệu, cắt ảnh, config.

    cd document_scan/backend
    python -m pytest tests -q
    DOCSCAN_TEST_IMAGES="/đường/dẫn/*.png" python -m pytest tests -q   # thêm ảnh thật
"""
import glob
import os
import sys

import cv2
import numpy as np
import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from document_scan import DocScanConfig, DocumentScanService, crop_document  # noqa: E402


@pytest.fixture(scope="module")
def svc():
    return DocumentScanService(DocScanConfig.load(onnx_threads=4))


def synthetic_page():
    """Tờ giấy trắng có chữ, đặt nghiêng trên nền tối — đủ để model nhận ra."""
    img = np.full((1080, 1920, 3), (60, 45, 40), np.uint8)
    page = np.full((1100, 800, 3), 245, np.uint8)
    for y in range(80, 1000, 40):
        cv2.putText(page, "CONG HOA XA HOI CHU NGHIA VIET NAM", (50, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    src = np.float32([[0, 0], [799, 0], [799, 1099], [0, 1099]])
    dst = np.float32([[640, 120], [1290, 160], [1250, 1000], [590, 960]])
    M = cv2.getPerspectiveTransform(src, dst)
    cv2.warpPerspective(page, M, (1920, 1080), img, borderMode=cv2.BORDER_TRANSPARENT)
    return img, dst


def test_weights_path_is_relative_to_module():
    cfg = DocScanConfig()
    assert cfg.weights_path() == os.path.join(BACKEND, "models", "docscan.onnx")
    assert os.path.exists(cfg.weights_path())


def test_config_camelcase_and_env(monkeypatch):
    monkeypatch.setenv("DOCSCAN_REFINE_LIVE", "false")
    cfg = DocScanConfig.load(conf=0.4)
    cfg.update({"imgszLive": 512, "_ghiChu": "bỏ qua"})
    assert cfg.refine_live is False and cfg.conf == 0.4 and cfg.imgsz_live == 512


def test_status(svc):
    s = svc.status()
    assert s["ready"] and s["imgsz"] == 960 and s["refineLive"] is True


def test_empty_frame(svc):
    r = svc.detect(np.zeros((540, 960, 3), np.uint8), mode="live")
    assert r["found"] is False


def test_synthetic_page_detect_and_crop(svc):
    img, truth = synthetic_page()
    r = svc.detect(img, mode="live")
    assert r["found"], r
    quad = np.float32([[p["x"], p["y"]] for p in r["quad"]])
    # Khung trả về (sau refine) nằm sát tờ giấy thật.
    err = min(np.abs(np.roll(quad, k, 0) - truth).max() for k in range(4))
    assert err < 40, (quad, err)
    assert {"quadModel", "refine", "refined"} <= set(r)

    page, res = svc.scan(img, orientation="portrait")
    assert page is not None and page.shape[0] > page.shape[1] > 400
    assert crop_document(img, quad, orientation="document", max_long_side=500).shape[:2][0] <= 500


@pytest.mark.parametrize("path", sorted(glob.glob(os.environ.get("DOCSCAN_TEST_IMAGES", "")))[:20]
                         if os.environ.get("DOCSCAN_TEST_IMAGES") else [])
def test_real_images(svc, path):
    img = cv2.imread(path)
    r = svc.detect(img, mode="capture")
    assert r["found"], path
