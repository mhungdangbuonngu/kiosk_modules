# Document Scan module

Module quét tài liệu từ camera, tách từ kiosk: tìm 4 góc tài liệu bằng **YOLO pose** →
**refine** kéo 4 cạnh vào mép giấy thật → **cắt + nắn phẳng**. Gồm 2 phần độc lập:

```
document_scan/
├── backend/                       Python — nhận ảnh, trả 4 góc (và cắt ảnh nếu cần)
│   ├── models/docscan.onnx                 model YOLO pose (input cố định 1280×1280)
│   ├── refine_mask.png            mask khay của camera kiosk (trắng = cửa kính khay)
│   ├── document_scan/             package Python
│   │   ├── service.py             DocumentScanService: detect / scan / crop_document
│   │   ├── detector.py            YOLO pose chạy bằng ONNX Runtime (KHÔNG cần PyTorch)
│   │   ├── refine.py              kéo 4 cạnh vào mép giấy
│   │   ├── geometry.py            warp_quad, hàm hình học
│   │   ├── config.py              DocScanConfig (mặc định / JSON / biến môi trường)
│   │   └── api.py                 router FastAPI (/status, /detect, /scan)
│   ├── server.py                  server mẫu: API + phục vụ frontend/ để thử
│   ├── run.sh, requirements.txt
│   └── tests/
└── frontend/
    ├── index.html                 trang demo = ví dụ tích hợp
    └── document-scan/             ES module, không cần build
        ├── index.js               điểm import
        ├── DocumentScanner.js     vòng detect live, vẽ khung, chụp
        ├── cropper.js             cắt + nắn phẳng bằng OpenCV.js
        ├── camera.js              mở camera, hiển thị video xoay 90°
        ├── geometry.js
        └── opencv.js              OpenCV.js (kèm sẵn, chạy offline)
```

## Chạy thử nhanh

```bash
cd document_scan/backend
pip install -r requirements.txt
python server.py --port 8000          # mở http://localhost:8000/
```

Trình duyệt chỉ cho mở camera trên `https://` hoặc `http://localhost`.

## Backend

Yêu cầu: Python ≥ 3.8, `numpy`, `opencv-python-headless`, `onnxruntime`
(+ `fastapi`, `uvicorn`, `python-multipart` nếu dùng router). Không cần GPU, không cần PyTorch.

### Gắn vào app FastAPI có sẵn

Chép thư mục `backend/` (giữ nguyên `models/` cạnh package `document_scan/`) rồi:

```python
import sys; sys.path.insert(0, "/đường/dẫn/tới/document_scan/backend")
from document_scan.api import create_router

app.include_router(create_router())                  # -> /api/docscan/...
# app.include_router(create_router(prefix="/scanner"))
```

Model được nạp + warm-up một lần ở thread nền ngay khi tạo router.

### Dùng trực tiếp (Flask, Django, script...)

```python
from document_scan import DocumentScanService, DocScanConfig

svc = DocumentScanService()                      # hoặc DocumentScanService(DocScanConfig.load(onnx_threads=4))
result = svc.detect(bgr, mode="live")            # bgr = ảnh OpenCV (numpy, BGR)
page, result = svc.scan(bgr, orientation="document", max_long_side=2800)   # ảnh đã cắt
```

### Endpoint

| Method | Path (prefix `/api/docscan`) | Vào | Ra |
| --- | --- | --- | --- |
| GET | `/status` | — | `{ready, imgsz, imgszLive, refine, refineLive, ...}` |
| POST | `/detect` | multipart `file`, `mode` = `live` \| `capture` | JSON bên dưới |
| POST | `/scan` | multipart `file`, `orientation` (`document`/`portrait`), `maxLongSide`, `quality` | `image/jpeg` đã cắt; header `X-DocScan-Result` = JSON quad |

Kết quả `/detect` (toạ độ theo chính ảnh gửi lên):

```json
{
  "found": true,
  "quad":      [{"x":..,"y":..} ×4],   // góc CUỐI CÙNG sau refine — dùng để vẽ khung và để cắt
  "quadModel": [{"x":..,"y":..} ×4],   // góc thô của model (chỉ để gỡ lỗi)
  "refine": "refined",                 // hoặc lý do giữ góc model: unchanged, area_change, ...
  "refined": true,
  "score": 0.85, "ms": 120.4, "mode": "live",
  "frame": {"width": 960, "height": 540}
}
```

