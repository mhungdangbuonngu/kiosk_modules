// Hàm hình học dùng chung: điểm {x, y}, quad = 4 điểm.

export function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
}

export function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

/** Sắp 4 góc theo hình học: theo góc quanh tâm, bắt đầu từ góc có x+y nhỏ nhất (TL của ẢNH). */
export function orderPoints(points) {
    const center = points.reduce(
        (sum, p) => ({ x: sum.x + p.x / points.length, y: sum.y + p.y / points.length }),
        { x: 0, y: 0 },
    );
    const ordered = [...points].sort(
        (a, b) => Math.atan2(a.y - center.y, a.x - center.x) - Math.atan2(b.y - center.y, b.x - center.x),
    );
    const tl = ordered.reduce((best, p, i) => (p.x + p.y < ordered[best].x + ordered[best].y ? i : best), 0);
    return [...ordered.slice(tl), ...ordered.slice(0, tl)];
}

export function pointsToBox(points, maxW, maxH) {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const x = clamp(Math.min(...xs), 0, maxW);
    const y = clamp(Math.min(...ys), 0, maxH);
    const right = clamp(Math.max(...xs), 0, maxW);
    const bottom = clamp(Math.max(...ys), 0, maxH);
    return { x, y, w: right - x, h: bottom - y };
}

/** Nới hình chữ nhật thêm `amount` (tỉ lệ) mỗi phía, kẹp trong khung, làm tròn ra ngoài. */
export function expandRect(box, amount, maxW, maxH) {
    const padX = box.w * amount;
    const padY = box.h * amount;
    const x = Math.max(0, Math.floor(box.x - padX));
    const y = Math.max(0, Math.floor(box.y - padY));
    const right = Math.min(maxW, Math.ceil(box.x + box.w + padX));
    const bottom = Math.min(maxH, Math.ceil(box.y + box.h + padY));
    return { x, y, w: Math.max(1, right - x), h: Math.max(1, bottom - y) };
}

export function scalePoints(points, sx, sy) {
    return points.map((p) => ({ x: p.x * sx, y: p.y * sy }));
}

/**
 * Toạ độ trong khung W×H -> toạ độ sau khi xoay cả khung `deg` độ (0, 90, -90/270, 180;
 * dương = chiều kim đồng hồ). Trả {points, width, height} của khung đã xoay.
 */
export function rotatePoints(points, deg, W, H) {
    const d = ((deg % 360) + 360) % 360;
    if (d === 0) return { points: points.map((p) => ({ ...p })), width: W, height: H };
    if (d === 90) return { points: points.map((p) => ({ x: H - p.y, y: p.x })), width: H, height: W };
    if (d === 270) return { points: points.map((p) => ({ x: p.y, y: W - p.x })), width: H, height: W };
    if (d === 180) return { points: points.map((p) => ({ x: W - p.x, y: H - p.y })), width: W, height: H };
    throw new Error(`captureRotation chỉ nhận 0, 90, -90, 180 (đang là ${deg})`);
}

export function canvasToBlob(canvas, type = 'image/jpeg', quality = 0.92) {
    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Không nén được ảnh'))), type, quality);
    });
}

/** Thu nhỏ canvas để cạnh dài <= maxLongSide (không phóng to). */
export function resizeCanvasToLongSide(source, maxLongSide) {
    const long = Math.max(source.width, source.height);
    if (!maxLongSide || long <= maxLongSide) return source;
    const s = maxLongSide / long;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(source.width * s));
    canvas.height = Math.max(1, Math.round(source.height * s));
    canvas.getContext('2d', { alpha: false }).drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
}

/** Canvas thu nhỏ theo chiều rộng tối đa (ảnh xem trước / thumbnail). */
export function resizeCanvasToWidth(source, maxWidth) {
    const s = Math.min(1, maxWidth / source.width);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(source.width * s));
    canvas.height = Math.max(1, Math.round(source.height * s));
    canvas.getContext('2d', { alpha: false }).drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
}

