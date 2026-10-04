# human_detection — nhận diện người dùng đứng trước kiosk

Module độc lập: đưa vào frame từ camera đặt trước kiosk, nhận lại **có người đang dùng
kiosk hay không**, kèm sự kiện `USER_ENGAGED` (có người bước vào) / `USER_LEFT` (người
đó đi). Ghép vào app bất kỳ (Python, web, Node, C#…) mà không phụ thuộc phần còn lại
của repo.

Bên trong: YOLOX-Nano (ONNX, CPU) tìm người → ByteTrack giữ ID → một người được coi là
**đang dùng kiosk** khi khung của họ chiếm ≥ 30% diện tích frame, và **rời đi** khi
xuống dưới 25% hoặc mất dấu quá 1 s. Lõi là engine `kiosk_vision` (kiosk-intent), giữ
nguyên bản gốc trong `src/kiosk_vision/`.

## Chọn cách ghép

| Cách | Khi nào dùng | App cần gì |
|---|---|---|
| **A. Server HTTP** (khuyên dùng) | App ở môi trường/ngôn ngữ khác, hoặc Python ≥ 3.13 / numpy 2 | Gửi JPEG qua HTTP |
| **B. Gọi thẳng trong Python** | App chạy được Python 3.10–3.12, numpy < 2, OpenCV < 4.12 | `from human_detection import HumanDetector` |
| **C. Service tự mở camera** | App chỉ muốn nghe sự kiện, không tự chụp frame | Nghe WebSocket `/events/ws` |

Lý do có cách A: MediaPipe ≤ 0.10.21 (bản mới hơn tự gọi mạng, kiosk phải chạy offline)
chỉ có wheel tới Python 3.12, nên module khoá Python 3.12 + numpy < 2. Chạy thành tiến
trình riêng thì app của bạn dùng môi trường nào cũng được.

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/getting-started/installation/) (nó tự tải Python 3.12).