Thứ tự góc là **TL, TR, BR, BL của chính trang tài liệu** (góc trên-trái của trang in),
không phải của ảnh — nên cắt theo đúng thứ tự này thì ảnh tự đứng đúng chiều.

### Cấu hình

Ưu tiên: mặc định → file JSON (`DocScanConfig.load("cfg.json")` hoặc env `DOCSCAN_CONFIG`)
→ biến môi trường `DOCSCAN_<TÊN_VIẾT_HOA>` → tham số truyền vào `load(...)`.

| Khoá | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `weights` | `models/docscan.onnx` | đường dẫn tương đối tính từ thư mục `backend/` của module, không phụ thuộc thư mục đang chạy |
| `conf` | 0.65 | độ tin cậy tối thiểu. Đặt cao để khay trống không hiện khung: khay trống tối đa ~0.56, giấy thật thấp nhất ~0.80 |
| `iou` | 0.7 | ngưỡng NMS |
| `min_area_frac` | 0.002 | bỏ tứ giác nhỏ hơn tỉ lệ này của khung |
| `onnx_threads` | 0 | 0 = tự chọn (½ số CPU, tối đa 8). **Đừng** để ONNX Runtime dùng hết nhân — máy nhiều nhân chậm gấp ~10 lần |
| `refine` / `refine_live` | true / true | refine lúc chụp / lúc live |
| `refine_mask` | `refine_mask.png` | mask khay (tương đối từ `backend/`); `""` hoặc file không có = không mask. Xem mục *Mask khay* |
| `max_frame_side` | 1280 | frame lớn hơn bị thu nhỏ trước khi detect |
| `imgsz` / `imgsz_live` | 1280 / 640 | bị bỏ qua với model kèm theo (input cố định 1280) |

Ví dụ: `DOCSCAN_ONNX_THREADS=4 DOCSCAN_CONF=0.3 python server.py`

## Frontend

ES module thuần, không cần bundler. Chép thư mục `frontend/document-scan/` vào app.

```html
<div class="stage" style="position:relative">
  <video id="video" autoplay playsinline muted style="width:100%;height:100%;object-fit:contain"></video>
  <canvas id="overlay" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></canvas>
</div>

<script type="module">
  import { DocumentScanner, openCamera } from './document-scan/index.js';

  const video = document.getElementById('video');
  await openCamera(video, { width: 3840, height: 2160 });   // hoặc tự gán video.srcObject

  const scanner = new DocumentScanner({
    video,
    overlay: document.getElementById('overlay'),
    apiBase: '/api/docscan',                // hoặc 'https://may-chu:8000/api/docscan'
    onStatus: (state, msg) => console.log(state, msg),   // connecting|empty|moving|stable|error
  });
  await scanner.init();                     // tải OpenCV.js + hỏi backend
  scanner.start();                          // bắt đầu vòng detect + vẽ khung

  const shot = await scanner.capture({
    onPreview: ({ blob }) => { /* hiện ngay ảnh xem trước */ },
  });
  if (shot) {
    // shot.blob (JPEG đã cắt + nắn), shot.canvas, shot.width, shot.height,
    // shot.thumbnailBlob, shot.detection (quad đã dùng), shot.snapshot (khung gốc)
  }
</script>
```

### Mask khay

`backend/refine_mask.png` là ảnh trắng/đen cùng tỉ lệ với frame camera: **trắng = cửa kính
khay**, đen = ngoài khay. Refine chỉ tìm mép giấy trong vùng trắng; cạnh giấy nào tràn ra
ngoài vùng trắng thì được kẻ theo mép mask, nên ảnh cắt chỉ lấy phần giấy nằm trong khay
(`detect` trả `"mask"` cho cạnh đó trong trạng thái từng cạnh).

Mask gắn với **vị trí camera**: file kèm theo vẽ cho camera kiosk hiện tại. Đổi camera / dịch
camera thì vẽ lại trên ảnh nền mới (trang `mask-editor.html` của repo kiosk), hoặc đặt
`refine_mask=""` để tắt.

### Khung trên màn hình = quad sau refine

