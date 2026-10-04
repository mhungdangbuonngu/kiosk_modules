"""
Tinh chỉnh 4 góc YOLO cho khít mép giấy (hậu xử lý sau model).

Chép nguyên thuật toán từ dự án yolo_pose (src/refine.py), chỉ đổi dòng import hàm
hình học. Mọi bước đều có quyền phủ quyết: không chắc chắn thì giữ nguyên góc của
model, nên refine không bao giờ làm ảnh cắt tệ hơn model.

Bản gốc (docstring tiếng Anh) giữ nguyên ở dưới.
"""

# Snap a predicted document quad onto the page's real edges.
#
# The pose head gets the page to within a few tens of pixels on a 1920-wide
# frame; that is enough to find the document but leaves a visible sliver of
# background (or a cut-off margin) in the crop. Paper edges are straight, and the
# network has already said roughly where each one is, so this only has to look
# in a thin band around each predicted side:
#
#     1. Gradients come from whichever colour channel changes most at each pixel,
#        so a red cover on a blue mat has an edge even where their greys match.
#        Nothing here thresholds on colour or brightness.
#     2. Each side is probed by short segments perpendicular to it. On every
#        probe, only gradient pointing across the side counts — text, tables and
#        artwork inside the page are mostly at other angles or come in +/- pairs.
#     3. Of the strong peaks on a probe, the one *nearest the predicted side* is
#        taken, not the strongest: a page lying on another page has two parallel
#        edges, and the model has already told us which one it meant.
#     4. A robust line is fitted per side; adjacent sides are intersected.
#
# Every step can veto. A side that is not clearly a straight edge close to the
# prediction keeps the model's line, and a quad that changes too much is thrown
# away whole — refinement must never make a crop worse than the model alone.
# Curved pages, a page the same colour as the platen, or a quad that is wrong
# altogether (an open notebook labelled as one sheet) all fall through to the
# prediction unchanged.
#
#     from document_scan.refine import refine_quad
#     quad, info = refine_quad(frame, quad)      # (4, 2) TL, TR, BR, BL


from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import is_convex, polygon_area


@dataclass
class RefineParams:
    band_frac: float = 0.03        # search ± this fraction of the frame's short side
    n_probes: int = 40             # probes per side
    end_skip: float = 0.10         # ignore this much of each side at both ends
    blur_sigma: float = 1.0
    orient_deg: float = 20.0       # gradient must be within this of the side normal
    min_grad: float = 12.0         # absolute floor on |gradient| (Sobel 3x3, uint8)
    peak_rel: float = 0.5          # a peak counts if >= this * strongest on the probe
    pick: str = "nearest"          # "nearest" to the predicted side, or "strongest"
    inlier_px: float = 2.0         # line-fit inlier tolerance at 1080p, scaled
    min_inlier_frac: float = 0.55  # of n_probes
    max_angle_deg: float = 4.0     # refined side vs predicted side
    max_area_change: float = 0.10


SIDE_STATUS_OK = "ok"


