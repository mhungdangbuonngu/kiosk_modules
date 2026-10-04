"""Hàm hình học dùng chung cho detector, refine và cắt ảnh.

Quy ước: quad là mảng (4, 2) float32 theo thứ tự TL, TR, BR, BL.
"""
from __future__ import annotations

import cv2
import numpy as np

CORNER_NAMES = ("TL", "TR", "BR", "BL")


def polygon_area(quad: np.ndarray) -> float:
    """Diện tích có dấu (công thức shoelace). Âm = thứ tự ngược chiều."""
    x, y = quad[:, 0], quad[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def is_convex(quad: np.ndarray) -> bool:
    """Tứ giác lồi và không tự cắt (tích có hướng các cạnh liên tiếp cùng dấu)."""
    cross = []
    for i in range(4):
        a, b, c = quad[i], quad[(i + 1) % 4], quad[(i + 2) % 4]
        cross.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    cross = np.asarray(cross)
    return bool(np.all(cross > 0) or np.all(cross < 0))


def order_clockwise(quad: np.ndarray) -> np.ndarray:
    """Sắp lại 4 góc theo hình học: chiều kim đồng hồ, bắt đầu từ góc trên-trái ẢNH.

    Chỉ dùng khi model ra tứ giác hình nơ (bow-tie): lấy lại được đúng vùng nhưng
    mất thông tin chiều xoay của tài liệu.
    """
    d = quad - quad.mean(0)
    quad = quad[np.argsort(np.arctan2(d[:, 1], d[:, 0]))]
    return np.roll(quad, -int(np.argmin(quad.sum(1))), axis=0)


def resize_long_side(img: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    """Thu nhỏ để cạnh dài <= max_side (không phóng to). Trả (ảnh, hệ số thu nhỏ)."""
    h, w = img.shape[:2]
    s = max_side / float(max(h, w))
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA), s


def warp_quad(img: np.ndarray, quad: np.ndarray, min_side: int = 20) -> np.ndarray | None:
    """Nắn phẳng tứ giác về hình chữ nhật, GIỮ NGUYÊN thứ tự góc TL, TR, BR, BL đưa vào.

    Với góc của YOLO (thứ tự của chính tài liệu) ảnh ra tự đứng đúng chiều, kể cả khi
    tài liệu đặt xoay trên khay. Trả None nếu tứ giác quá nhỏ.
    """
    tl, tr, br, bl = np.asarray(quad, np.float32)
    w = int(round(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))))
    h = int(round(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))))
    if w < min_side or h < min_side:
        return None
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    M = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), dst)
    # CUBIC khớp với frontend (cropper.js): nét chữ hơn LINEAR.
    return cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_CUBIC)


def draw_quad(bgr: np.ndarray, quad: np.ndarray | None, score: float | None = None) -> np.ndarray:
    """Ảnh gỡ lỗi: quad đỏ + tên từng góc."""
    vis = bgr.copy()
    if quad is not None:
        pts = np.asarray(quad).astype(int)
        cv2.polylines(vis, [pts.reshape(-1, 1, 2)], True, (0, 0, 255), 2, cv2.LINE_AA)
        for name, (x, y) in zip(CORNER_NAMES, pts):
            cv2.circle(vis, (int(x), int(y)), 5, (0, 255, 255), -1, cv2.LINE_AA)
            cv2.putText(vis, name, (int(x) + 6, int(y) - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 2, cv2.LINE_AA)
        if score is not None:
            cv2.putText(vis, "%.2f" % score, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return vis