Khung vẽ luôn là `quad` backend trả (đã refine), **không bao giờ** vẽ `quadModel`. Đây cũng
chính là quad dùng để cắt, nên khung người dùng thấy đúng bằng vùng sẽ được cắt. Backend
mặc định bật refine cho cả live (`refine_live: true`).

Muốn chặt hơn — chỉ hiện khung khi refine **thành công** (lần nào refine phải giữ góc model
thì coi như không thấy): `new DocumentScanner({ ..., box: { requireRefined: true } })`.

### Các bước khi `capture()`

1. Đóng băng khung hình video ở độ phân giải gốc (không dùng quad live cũ — giấy xê dịch là cắt lệch).
2. Thu nhỏ về cỡ model nhìn, gửi `/detect` mode `capture` → quad đã refine, nhân lại về độ phân giải gốc.
   Hụt thì dùng tạm quad live nếu còn mới hơn 800ms.
3. Xoay khung theo `crop.captureRotation`, chỉ chép vùng quanh tài liệu (nới `crop.padding`).
4. Gọi `onPreview` với ảnh vùng đó (để UI hiện ngay).
5. `warpPerspective` (INTER_CUBIC) theo 4 góc; `orientation: 'portrait'` thì ảnh ngang được xoay thành dọc.
6. Thu nhỏ cạnh dài ≤ `crop.outputMaxLongSide`, nén JPEG `crop.jpegQuality`, kèm thumbnail.

Không chỉnh sáng / tương phản / làm nét — ảnh giữ nguyên như camera chụp.

### Tuỳ chọn chính (`DEFAULT_OPTIONS` trong DocumentScanner.js)

| Tuỳ chọn | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `apiBase` | `/api/docscan` | prefix API backend |
| `fetchOptions` | `{}` | thêm vào mọi fetch, vd `{ headers: { Authorization } }` |
| `opencvUrl` | `./opencv.js` cạnh module | `null` nếu trang đã tự nhúng OpenCV.js |
| `detectionIntervalMs` | 380 | nhịp gửi frame live (không gửi khi khung hình đứng yên) |
| `box.requireRefined` | false | chỉ hiện khung khi refine thành công |
| `box.smoothingMs` / `holdMs` | 150 / 700 | khung trượt mượt / mờ dần khi hụt |
| `box.colorMoving` / `colorStable` | vàng / xanh | xanh = mọi góc đứng yên qua 3 lần detect |
| `crop.captureRotation` | 0 | xoay khung trước khi cắt: 0, 90, -90, 180. Kiosk gốc dùng -90 |
| `crop.orientation` | `portrait` | `portrait` = ép khổ dọc (như kiosk gốc); `document` = theo chiều trang in (lộn ngược / nằm ngang cũng ra đúng chiều) |
| `crop.outputMaxLongSide` | 2800 | cạnh dài tối đa ảnh ra |
| `crop.jpegQuality` | 0.95 | |
| `messages` | tiếng Việt | chữ hiện cho từng trạng thái |
| `statusEl` | null | phần tử nhận chữ trạng thái |

### Camera gắn nằm ngang, màn hình dọc (như kiosk)

```js
import { layoutRotatedVideo } from './document-scan/index.js';
layoutRotatedVideo(video, 90);                                  // xoay video bằng CSS để hiển thị
new DocumentScanner({ ..., crop: { captureRotation: -90 } });    // xoay ảnh khi cắt (như kiosk gốc)
```

Overlay tự đọc CSS `transform` / `object-fit` của `<video>` nên khung vẫn khớp khi video bị xoay.

### Backend ở origin khác

Đặt `apiBase` là URL tuyệt đối. `server.py` đã bật CORS; app của bạn thì tự thêm
`CORSMiddleware`. Trang chạy HTTPS thì backend cũng phải HTTPS (mixed content), hoặc cho
server frontend chuyển tiếp `/api/docscan/*` sang backend.

## Kiểm tra

```bash
cd document_scan/backend
python -m pytest tests -q
DOCSCAN_TEST_IMAGES="/đường/dẫn/anh/*.png" python -m pytest tests -q
```

Detector ONNX Runtime thuần đã được so với bản Ultralytics của kiosk trên 400 ảnh thật:
4 góc lệch tối đa 0.0001px, cùng kết quả có/không có tài liệu.