// ---------- map toạ độ khung video gốc -> canvas overlay trên màn hình ----------
// Tự đọc CSS của <video>: object-fit (contain/cover/fill) và transform xoay 90° (nếu
// video được xoay bằng CSS để hiển thị dọc). Overlay phải phủ cùng vùng với khung chứa video.

export function getFrameToOverlayMetrics(frameW, frameH, overlayW, overlayH, video, overlay) {
    const objectFit = video ? window.getComputedStyle(video).objectFit : 'fill';
    const rotation = getQuarterTurnRotation(video);

    if (rotation) {
        const videoRect = video.getBoundingClientRect();
        const anchorRect = (overlay || video.parentElement).getBoundingClientRect();
        const drawnWidth = videoRect.width || overlayW;
        const drawnHeight = videoRect.height || overlayH;
        const preW = drawnHeight;   // kích thước phần tử TRƯỚC khi xoay
        const preH = drawnWidth;
        const scale = objectFit === 'cover'
            ? Math.max(preW / frameW, preH / frameH)
            : Math.min(preW / frameW, preH / frameH);
        return {
            rotation,
            scale,
            offsetX: videoRect.left - anchorRect.left,
            offsetY: videoRect.top - anchorRect.top,
            padX: (preW - frameW * scale) / 2,
            padY: (preH - frameH * scale) / 2,
            drawnWidth,
            drawnHeight,
        };
    }

    // Không xoay: tính theo đúng hình chữ nhật của <video> so với overlay (overlay có thể
    // to hơn video, vd phủ cả khung chứa).
    if (video && overlay) {
        const v = video.getBoundingClientRect();
        const o = overlay.getBoundingClientRect();
        if (v.width && v.height) {
            return metricsForRect(frameW, frameH, v.width, v.height, objectFit, v.left - o.left, v.top - o.top);
        }
    }
    return metricsForRect(frameW, frameH, overlayW, overlayH, objectFit, 0, 0);
}

function metricsForRect(frameW, frameH, w, h, objectFit, ox, oy) {
    let scaleX = w / frameW;
    let scaleY = h / frameH;
    let offsetX = ox;
    let offsetY = oy;
    if (objectFit === 'contain' || objectFit === 'cover') {
        const s = objectFit === 'contain' ? Math.min(scaleX, scaleY) : Math.max(scaleX, scaleY);
        scaleX = s;
        scaleY = s;
        offsetX += (w - frameW * s) / 2;
        offsetY += (h - frameH * s) / 2;
    }
    return { scaleX, scaleY, offsetX, offsetY };
}

function getQuarterTurnRotation(video) {
    if (!video) return null;
    const transform = window.getComputedStyle(video).transform;
    if (!transform || transform === 'none') return null;
    const match = transform.match(/matrix\(([^)]+)\)/);
    if (!match) return null;
    const [a, b, c, d] = match[1].split(',').slice(0, 4).map((v) => Number.parseFloat(v.trim()));
    const n = Math.hypot(a, b) || 1;   // bỏ ảnh hưởng của scale()
    if (Math.abs(a / n) < 0.01 && Math.abs(d / n) < 0.01 && b / n > 0.9 && c / n < -0.9) return 'cw';
    if (Math.abs(a / n) < 0.01 && Math.abs(d / n) < 0.01 && b / n < -0.9 && c / n > 0.9) return 'ccw';
    return null;
}

export function mapFramePoint(p, m) {
    if (m.rotation === 'cw') {
        const x = p.x * m.scale + m.padX;
        const y = p.y * m.scale + m.padY;
        return { x: m.offsetX + m.drawnWidth - y, y: m.offsetY + x };
    }
    if (m.rotation === 'ccw') {
        const x = p.x * m.scale + m.padX;
        const y = p.y * m.scale + m.padY;
        return { x: m.offsetX + y, y: m.offsetY + m.drawnHeight - x };
    }
    return { x: p.x * m.scaleX + m.offsetX, y: p.y * m.scaleY + m.offsetY };
}
