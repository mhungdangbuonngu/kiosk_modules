# Triển khai Kiosk Intent trên máy sản phẩm

Gói triển khai chứa mã nguồn, ba model, lockfile, test và tài liệu. Gói không chứa `.venv`, cache,
video hoặc dữ liệu diagnostics từ máy phát triển.

> **Quan trọng:** `config/kiosk.calibrated.yaml` trong ZIP chỉ là kết quả hiệu chuẩn trên máy phát
> triển. Không dùng homography đó cho máy sản phẩm. Camera, ống kính, độ phân giải, vị trí và góc đặt
> khác nhau đều làm calibration cũ không còn chính xác. Phải hiệu chuẩn lại ngay tại vị trí lắp đặt.

## Yêu cầu

- Windows 10/11 64-bit.
- Python 3.12 do `uv` quản lý.
- `uv` phiên bản 0.8–0.x.
- Quyền truy cập camera cho ứng dụng desktop.
- Internet trong lần cài dependency đầu tiên. Model đã có sẵn trong ZIP.
- Camera đã được lắp cố định đúng vị trí vận hành.
- Thước đo và ít nhất 4 mốc sàn; nên dùng 6–12 mốc.

## 1. Giải nén

Giải nén ZIP vào một thư mục cố định, ví dụ:

```text
C:\Kiosk\kiosk-intent
```

Mở PowerShell tại thư mục vừa giải nén.

## 2. Cài môi trường

Nếu máy chưa có `uv`, cài theo tài liệu chính thức của uv. Sau đó chạy:

```powershell
uv sync --frozen --extra head-pose --extra visual-calibration
```

`--frozen` buộc máy sản phẩm dùng đúng phiên bản dependency trong `uv.lock`.

Kiểm tra OpenCV có hỗ trợ cửa sổ GUI:

```powershell
uv run --frozen python -c "import cv2; print([x.strip() for x in cv2.getBuildInformation().splitlines() if x.strip().startswith('GUI:')])"
```

Kết quả trên Windows phải chứa `GUI: WIN32`. Nếu thấy `GUI: NONE`, môi trường đang bị bản
`opencv-python-headless` ghi đè; xem mục xử lý sự cố ở cuối tài liệu.

## 3. Tạo cấu hình riêng cho máy sản phẩm

Không sửa trực tiếp file đã calibrate trên máy phát triển. Tạo cấu hình mới từ file mẫu:

```powershell
Copy-Item config\kiosk.example.yaml config\kiosk.production.yaml
```

Mở `config\kiosk.production.yaml` và chọn đúng camera:

```yaml
camera:
  source: 0
  backend: dshow
  width: 1920
  height: 1080
  fps: 30
  reconnect_ms: 1000
  resolution_mode: native
```

- Thử `source: 0`, `1`, `2` nếu máy có nhiều camera.
- Trên Windows, dùng `backend: dshow` nếu backend `auto` treo khi mở camera USB thứ hai.
- Trong `resolution_mode: native`, code yêu cầu `width`, `height` và `fps`; driver chọn mode native
  gần nhất mà camera thực sự hỗ trợ.
- Hệ thống giữ nguyên kích thước driver trả về, không upscale/downscale bằng phần mềm.
- Luôn cắm camera vào cùng một cổng USB để giảm khả năng Windows đổi thứ tự camera.

Kiểm tra đã chọn đúng camera:

```powershell
uv run --frozen --extra head-pose kiosk-vision doctor `
  config\kiosk.production.yaml --camera
```

Kết quả cần có `"ok": true`, `"opened": true` và `"frames_read": 5`.

## 4. Hiệu chuẩn tại vị trí lắp đặt

### 4.1. Cố định hệ thống

Trước khi hiệu chuẩn, cố định hoàn toàn camera, kiosk, chiều cao, góc nghiêng, zoom, focus, cổng USB
và điều kiện ánh sáng vận hành.

Chọn tâm chân kiosk trên mặt sàn làm gốc `(0, 0)`. Trục `x` chạy ngang, bên trái âm và bên phải
dương. Trục `y` hướng từ kiosk ra phía người dùng. Tất cả khoảng cách dùng đơn vị mét.

### 4.2. Đặt mốc sàn

Đặt tối thiểu 4 mốc không thẳng hàng; nên dùng 6–12 mốc trải đều vùng camera nhìn thấy. Phải có
mốc gần, xa, trái và phải. Tất cả mốc phải nằm trên cùng một mặt sàn. Đo tọa độ `(x, y)` của từng
mốc từ gốc tại chân kiosk; không ước lượng bằng mắt.

### 4.3. Chạy visual calibration

Đóng Camera, Teams, Zoom và mọi ứng dụng đang giữ webcam, rồi chạy:

```powershell
uv run --frozen --extra visual-calibration kiosk-vision calibrate-visual `
  config\kiosk.production.yaml `
  --output config\kiosk.production.calibrated.yaml `
  --correspondences config\kiosk.production.points.json
```

Trong cửa sổ calibration:

1. Nhấp chuột trái vào chính giữa một mốc sàn.
2. Gõ tọa độ `x,y` ngay trong cửa sổ, ví dụ `-1.5, 2.0`.
3. Nhấn `Enter` để xác nhận.
4. Lặp lại với tất cả mốc.
5. Sau ít nhất 4 điểm, kiểm tra các vùng `DETECTION`, `APPROACH`, `INTERACTION` trên hình.
6. Nhấn `S` để lưu.

Phím hỗ trợ:

| Phím | Chức năng |
|---|---|
| Chuột trái | Chọn mốc sàn |
| `Enter` | Xác nhận tọa độ |
| `Esc` | Hủy điểm đang nhập |
| `P` hoặc `Space` | Dừng/tiếp tục hình |
| `U` | Xóa điểm vừa thêm |
| `R` | Xóa toàn bộ và làm lại |
| `S` | Lưu calibration |
| `Q` | Thoát |

Kết quả cần giữ lại trên máy sản phẩm:

- `config\kiosk.production.calibrated.yaml` — cấu hình vận hành chính thức;
- `config\kiosk.production.points.json` — dữ liệu điểm để kiểm tra và truy vết.

## 5. Xác thực calibration

```powershell
uv run --frozen kiosk-vision validate-config config\kiosk.production.calibrated.yaml

uv run --frozen --extra head-pose kiosk-vision doctor `
  config\kiosk.production.calibrated.yaml --camera
```

Chạy preview để kiểm tra trực tiếp:

```powershell
uv run --frozen --extra visual-calibration kiosk-vision serve `
  config\kiosk.production.calibrated.yaml --preview
```

Đứng lần lượt tại các mốc đã đo và mở `http://127.0.0.1:8765/tracks`. Giá trị `world_xy` phải gần
tọa độ thực của mốc. Kiểm tra thêm một vài vị trí không dùng để tính homography. Nhấn `Ctrl+C` để
dừng dịch vụ sau khi xác thực.

Trong preview, nhãn mỗi người có `% frame`. Mặc định hệ thống phát `USER_ENGAGED` khi box chiếm từ
18% khung hình và phát `USER_LEFT` khi giảm dưới 12%. Chỉnh `engagement.bbox_enter_ratio` và
`engagement.bbox_exit_ratio` trong file calibrated theo góc camera thực tế; ngưỡng thoát phải nhỏ
hơn ngưỡng vào. Calibration vẫn cung cấp tọa độ/khoảng cách để quan sát nhưng không quyết định
người đó có đang sử dụng kiosk hay không.

## 6. Chạy dịch vụ chính thức

Chạy không có preview để giảm tải CPU:

```powershell
uv run --frozen kiosk-vision serve `
  config\kiosk.production.calibrated.yaml
```

Mở `http://127.0.0.1:8765/health` và xác nhận `status: ok`, `ready: true`, camera online, độ phân
giải native đúng mong đợi và `inference_errors` bằng `0`.

## 7. Khi nào phải hiệu chuẩn lại

Phải chạy lại bước 4 và 5 khi đổi camera hoặc ống kính; đổi cổng USB làm Windows chọn camera khác;
thay đổi độ phân giải; di chuyển hoặc xoay camera/kiosk; thay đổi zoom/focus; hoặc khi `world_xy`
lệch đáng kể so với vị trí thực.

## 8. Lưu ý vận hành

- Detector được khóa bằng `provider: cpu`; pipeline không dùng CUDA/GPU.
- Không mở Camera, Teams hoặc ứng dụng khác đồng thời vì chúng có thể giữ webcam.
- Không xóa file calibration và point JSON đã xác nhận tại hiện trường.
- Nên sao lưu hai file này theo mã kiosk, vị trí và ngày hiệu chuẩn.
- Nhấn `Ctrl+C` trong terminal để dừng dịch vụ.

## 9. Xác minh ZIP sau khi sao chép

```powershell
Get-FileHash .\kiosk-intent-production-*.zip -Algorithm SHA256
```

So sánh kết quả với file `.sha256` đi kèm. Nếu hash khác, không sử dụng gói.

## Máy sản phẩm không có Internet

ZIP này tương đương một gói source-control có kèm model; nó không chứa toàn bộ wheel Python. Nếu
máy sản phẩm hoàn toàn offline, cần tạo thêm wheel/cache bundle cho Windows x64 và Python 3.12 trên
một máy có Internet.

## Xử lý sự cố: doctor đọc được camera nhưng không có cửa sổ

Nếu `doctor --camera` thành công nhưng calibration không mở cửa sổ, kiểm tra `GUI:` bằng lệnh ở
bước 2. Với gói triển khai mới, chạy lại:

```powershell
Remove-Item .venv -Recurse -Force
uv sync --frozen --extra head-pose --extra visual-calibration
```

Thao tác này chỉ xóa môi trường Python có thể tái tạo; không xóa config, model hoặc calibration.
Không cài `opencv-python-headless` vì bản đó đọc được camera nhưng không có `namedWindow`/`imshow`.
