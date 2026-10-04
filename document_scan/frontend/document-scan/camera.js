// Mở camera cho <video>. Không bắt buộc dùng — app đã có stream riêng thì gán
// video.srcObject rồi đưa <video> đó cho DocumentScanner là đủ.

/**
 * @param {HTMLVideoElement} video
 * @param {object} [opts]
 * @param {number} [opts.width=3840]   độ phân giải mong muốn (camera càng nét, ảnh cắt càng nét)
 * @param {number} [opts.height=2160]
 * @param {number} [opts.frameRate=10]
 * @param {string} [opts.label]        một phần tên camera (không phân biệt hoa thường), vd 'Logitech'
 * @param {string} [opts.facingMode='environment']
 * @returns {Promise<MediaStream>}
 */
export async function openCamera(video, opts = {}) {
    const { width = 3840, height = 2160, frameRate = 10, label = '', facingMode = 'environment' } = opts;
    const deviceId = label ? await findCameraByLabel(label) : null;
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
            // deviceId exact: camera bị rút thì báo lỗi, thay vì lặng lẽ quay về webcam laptop.
            ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: facingMode } }),
            width: { ideal: width },
            height: { ideal: height },
            frameRate: { ideal: frameRate, max: Math.max(10, frameRate + 3) },
        },
    });
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await new Promise((resolve) => {
        if (video.readyState >= 1) resolve();
        else video.addEventListener('loadedmetadata', resolve, { once: true });
    });
    await video.play().catch(() => {});
    return stream;
}

export function stopCamera(video) {
    const stream = video?.srcObject;
    if (stream?.getTracks) stream.getTracks().forEach((t) => t.stop());
    if (video) video.srcObject = null;
}

export async function listCameras() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'videoinput');
}

async function findCameraByLabel(label) {
    const want = label.trim().toLowerCase();
    let cameras = await listCameras();
    // Trình duyệt giấu tên camera khi origin chưa được cấp quyền -> xin quyền rồi đọc lại.
    if (cameras.length && cameras.every((d) => !d.label)) {
        let probe = null;
        try {
            probe = await navigator.mediaDevices.getUserMedia({ video: true });
            cameras = await listCameras();
        } catch (e) {
            console.warn('[DocScan] Không xin được quyền để đọc tên camera:', e.name);
        } finally {
            probe?.getTracks().forEach((t) => t.stop());
        }
    }
    const hit = cameras.find((d) => d.label.toLowerCase().includes(want));
    if (!hit) {
        console.warn(`[DocScan] Không thấy camera khớp "${label}". Đang có:`, cameras.map((d) => d.label));
        return null;
    }
    return hit.deviceId;
}

/**
 * Hiển thị video xoay 90° (camera gắn nằm ngang, màn hình dọc) mà vẫn vừa khung chứa.
 * Overlay của DocumentScanner tự nhận ra phép xoay này. Trả hàm huỷ.
 */
export function layoutRotatedVideo(video, deg = 90) {
    const container = video.parentElement;
    const apply = () => {
        const rect = container.getBoundingClientRect();
        if (!rect.width || !rect.height || !video.videoWidth) return;
        const aspect = video.videoHeight / video.videoWidth;   // tỉ lệ SAU khi xoay
        const w = Math.min(rect.width, rect.height * aspect);
        const h = Math.min(rect.height, rect.width / aspect);
        Object.assign(video.style, {
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: `${h}px`,       // phần tử bị xoay nên kích thước trước xoay đảo cho nhau
            height: `${w}px`,
            maxWidth: 'none',
            maxHeight: 'none',
            objectFit: 'contain',
            transformOrigin: 'center center',
            transform: `translate(-50%, -50%) rotate(${deg}deg)`,
        });
    };
    apply();
    video.addEventListener('loadedmetadata', apply);
    window.addEventListener('resize', apply);
    return () => {
        video.removeEventListener('loadedmetadata', apply);
        window.removeEventListener('resize', apply);
    };
}
