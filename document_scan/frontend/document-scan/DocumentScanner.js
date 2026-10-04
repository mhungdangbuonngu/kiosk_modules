// DocumentScanner — nhận diện tài liệu trên video (YOLO pose ở backend), vẽ khung live,
// và chụp: đóng băng khung hình -> detect lại -> cắt + nắn phẳng -> JPEG.
//
// KHUNG VẼ TRÊN MÀN HÌNH LUÔN LÀ QUAD SAU REFINE (backend trả `quad` = góc đã kéo vào mép
// giấy thật; góc thô của model nằm ở `quadModel` và KHÔNG được vẽ). Đây cũng chính là
// quad dùng để cắt, nên khung người dùng thấy = vùng sẽ được cắt.
//
//   const scanner = new DocumentScanner({ video, overlay, apiBase: '/api/docscan' });
//   await scanner.init();
//   scanner.start();
//   const shot = await scanner.capture();      // { blob, canvas, width, height, ... } | null
import { canvasToBlob, distance, getFrameToOverlayMetrics, mapFramePoint, orderPoints,
    resizeCanvasToLongSide, resizeCanvasToWidth, scalePoints } from './geometry.js';
import { loadOpenCv, prepareCropRegion, warpCanvas } from './cropper.js';

export const DEFAULT_OPTIONS = {
    // Prefix API backend (document_scan.api.create_router). Có thể là URL tuyệt đối.
    apiBase: '/api/docscan',
    // Thêm vào mọi fetch (vd headers xác thực): { headers: { Authorization: '...' } }
    fetchOptions: {},
    // OpenCV.js: mặc định file opencv.js cạnh module. Đặt null nếu trang đã tự nhúng.
    opencvUrl: new URL('./opencv.js', import.meta.url).href,

    // ===== Vòng detect LIVE (khung trên màn hình) =====
    detectionIntervalMs: 380,
    live: {
        maxDim: 640,              // dự phòng; thực tế dùng imgszLive backend báo qua /status
        jpegQuality: 0.7,
        // Không gửi khi khung hình đứng yên: so ảnh xám rộng 64px với frame gửi lần trước.
        staticThumbWidth: 64,
        staticDiffThreshold: 3,   // chênh lệch TB (0-255) dưới mức này = đứng yên
        staticMaxSkipMs: 1500,    // đứng yên lâu vậy vẫn gửi lại một lần cho chắc
    },

    // ===== Lúc bấm Chụp: detect lại trên chính khung vừa đóng băng =====
    capture: {
        maxDim: 960,              // dự phòng; thực tế dùng imgsz backend báo qua /status
        jpegQuality: 0.9,
        liveFallbackMaxAgeMs: 800,   // detect lúc chụp hụt thì dùng quad live nếu còn mới hơn
    },

    // ===== Khung vẽ trên overlay (tên `box` để không trùng tham số `overlay` = canvas) =====
    box: {
        smoothingMs: 150,         // khung trượt tới vị trí mới thay vì nhảy cóc
        holdMs: 700,              // hụt một lần detect: mờ dần chừng này rồi mới xoá
        stableTolerance: 0.015,   // "đứng yên" = mọi góc lệch < tỉ lệ này của cạnh dài khung
        stableCount: 3,           // ... qua chừng này lần detect liên tiếp
        // true = CHỈ hiện khung khi refine thành công (backend refined=true); lần nào refine
        // phải giữ góc model thì coi như không thấy. false = luôn vẽ quad cuối cùng backend trả.
        requireRefined: false,
        showScore: true,
        colorMoving: '#f5c542',
        colorStable: '#47d7ac',
    },

    // ===== Cắt ảnh =====
    crop: {
        // Xoay khung hình trước khi cắt: 0 | 90 | -90 | 180 (dương = chiều kim đồng hồ).
        // Kiosk gốc (camera nằm ngang, hiển thị dọc) dùng -90.
        captureRotation: 0,
        padding: 0.12,            // nới vùng chép quanh tài liệu (chỉ để cắt, không ảnh hưởng kết quả)
        // 'portrait': sắp góc theo hình học + ép khổ dọc (giống kiosk gốc).
        // 'document': giữ thứ tự góc TL,TR,BR,BL của chính trang in -> ảnh tự đứng đúng chiều.
        orientation: 'portrait',
        outputMaxLongSide: 2800,
        jpegQuality: 0.95,
        previewWidth: 420,        // ảnh xem trước (trước khi nắn phẳng xong)
        previewQuality: 0.72,
        thumbnailQuality: 0.74,
    },

    messages: {
        connecting: 'Đang kết nối máy chủ...',
        empty: 'Đưa tài liệu vào khay.',
        moving: 'Đã thấy tài liệu. Giữ yên giấy tờ...',
        stable: 'Sẵn sàng chụp.',
        error: 'Nhận diện tài liệu bị lỗi.',
    },

    statusEl: null,               // phần tử hiện thông báo trạng thái (tuỳ chọn)
    onStatus: null,               // (state, message) => {}  state: connecting|empty|moving|stable|error
    onDetection: null,            // (detection | null) => {} mỗi lần live có kết quả mới
};