```bash
# Linux / macOS
scripts/setup.sh
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Script tạo `.venv` đúng phiên bản trong `uv.lock`, tải 3 model vào `models/` rồi kiểm
SHA-256 (xem `models/MANIFEST.md`), và chạy test. Lần đầu cần mạng (~1.2 GB gói);
sau đó chạy offline được. Model không nằm trong git.

## A. Server HTTP

```bash
scripts/run.sh                                     # config/kiosk.yaml, 127.0.0.1:8765
scripts/run.sh --port 8766 --calibration-frame 1920x1080
scripts/run.sh --cors-origin http://localhost:3000 # cho trang web gọi thẳng
```

Windows: `scripts\run.ps1` (cùng tham số). Tham số cũng đặt được bằng biến môi trường
`HUMAN_DETECTION_CONFIG`, `_HOST`, `_PORT`, `_CALIBRATION_FRAME`, `_ONNX_THREADS`.

| Tham số | Ý nghĩa |
|---|---|
| `--config` | file YAML (mặc định `config/kiosk.yaml`) |
| `--host`, `--port` | mặc định `service.host`/`service.port` trong YAML (`127.0.0.1:8765`) |
| `--calibration-frame WxH` | cỡ khung lúc hiệu chuẩn homography (mặc định `camera.width`×`camera.height`) |
| `--onnx-threads N` | luồng ONNX Runtime; `0` = tự chọn (nửa số CPU, tối đa 8). Máy nhiều nhân mà để ORT tự dùng hết thì **chậm hơn** ~20 lần |
| `--cors-origin` | cho trang web ở origin đó gọi thẳng; lặp lại được, `'*'` = tất cả |
| `--development-tracker` | tracker IoU đơn giản thay ByteTrack, chỉ để dò lỗi |

### Endpoint

Mặc định chỉ nghe `127.0.0.1`, **không có xác thực** — muốn mở ra mạng thì đặt sau
reverse proxy có xác thực.

| Endpoint | |
|---|---|
| `POST /frame?timestampMs=` | thân request = **nguyên byte** một ảnh JPEG/PNG (không multipart). Trả kết quả bên dưới |
| `POST /reset` | bỏ hết track, bắt đầu phiên mới; người đang dùng → phát `USER_LEFT` (`session_reset`) |
| `GET /status` | cấu hình đang chạy: khung hiệu chuẩn, ngưỡng, vùng, số luồng, checksum model |
| `GET /health` | `{"status": "ok", "ready": true, ...}` — cho process supervisor |
| `GET /tracks`, `GET /events` | track hiện tại / ~100 sự kiện gần nhất |
| `WS /events/ws` | luồng sự kiện trực tiếp |

`timestampMs` là đồng hồ **đơn điệu** của bên chụp (vd. `performance.now()`), để vận tốc
không lệch theo độ trễ mạng; bỏ trống thì server lấy giờ lúc nhận. Đồng hồ đi lùi (trang
tải lại) hoặc đổi cỡ frame = phiên mới.

**Quy tắc gửi frame:** chỉ **một** camera, **đúng thứ tự** thời gian, gửi tuần tự (đợi
kết quả rồi mới gửi tiếp), ~5–10 frame/giây. Thu nhỏ frame được (vd. 1280×720 từ camera
1920×1080) — % khung không đổi, toạ độ sàn tự quy đổi — miễn **giữ đúng tỉ lệ** khung.

### Kết quả `POST /frame`

```jsonc
{
  "timestampMs": 1000,
  "frame": {"width": 1280, "height": 720},     // mọi toạ độ pixel theo frame gửi lên
  "ms": 21.4,                                   // thời gian xử lý
  "activeTrackId": 3,                           // null = không ai đang dùng kiosk
  "tracks": [{
    "id": 3,
    "state": "ENGAGED",                         // PRESENT | ENGAGED | ENGAGED_HOLD | ...
    "active": true,
    "seen": true,                               // false = frame này không thấy, đang giữ chờ
    "bbox": [400, 100, 880, 684],               // x1, y1, x2, y2
    "bboxAreaRatio": 0.3041,                    // đại lượng quyết định ENGAGED
    "confidence": 0.91,
    "worldXY": [0.0, 0.2], "distanceM": 0.2,    // toạ độ sàn (m) — chỉ để xem
    "zones": {"detection": true, "approach": false, "interaction": true}
    // ... velocityMps, facingScore, head, ageMs, stateMs
  }],
  "events": [{                                  // sự kiện MỚI phát sinh ở frame này
    "timestamp_ms": 1000, "event": "USER_ENGAGED", "track_id": 3,
    "reason": ["bbox_area_ratio_above_enter_threshold"],
    "distance_m": 0.2, "facing_score": null, "engagement_confidence": 1.0
  }],
  "zones": {"detection": [[x, y], ...], ...},   // 3 vùng chiếu lên ảnh, để vẽ
  "calibration": {"frame": {...}, "scale": [1.5, 1.5], "aspectMismatch": false},
  "notes": []                                   // "clock_reset", "frame_size_changed"
}
```

Lý do của `USER_LEFT`: `bbox_area_ratio_below_exit_threshold`, `track_lost`,
`session_reset`, `clock_reset`, `frame_size_changed`.

App thường chỉ cần: **`activeTrackId !== null`** (đang có người dùng) hoặc phản ứng theo
`events`.

### Client có sẵn

- **Python** — [`src/human_detection/client.py`](src/human_detection/client.py): chỉ dùng
  thư viện chuẩn (Python 3.8+), chép nguyên file vào app là dùng được.

  ```python
  from client import HumanDetectionClient
  hd = HumanDetectionClient("http://127.0.0.1:8765")
  hd.wait_until_ready()
  result = hd.send_frame(jpeg_bytes)
  if result["activeTrackId"] is not None:
      ...
  ```

  Ví dụ đầy đủ đọc camera bằng OpenCV: [`examples/python_camera.py`](examples/python_camera.py).

- **Trình duyệt** — [`examples/humanDetectionClient.js`](examples/humanDetectionClient.js)
  (ES module): lấy frame từ `<video>`, gửi tuần tự, gọi `onEngaged` / `onLeft`. Demo vẽ
  khung người: [`examples/browser_demo.html`](examples/browser_demo.html) (chạy server với
  `--cors-origin '*'` rồi mở file bằng Chrome/Edge).

- **Ngôn ngữ khác** — chỉ là HTTP: `POST` byte JPEG với `Content-Type: image/jpeg`.

  ```bash
  curl -s -X POST --data-binary @frame.jpg -H 'Content-Type: image/jpeg' \
       'http://127.0.0.1:8765/frame?timestampMs=1000'
  ```

## B. Gọi thẳng trong Python

Cài vào môi trường Python 3.10–3.12 của app: `pip install -e path/to/human_detection[head-pose]`
(hoặc chạy app bằng `uv run` trong thư mục này). Khi cài ở chỗ khác mà không có thư mục
`models/` bên cạnh, truyền `root=` hoặc đặt `HUMAN_DETECTION_HOME` trỏ tới thư mục chứa
`models/` và `config/`.

```python
from human_detection import DEFAULT_CONFIG, HumanDetector, load_config