def _gradients(image: np.ndarray, roi: tuple[int, int, int, int],
               sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel gradient of the channel with the largest magnitude, inside roi."""
    x0, y0, x1, y1 = roi
    patch = image[y0:y1, x0:x1]
    if patch.ndim == 2:
        patch = patch[..., None]
    patch = patch.astype(np.float32)
    if sigma > 0:
        patch = cv2.GaussianBlur(patch, (0, 0), sigma)
        if patch.ndim == 2:
            patch = patch[..., None]
    gx = np.stack([cv2.Sobel(patch[..., c], cv2.CV_32F, 1, 0, ksize=3)
                   for c in range(patch.shape[2])], axis=-1)
    gy = np.stack([cv2.Sobel(patch[..., c], cv2.CV_32F, 0, 1, ksize=3)
                   for c in range(patch.shape[2])], axis=-1)
    best = np.argmax(gx * gx + gy * gy, axis=-1)[..., None]
    return (np.take_along_axis(gx, best, axis=-1)[..., 0],
            np.take_along_axis(gy, best, axis=-1)[..., 0])


def _side_points(gx: np.ndarray, gy: np.ndarray, origin: np.ndarray,
                 p0: np.ndarray, p1: np.ndarray, band: float,
                 prm: RefineParams, dbg: dict | None = None) -> np.ndarray:
    """Edge points found across the side p0->p1, in roi coordinates. (k, 2).

    `dbg`, when given, is filled with the intermediate arrays (for src.viz_refine).
    """
    d = p1 - p0
    length = float(np.linalg.norm(d))
    if length < 1e-6:
        return np.empty((0, 2), np.float32)
    d /= length
    n = np.array([-d[1], d[0]])

    ts = np.linspace(prm.end_skip, 1.0 - prm.end_skip, prm.n_probes)
    ss = np.arange(-np.ceil(band), np.ceil(band) + 1.0)
    centres = (p0 - origin)[None, :] + ts[:, None] * length * d[None, :]
    pts = centres[:, None, :] + ss[None, :, None] * n[None, None, :]   # (P, S, 2)
    mx = pts[..., 0].astype(np.float32)
    my = pts[..., 1].astype(np.float32)
    sx = cv2.remap(gx, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    sy = cv2.remap(gy, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    across = sx * n[0] + sy * n[1]                       # signed, along the normal
    mag = np.sqrt(sx * sx + sy * sy) + 1e-6
    cos_ok = np.cos(np.deg2rad(prm.orient_deg))
    strength = np.where((np.abs(across) / mag >= cos_ok) & (mag >= prm.min_grad),
                        np.abs(across), 0.0)
    sign = np.sign(across)
    if dbg is not None:
        dbg.update(centres=centres + origin, normal=n, ss=ss, grid=pts + origin,
                   mag=np.sqrt(sx * sx + sy * sy), across=across, strength=strength,
                   peaks=[])

    found_s, found_sign, found_t = [], [], []
    for i in range(len(ts)):
        row = strength[i]
        top = row.max()
        if top <= 0:
            continue
        # local maxima above the relative floor
        inner = (row[1:-1] >= row[:-2]) & (row[1:-1] >= row[2:]) & \
                (row[1:-1] >= prm.peak_rel * top) & (row[1:-1] > 0)
        peaks = np.nonzero(inner)[0] + 1
        if dbg is not None:
            dbg["peaks"].append((i, peaks.copy()))
        if len(peaks) == 0:
            continue
        if prm.pick == "strongest":
            j = int(peaks[np.argmax(row[peaks])])
        else:
            j = int(peaks[np.argmin(np.abs(ss[peaks]))])
        # sub-pixel: parabola through the peak and its neighbours
        a, b, c = row[j - 1], row[j], row[j + 1]
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if abs(den) > 1e-6 else 0.0
        found_s.append(ss[j] + float(np.clip(off, -0.5, 0.5)))
        found_sign.append(sign[i, j])
        found_t.append(i)

    if not found_s:
        return np.empty((0, 2), np.float32)
    found_s = np.asarray(found_s)
    found_sign = np.asarray(found_sign)
    found_t = np.asarray(found_t)
    # A page boundary is one step with one polarity along its whole length;
    # keep the majority polarity and drop the rest.
    keep = found_sign == (1.0 if (found_sign > 0).sum() >= (found_sign < 0).sum() else -1.0)
    pts_out = centres[found_t[keep]] + found_s[keep][:, None] * n[None, :]
    if dbg is not None:
        dbg.update(chosen_t=found_t, chosen_s=found_s, polarity_kept=keep,
                   chosen_xy=centres[found_t] + found_s[:, None] * n[None, :] + origin)
    return pts_out.astype(np.float32)


def _fit_line(pts: np.ndarray, tol: float,
              dbg: dict | None = None) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Robust line through pts: (point, unit direction, inlier count)."""
    if len(pts) < 2:
        return None
    vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    d = np.array([vx, vy], np.float64)
    p = np.array([x0, y0], np.float64)
    nrm = np.array([-d[1], d[0]])
    resid = np.abs((pts - p) @ nrm)
    inl = pts[resid <= tol]
    if dbg is not None:
        dbg["inlier_mask"] = resid <= tol
    if len(inl) < 2:
        return None
    vx, vy, x0, y0 = cv2.fitLine(inl, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    return np.array([x0, y0], np.float64), np.array([vx, vy], np.float64), len(inl)


def _intersect(pa: np.ndarray, da: np.ndarray, pb: np.ndarray, db: np.ndarray):
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-9:
        return None
    t = ((pb[0] - pa[0]) * db[1] - (pb[1] - pa[1]) * db[0]) / den
    return pa + t * da


def refine_quad(image: np.ndarray, quad: np.ndarray, params: RefineParams | None = None,
                debug: dict | None = None) -> tuple[np.ndarray, dict]:
    """Return (refined quad, info). Falls back to the input quad whenever unsure.

    info["sides"] has one status per side (TL-TR, TR-BR, BR-BL, BL-TL):
    "ok" when it was moved onto a detected edge, otherwise why it was kept.
    info["status"] is "refined", "unchanged" or the reason the quad was rejected.
    Pass a dict as `debug` to collect every intermediate step (see src.viz_refine).
    """
    prm = params or RefineParams()
    quad = np.asarray(quad, np.float64).reshape(4, 2)
    h, w = image.shape[:2]
    short = float(min(h, w))
    band = prm.band_frac * short
    tol = prm.inlier_px * short / 1080.0

    pad = int(np.ceil(band)) + 4
    if np.ptp(quad[:, 0]) < 8 or np.ptp(quad[:, 1]) < 8:
        return quad, {"status": "too_small", "sides": ["skipped"] * 4}

    if debug is not None:
        debug.update(band=band, tol=tol, sides=[{} for _ in range(4)])
    lines, sides = [], []
    for i in range(4):
        p0, p1 = quad[i], quad[(i + 1) % 4]
        d_pred = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-9)
        model_line = (p0, d_pred)
        sd = debug["sides"][i] if debug is not None else None

        # Gradients only over this side's band: on a page filling the frame,
        # the whole-quad box would be most of the image.
        x0 = max(int(np.floor(min(p0[0], p1[0]))) - pad, 0)
        y0 = max(int(np.floor(min(p0[1], p1[1]))) - pad, 0)
        x1 = min(int(np.ceil(max(p0[0], p1[0]))) + pad, w)
        y1 = min(int(np.ceil(max(p0[1], p1[1]))) + pad, h)
        if x1 - x0 < 3 or y1 - y0 < 3:
            lines.append(model_line)
            sides.append("off_frame")
            continue
        gx, gy = _gradients(image, (x0, y0, x1, y1), prm.blur_sigma)
        origin = np.array([x0, y0], np.float64)

        if sd is not None:
            sd.update(roi=(x0, y0, x1, y1), grad_mag=np.sqrt(gx * gx + gy * gy))
        pts = _side_points(gx, gy, origin, p0, p1, band, prm, sd)
        fit = _fit_line(pts, tol, sd)
        if sd is not None:
            sd["points"] = pts + origin
            if fit is not None:
                sd["fit"] = (fit[0] + origin, fit[1], fit[2])
        if fit is None or fit[2] < prm.min_inlier_frac * prm.n_probes:
            lines.append(model_line)
            sides.append("few_edge_points")
            continue
        p_fit, d_fit, _ = fit
        p_fit = p_fit + origin
        cosang = abs(float(d_fit @ d_pred))
        if np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0))) > prm.max_angle_deg:
            lines.append(model_line)
            sides.append("angle")
            continue
        mid = 0.5 * (p0 + p1)
        shift = abs(float((mid - p_fit) @ np.array([-d_fit[1], d_fit[0]])))
        if shift > band:
            lines.append(model_line)
            sides.append("shift")
            continue
        if d_fit @ d_pred < 0:
            d_fit = -d_fit
        lines.append((p_fit, d_fit))
        sides.append(SIDE_STATUS_OK)

    info = {"sides": sides}
    if debug is not None:
        debug["lines"] = lines
    if SIDE_STATUS_OK not in sides:
        info["status"] = "unchanged"
        return quad, info

    out = np.empty_like(quad)
    for i in range(4):                      # corner i = side (i-1) ∩ side i
        prev_p, prev_d = lines[(i - 1) % 4]
        cur_p, cur_d = lines[i]
        c = _intersect(prev_p, prev_d, cur_p, cur_d)
        if c is None:
            info["status"] = "parallel_sides"
            return quad, info
        out[i] = c

    if not is_convex(out) or polygon_area(out) <= 0:
        info["status"] = "not_convex"
        return quad, info
    a0, a1 = abs(polygon_area(quad)), abs(polygon_area(out))
    if abs(a1 - a0) > prm.max_area_change * a0:
        info["status"] = "area_change"
        return quad, info
    if np.linalg.norm(out - quad, axis=1).max() > 2.0 * band:
        info["status"] = "corner_jump"
        return quad, info

    info["status"] = "refined"
    return out, info