export class DocumentScanner {
    /**
     * @param {object} options xem DEFAULT_OPTIONS; bắt buộc `video`, nên có `overlay` (canvas
     *   phủ lên video, CSS: position:absolute; inset:0; pointer-events:none).
     */
    constructor(options = {}) {
        this.opts = mergeDeep(DEFAULT_OPTIONS, options);
        this.video = options.video || null;
        this.overlay = options.overlay || null;

        this.backendReady = false;
        this.liveImgsz = null;
        this.captureImgsz = null;
        this.frameCanvas = document.createElement('canvas');
        this.frameCtx = this.frameCanvas.getContext('2d', { willReadFrequently: true });
        this.thumbCanvas = document.createElement('canvas');
        this.thumbCtx = this.thumbCanvas.getContext('2d', { willReadFrequently: true });

        this.liveRunning = false;
        this.liveBusy = false;
        this.liveFrameId = 0;
        this.lastLiveDetectAt = 0;
        this.lastLiveDetection = null;   // toạ độ video gốc
        this.lastLiveDetectedAt = 0;
        this.lastSentThumb = null;
        this.lastSentAt = 0;

        this.overlayTarget = null;
        this.overlayShown = null;
        this.overlayMissAt = null;
        this.overlayDirty = false;
        this.overlayPaintedSize = '';
        this.lastRenderAt = 0;
        this.stableHistory = [];
        this.isStable = false;
        this.state = null;
        this.capturing = false;
    }

    get api() {
        const base = this.opts.apiBase.replace(/\/+$/, '');
        return { status: `${base}/status`, detect: `${base}/detect` };
    }

    /** Tải OpenCV.js + hỏi backend. Gọi một lần trước start()/capture(). */
    async init() {
        // opencvUrl null = trang tự nhúng opencv.js, chỉ chờ nó sẵn sàng.
        await Promise.all([loadOpenCv(this.opts.opencvUrl), this.checkBackendStatus()]);
        return this;
    }

    // ------------------------------------------------------------------ live

    start(video = this.video, overlay = this.overlay) {
        if (!video) throw new Error('DocumentScanner.start: thiếu <video>');
        this.video = video;
        this.overlay = overlay;
        if (this.liveRunning) return;
        this.liveRunning = true;
        this.updateStatus();
        this.liveFrameId = window.requestAnimationFrame(() => this.liveLoop());
    }

    stop() {
        this.liveRunning = false;
        if (this.liveFrameId) window.cancelAnimationFrame(this.liveFrameId);
        this.liveFrameId = 0;
        this.lastLiveDetection = null;
        this.lastSentThumb = null;
        this.overlayTarget = null;
        this.overlayShown = null;
        this.overlayMissAt = null;
        this.stableHistory = [];
        this.isStable = false;
        this.clearOverlay();
    }

