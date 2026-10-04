// Cắt + nắn phẳng tài liệu ở trình duyệt bằng OpenCV.js. Các bước giống kiosk:
//   1. xoay khung hình (captureRotation) và chỉ chép VÙNG QUANH tài liệu (nới cropRoiPadding)
//   2. warpPerspective theo 4 góc (INTER_CUBIC)
//   3. orientation 'portrait': ảnh ngang -> xoay 90° cho thành dọc
//      orientation 'document': giữ thứ tự góc của model -> ảnh tự đứng đúng chiều trang in
//   4. thu nhỏ cạnh dài <= outputMaxLongSide, nén JPEG
import {
    distance, expandRect, orderPoints, pointsToBox, rotatePoints,
} from './geometry.js';

let openCvPromise = null;

/**
 * Chờ OpenCV.js sẵn sàng. Nếu trang chưa nhúng thì tự chèn <script src=opencvUrl>.
 * Mặc định lấy opencv.js nằm cạnh file này (chạy offline được).
 */
export function loadOpenCv(opencvUrl = new URL('./opencv.js', import.meta.url).href, timeoutMs = 30000) {
    // Resolve true chứ KHÔNG resolve window.cv: object cv của Emscripten có .then() nên
    // Promise sẽ "nuốt" nó như thenable và treo vĩnh viễn.
    if (window.cv?.Mat && window.cv?.imread) return Promise.resolve(true);
    if (openCvPromise) return openCvPromise;

    openCvPromise = new Promise((resolve, reject) => {
        const hasScript = [...document.scripts].some((s) => /opencv(\.min)?\.js/.test(s.src));
        if (!hasScript && opencvUrl) {
            const script = document.createElement('script');
            script.src = opencvUrl;
            script.async = true;
            script.onerror = () => reject(new Error(`Không tải được OpenCV.js: ${opencvUrl}`));
            document.head.appendChild(script);
        }
        const started = performance.now();
        const timer = window.setInterval(() => {
            // Bản build có thể trả cv là Promise / chưa xong runtime -> chờ tới khi có Mat.
            if (window.cv?.Mat && window.cv?.imread) {
                window.clearInterval(timer);
                resolve(true);
            } else if (performance.now() - started > timeoutMs) {
                window.clearInterval(timer);
                reject(new Error('OpenCV.js tải quá lâu'));
            }
        }, 100);
    });
    openCvPromise.catch(() => { openCvPromise = null; });
    return openCvPromise;
}

/**
 * Bước 1: từ khung hình gốc (`source`: <video> hoặc canvas) -> canvas nhỏ chỉ chứa vùng
 * quanh tài liệu, đã xoay `rotationDeg`, kèm 4 góc theo toạ độ canvas đó.
 *
 * `corners` theo toạ độ khung gốc, thứ tự TL,TR,BR,BL của tài liệu (như backend trả).
 */
export function prepareCropRegion(source, corners, { rotationDeg = 0, padding = 0.12, orientation = 'portrait' } = {}) {
    const sw = source.videoWidth || source.width;
    const sh = source.videoHeight || source.height;
    const rotated = rotatePoints(corners, rotationDeg, sw, sh);
    const tw = rotated.width;
    const th = rotated.height;
    // 'portrait' sắp lại theo hình học như kiosk cũ; 'document' giữ thứ tự của model.
    const pts = orientation === 'document' ? rotated.points : orderPoints(rotated.points);
    const roi = expandRect(pointsToBox(pts, tw, th), padding, tw, th);

    const canvas = document.createElement('canvas');
    canvas.width = roi.w;
    canvas.height = roi.h;
    const ctx = canvas.getContext('2d', { alpha: false });
    ctx.save();
    ctx.translate(-roi.x, -roi.y);
    ctx.translate(tw / 2, th / 2);
    ctx.rotate((rotationDeg * Math.PI) / 180);
    ctx.drawImage(source, -sw / 2, -sh / 2, sw, sh);
    ctx.restore();

    return {
        canvas,
        corners: pts.map((p) => ({ x: p.x - roi.x, y: p.y - roi.y })),
        roi,
    };
}

/**
 * Bước 2 + 3: nắn phẳng `canvas` theo 4 góc (toạ độ trong canvas đó). Trả canvas mới.
 */
export async function warpCanvas(canvas, corners, { orientation = 'portrait' } = {}) {
    await loadOpenCv(null);
    const { cv } = window;
    const src = cv.imread(canvas);
    const warped = warpDocument(cv, src, orientation === 'document' ? corners : orderPoints(corners));
    let out = warped;
    if (orientation !== 'document' && warped.cols > warped.rows) {
        out = new cv.Mat();
        cv.rotate(warped, out, cv.ROTATE_90_CLOCKWISE);
        warped.delete();
    }
    const result = document.createElement('canvas');
    cv.imshow(result, out);
    src.delete();
    out.delete();
    return result;
}

/** warpPerspective GIỮ thứ tự góc đưa vào (TL, TR, BR, BL). Không chỉnh sáng / làm nét. */
function warpDocument(cv, src, [tl, tr, br, bl]) {
    const width = Math.max(1, Math.round(Math.max(distance(br, bl), distance(tr, tl))));
    const height = Math.max(1, Math.round(Math.max(distance(tr, br), distance(tl, bl))));
    const dst = new cv.Mat();
    const srcTri = cv.matFromArray(4, 1, cv.CV_32FC2, [tl.x, tl.y, tr.x, tr.y, br.x, br.y, bl.x, bl.y]);
    const dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, width - 1, 0, width - 1, height - 1, 0, height - 1]);
    const matrix = cv.getPerspectiveTransform(srcTri, dstTri);
    // CUBIC: nét chữ hơn LINEAR ~41%; LANCZOS4 chậm gấp 3 mà chỉ hơn chút ít.
    cv.warpPerspective(src, dst, matrix, new cv.Size(width, height), cv.INTER_CUBIC, cv.BORDER_CONSTANT);
    srcTri.delete();
    dstTri.delete();
    matrix.delete();
    return dst;
}