config, checksum = load_config(DEFAULT_CONFIG)
detector = HumanDetector.load(config, checksum, onnx_threads=4)
result, events = detector.process(frame_bgr, timestamp_ms)   # frame numpy BGR (OpenCV)
# hoặc detector.process_jpeg(jpeg_bytes, timestamp_ms)
detector.reset()
detector.close()
```

`result` giống hệt JSON của `POST /frame`. Một `HumanDetector` dùng cho **một** camera;
có khoá nội bộ nên gọi từ nhiều luồng không hỏng, nhưng frame vẫn phải đúng thứ tự.
Ví dụ: [`examples/in_process.py`](examples/in_process.py).

## C. Service tự mở camera

Công cụ gốc `kiosk-vision` tự đọc `camera.source` trong YAML và phát sự kiện, app chỉ
cần nghe `WS /events/ws` hoặc gọi `GET /health`:

```bash
uv run --extra head-pose kiosk-vision serve config/kiosk.yaml
uv run --extra visual-calibration kiosk-vision serve config/kiosk.yaml --preview  # có cửa sổ xem
```

Cách này không có `/frame`, `/status`, `/reset`. Chi tiết: [`docs/KIOSK_VISION_README.md`](docs/KIOSK_VISION_README.md).

## Cấu hình và hiệu chuẩn

[`config/kiosk.yaml`](config/kiosk.yaml) là cấu hình mặc định, **hiệu chuẩn cho camera trước
kiosk VOTRANH ở 1920×1080**. Các khoá hay chỉnh:

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `engagement.bbox_enter_ratio` | `0.30` | khung người ≥ 30% frame → `USER_ENGAGED` |
| `engagement.bbox_exit_ratio` | `0.25` | xuống dưới 25% → `USER_LEFT` (khoảng chênh chống nhấp nháy) |
| `engagement.lost_track_ms` | `1000` | mất dấu bao lâu thì coi là đã đi |
| `detector.confidence_threshold` | `0.3` | ngưỡng tin cậy YOLOX |
| `head_pose.enabled` | `false` | bật YuNet + MediaPipe để có hướng đầu (chỉ để xem, chậm hơn) |
| `camera.width` / `height` | `1920` / `1080` | cỡ khung hiệu chuẩn mặc định |

Kiosk khác / camera đặt khác: **ngưỡng % khung** phải chỉnh theo khoảng cách camera–người
dùng (đứng ở vị trí dùng kiosk, xem `bboxAreaRatio`, đặt ngưỡng vào thấp hơn một chút).
Toạ độ sàn và 3 vùng chỉ để xem, không ảnh hưởng quyết định — muốn đúng thì hiệu chuẩn lại
theo [`docs/CALIBRATION_VI.md`](docs/CALIBRATION_VI.md) hoặc
[`docs/VIDEO_CALIBRATION.md`](docs/VIDEO_CALIBRATION.md).

Kiểm tra cài đặt và camera:

```bash
uv run --extra head-pose kiosk-vision doctor config/kiosk.yaml            # không cần camera
uv run --extra head-pose kiosk-vision doctor config/kiosk.yaml --camera   # có camera
```

## Cấu trúc thư mục

```
human_detection/
├── src/human_detection/   phần ghép: engine.py (HumanDetector), server.py (HTTP), client.py
├── src/kiosk_vision/      engine gốc kiosk-intent — KHÔNG sửa, cập nhật = chép đè
├── config/kiosk.yaml      cấu hình mặc định (+ các YAML mẫu/hiệu chuẩn gốc)
├── models/                3 model (tải bằng scripts/setup.*), MANIFEST.md có SHA-256
├── scripts/               setup.sh / setup.ps1, run.sh / run.ps1
├── examples/              client JS, demo trình duyệt, ví dụ Python
├── tests/                 pytest (`uv run pytest -q`)
└── docs/                  hiệu chuẩn, README gốc của kiosk-intent, DEPLOY_VI.md
```

Cập nhật engine gốc từ bản kiosk-intent mới: chép đè `src/kiosk_vision/`, rồi nếu
`runtime.py::VisionRuntime._run` thay đổi thì sửa theo `HumanDetector.process()` trong
`engine.py`, chạy `uv run pytest -q`.

## Riêng tư

Không lưu frame nào: ảnh chỉ nằm trong bộ nhớ lúc xử lý. Track ID ẩn danh, chỉ sống trong
tiến trình. Model chạy hoàn toàn offline trên CPU.