    /** Mỗi frame màn hình: vẽ khung (mượt); detect theo nhịp, không chờ request bay về. */
    liveLoop() {
        if (!this.liveRunning) return;
        const video = this.video;
        const now = performance.now();
        if (!this.liveBusy
            && now - this.lastLiveDetectAt >= this.opts.detectionIntervalMs
            && video?.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
            this.liveBusy = true;       // chỉ một request đang bay, không dồn hàng đợi
            this.lastLiveDetectAt = now;
            this.runLiveDetection(video, now).finally(() => { this.liveBusy = false; });
        }
        this.renderOverlay(now);
        this.liveFrameId = window.requestAnimationFrame(() => this.liveLoop());
    }

    async runLiveDetection(video, now) {
        try {
            if (!this.backendReady && !(await this.checkBackendStatus())) {
                this.setOverlayTarget(null, performance.now());
                return;
            }
            const maxDim = this.liveImgsz || this.opts.live.maxDim;
            drawScaled(video, this.frameCanvas, this.frameCtx, maxDim);
            if (this.isFrameStatic(now)) {
                // Cảnh không đổi so với frame gửi lần trước -> kết quả cũ vẫn đúng.
                if (this.lastLiveDetection) {
                    this.lastLiveDetectedAt = performance.now();
                    this.updateStability(this.overlayTarget?.corners);
                    this.updateStatus();
                }
                return;
            }

            const found = await this.detect(this.frameCanvas, 'live', this.opts.live.jpegQuality);
            if (!this.liveRunning) return;
            const t = performance.now();
            const det = found && (!this.opts.box.requireRefined || found.refined)
                ? scaleDetection(found, video.videoWidth / this.frameCanvas.width, video.videoHeight / this.frameCanvas.height)
                : null;
            this.lastLiveDetection = det;
            if (det) this.lastLiveDetectedAt = t;
            this.setOverlayTarget(det, t);
            this.opts.onDetection?.(det);
        } catch (error) {
            console.warn('[DocScan] live detection lỗi:', error);
            this.setOverlayTarget(null, performance.now());
            this.emitStatus('error');
        }
    }

    /**
     * Gửi một ảnh (canvas) lên backend. Trả detection theo toạ độ CHÍNH canvas đó, hoặc null.
     * detection = { corners (đã refine, thứ tự TL,TR,BR,BL của tài liệu), cornersModel,
     *               score, refine, refined, ms }
     */
    async detect(canvas, mode = 'capture', quality = 0.9) {
        if (!this.backendReady && !(await this.checkBackendStatus())) return null;
        const blob = await canvasToBlob(canvas, 'image/jpeg', quality);
        const form = new FormData();
        form.append('file', blob, 'frame.jpg');
        form.append('mode', mode);
        const res = await fetch(this.api.detect, { ...this.opts.fetchOptions, method: 'POST', body: form });
        if (!res.ok) {
            this.backendReady = false;   // vòng sau hỏi lại /status
            throw new Error(`Detect lỗi HTTP ${res.status}`);
        }
        const r = await res.json();
        if (!r.found) return null;
        return {
            corners: r.quad,
            cornersModel: r.quadModel || null,
            score: r.score ?? null,
            refine: r.refine ?? null,
            refined: r.refined === true,
            ms: r.ms,
            frame: { width: canvas.width, height: canvas.height },
        };
    }

    async checkBackendStatus() {
        try {
            const res = await fetch(this.api.status, this.opts.fetchOptions);
            if (!res.ok) return false;
            const s = await res.json();
            this.backendReady = s.ready === true;
            this.liveImgsz = s.imgszLive || null;
            this.captureImgsz = s.imgsz || null;
            return this.backendReady;
        } catch (error) {
            console.warn('[DocScan] Không hỏi được trạng thái backend:', error);
            return false;
        } finally {
            this.updateStatus();
        }
    }

    /** So ảnh xám 64px với frame ĐÃ GỬI lần trước (để xê dịch chậm vẫn cộng dồn và bị bắt). */
    isFrameStatic(now) {
        const cfg = this.opts.live;
        const w = cfg.staticThumbWidth;
        const h = Math.max(1, Math.round(w * this.frameCanvas.height / this.frameCanvas.width));
        if (this.thumbCanvas.width !== w) this.thumbCanvas.width = w;
        if (this.thumbCanvas.height !== h) this.thumbCanvas.height = h;
        this.thumbCtx.drawImage(this.frameCanvas, 0, 0, w, h);
        const rgba = this.thumbCtx.getImageData(0, 0, w, h).data;
        const gray = new Uint8Array(w * h);
        for (let i = 0; i < gray.length; i += 1) {
            gray[i] = (rgba[i * 4] * 77 + rgba[i * 4 + 1] * 150 + rgba[i * 4 + 2] * 29) >> 8;
        }
        const prev = this.lastSentThumb;
        let isStatic = false;
        if (prev && prev.length === gray.length && now - this.lastSentAt < cfg.staticMaxSkipMs) {
            let sum = 0;
            for (let i = 0; i < gray.length; i += 1) sum += Math.abs(gray[i] - prev[i]);
            isStatic = sum / gray.length < cfg.staticDiffThreshold;
        }
        if (!isStatic) {
            this.lastSentThumb = gray;
            this.lastSentAt = now;
        }
        return isStatic;
    }

    // ------------------------------------------------------------------ capture

    /**
     * Đóng băng khung hình NGAY lúc gọi, detect lại trên chính nó (không dùng quad live cũ —
     * giấy xê dịch là cắt lệch), rồi cắt + nắn phẳng.
     *
     * @param {object} [opts]
     * @param {(preview: {blob, canvas}) => void} [opts.onPreview] gọi ngay khi có ảnh xem
     *        trước (vùng quanh tài liệu, chưa nắn) — để UI hiện liền, không chờ bước nắn.
     * @returns {Promise<null | {blob, canvas, width, height, thumbnailBlob, detection, snapshot}>}
     *          null = không thấy tài liệu. `detection` theo toạ độ `snapshot` (khung gốc).
     */
    async capture({ onPreview } = {}) {
        if (this.capturing) return null;
        this.capturing = true;
        try {
            const video = this.video;
            if (!video?.videoWidth) throw new Error('Camera chưa sẵn sàng');
            const { snapshot, detection } = await this.detectForCapture(video);
            if (!detection) return null;
            return await this.cropFrom(snapshot, detection, { onPreview });
        } finally {
            this.capturing = false;
        }
    }

    /** Cắt tài liệu từ một ảnh bất kỳ (canvas/<video>/<img> đã vẽ vào canvas) theo detection. */
    async cropFrom(source, detection, { onPreview } = {}) {
        const c = this.opts.crop;
        const region = prepareCropRegion(source, detection.corners, {
            rotationDeg: c.captureRotation,
            padding: c.padding,
            orientation: c.orientation,
        });
        if (onPreview) {
            const pc = resizeCanvasToWidth(region.canvas, c.previewWidth);
            canvasToBlob(pc, 'image/jpeg', c.previewQuality)
                .then((blob) => onPreview({ blob, canvas: pc }))
                .catch((e) => console.warn('[DocScan] preview lỗi:', e));
        }
        await yieldToBrowser();
        const warped = await warpCanvas(region.canvas, region.corners, { orientation: c.orientation });
        const canvas = resizeCanvasToLongSide(warped, c.outputMaxLongSide);
        const [blob, thumbnailBlob] = await Promise.all([
            canvasToBlob(canvas, 'image/jpeg', c.jpegQuality),
            canvasToBlob(resizeCanvasToWidth(canvas, c.previewWidth), 'image/jpeg', c.thumbnailQuality),
        ]);
        return { blob, canvas, width: canvas.width, height: canvas.height, thumbnailBlob, detection, snapshot: source };
    }

    /** {snapshot: canvas full-res (chưa xoay), detection theo toạ độ snapshot | null}. */
    async detectForCapture(video = this.video) {
        const cfg = this.opts.capture;
        const snapshot = document.createElement('canvas');
        snapshot.width = video.videoWidth;
        snapshot.height = video.videoHeight;
        snapshot.getContext('2d', { alpha: false }).drawImage(video, 0, 0);

        let detection = null;
        try {
            // Model chỉ nhìn ở imgsz -> gửi đúng cỡ đó, gửi 4K chỉ tốn đường truyền.
            const small = document.createElement('canvas');
            drawScaled(snapshot, small, small.getContext('2d', { alpha: false }), this.captureImgsz || cfg.maxDim);
            const found = await this.detect(small, 'capture', cfg.jpegQuality);
            if (found) detection = scaleDetection(found, snapshot.width / small.width, snapshot.height / small.height);
        } catch (error) {
            console.warn('[DocScan] detect lúc chụp lỗi, thử dùng quad live:', error);
        }
        if (!detection && this.lastLiveDetection
            && performance.now() - this.lastLiveDetectedAt <= cfg.liveFallbackMaxAgeMs) {
            detection = { ...this.lastLiveDetection, source: 'live-fallback' };
        }
        return { snapshot, detection };
    }

    // ------------------------------------------------------------------ overlay

    setOverlayTarget(detection, t) {
        if (detection) {
            // Sắp theo hình học chỉ để VẼ (góc i khung cũ trượt về góc i khung mới).
            const corners = orderPoints(detection.corners);
            this.overlayTarget = { corners, score: detection.score ?? null };
            this.overlayMissAt = null;
            this.updateStability(corners);
        } else {
            if (this.overlayTarget && this.overlayMissAt == null) this.overlayMissAt = t;
            this.stableHistory = [];
            this.isStable = false;
        }
        this.overlayDirty = true;
        this.updateStatus();
    }

    updateStability(corners) {
        if (!corners) return;
        const cfg = this.opts.box;
        const hist = this.stableHistory;
        hist.push(corners.map((p) => ({ x: p.x, y: p.y })));
        while (hist.length > cfg.stableCount) hist.shift();
        const tol = cfg.stableTolerance * Math.max(this.video?.videoWidth || 1, this.video?.videoHeight || 1);
        let stable = hist.length >= cfg.stableCount;
        for (let i = 1; stable && i < hist.length; i += 1) {
            for (let k = 0; k < 4; k += 1) {
                if (distance(hist[i][k], hist[i - 1][k]) > tol) { stable = false; break; }
            }
        }
        if (stable !== this.isStable) this.overlayDirty = true;
        this.isStable = stable;
    }

    updateStatus() {
        if (!this.backendReady) this.emitStatus('connecting');
        else if (!this.overlayTarget || this.overlayMissAt != null) this.emitStatus('empty');
        else this.emitStatus(this.isStable ? 'stable' : 'moving');
    }

    emitStatus(state) {
        if (state === this.state) return;
        this.state = state;
        const message = this.opts.messages[state] || state;
        if (this.opts.statusEl) this.opts.statusEl.textContent = message;
        this.opts.onStatus?.(state, message);
    }

    renderOverlay(now) {
        if (!this.overlay || !this.video?.videoWidth) return;
        const cfg = this.opts.box;
        const dt = this.lastRenderAt ? Math.min(100, now - this.lastRenderAt) : 16;
        this.lastRenderAt = now;

        const target = this.overlayTarget;
        if (!target) {
            if (this.overlayShown) {
                this.overlayShown = null;
                this.clearOverlay();
            }
            return;
        }
        let alpha = 1;
        if (this.overlayMissAt != null) {
            const age = now - this.overlayMissAt;
            if (age >= cfg.holdMs) {
                this.overlayTarget = null;
                this.overlayShown = null;
                this.overlayMissAt = null;
                this.clearOverlay();
                this.updateStatus();
                return;
            }
            alpha = 1 - age / cfg.holdMs;
        }

        // Làm mượt kiểu hàm mũ: sau smoothingMs khung đi được ~63% quãng đường.
        let moving = false;
        if (!this.overlayShown) {
            this.overlayShown = target.corners.map((p) => ({ x: p.x, y: p.y }));
            moving = true;
        } else {
            const k = 1 - Math.exp(-dt / cfg.smoothingMs);
            this.overlayShown.forEach((p, i) => {
                const dx = target.corners[i].x - p.x;
                const dy = target.corners[i].y - p.y;
                if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) moving = true;
                p.x += dx * k;
                p.y += dy * k;
            });
        }
        const size = `${this.overlay.clientWidth}x${this.overlay.clientHeight}`;
        if (!moving && alpha === 1 && !this.overlayDirty && size === this.overlayPaintedSize) return;
        this.overlayDirty = false;
        this.overlayPaintedSize = size;
        this.paintOverlay(this.overlayShown, target.score, alpha);
    }

    paintOverlay(corners, score, alpha) {
        const cfg = this.opts.box;
        const video = this.video;
        const ctx = this.prepareOverlayCanvas();
        const m = getFrameToOverlayMetrics(video.videoWidth, video.videoHeight,
            this.overlay.width, this.overlay.height, video, this.overlay);
        const pts = corners.map((p) => mapFramePoint(p, m));
        const color = this.isStable ? cfg.colorStable : cfg.colorMoving;

        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.lineJoin = 'round';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.55)';
        ctx.shadowBlur = 8;
        ctx.strokeStyle = '#07110e';
        ctx.lineWidth = 9;
        pathOf(ctx, pts);
        ctx.stroke();

        ctx.shadowBlur = 0;
        ctx.strokeStyle = color;
        ctx.lineWidth = 5;
        pathOf(ctx, pts);
        ctx.stroke();
        ctx.fillStyle = hexToRgba(color, this.isStable ? 0.16 : 0.12);
        pathOf(ctx, pts);
        ctx.fill();

        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        for (const p of pts) {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
            ctx.stroke();
        }
        if (cfg.showScore && score) {
            const top = pts.reduce((a, b) => (b.y < a.y ? b : a));
            ctx.fillStyle = color;
            ctx.font = '24px sans-serif';
            ctx.fillText(`${(score * 100).toFixed(0)}%`, top.x + 10, Math.max(28, top.y - 12));
        }
        ctx.restore();
    }

    prepareOverlayCanvas() {
        const w = Math.max(1, Math.round(this.overlay.clientWidth || this.video?.videoWidth || 1));
        const h = Math.max(1, Math.round(this.overlay.clientHeight || this.video?.videoHeight || 1));
        if (this.overlay.width !== w) this.overlay.width = w;
        if (this.overlay.height !== h) this.overlay.height = h;
        const ctx = this.overlay.getContext('2d');
        ctx.clearRect(0, 0, w, h);
        return ctx;
    }

    clearOverlay() {
        if (this.overlay) this.prepareOverlayCanvas();
    }
}

// ---------------------------------------------------------------------- helpers

function drawScaled(source, canvas, ctx, maxDim) {
    const sw = source.videoWidth || source.width;
    const sh = source.videoHeight || source.height;
    const s = Math.min(1, maxDim / Math.max(sw, sh));
    canvas.width = Math.max(1, Math.round(sw * s));
    canvas.height = Math.max(1, Math.round(sh * s));
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
}

function scaleDetection(det, sx, sy) {
    return {
        ...det,
        corners: scalePoints(det.corners, sx, sy),
        cornersModel: det.cornersModel ? scalePoints(det.cornersModel, sx, sy) : null,
        frame: det.frame ? { width: Math.round(det.frame.width * sx), height: Math.round(det.frame.height * sy) } : null,
    };
}

function pathOf(ctx, pts) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i += 1) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
}

function hexToRgba(hex, a) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex);
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function yieldToBrowser() {
    return new Promise((resolve) => {
        if ('requestIdleCallback' in window) window.requestIdleCallback(resolve, { timeout: 120 });
        else setTimeout(resolve, 0);
    });
}

function mergeDeep(base, extra) {
    const out = { ...base };
    for (const [k, v] of Object.entries(extra || {})) {
        const isPlain = v && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
        out[k] = isPlain && base[k] && typeof base[k] === 'object' ? mergeDeep(base[k], v) : v;
    }
    return out;
}
