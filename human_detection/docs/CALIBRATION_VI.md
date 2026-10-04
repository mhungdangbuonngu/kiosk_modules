# Hướng dẫn hiệu chuẩn camera trực quan

Công cụ `calibrate-visual` hiển thị hình ảnh trực tiếp từ camera, cho phép chọn các mốc trên sàn
và chiếu ba vùng hoạt động lên hình ảnh. Toàn bộ quá trình chạy cục bộ. Công cụ không lưu ảnh hay
video; nó chỉ lưu tọa độ điểm và ma trận homography.

## 1. Hiểu hệ tọa độ

Hệ thống theo dõi vị trí bàn chân trên một mặt sàn phẳng:

- Gốc `(0, 0)` nên đặt tại vị trí kiosk.
- Trục `x` chạy ngang: bên trái kiosk là số âm, bên phải là số dương.
- Trục `y` chạy từ kiosk ra phía trước và dùng số dương.
- Đơn vị của cả hai trục là mét.

Ví dụ, một điểm cách kiosk 1,5 m về bên trái và 2 m về phía trước có tọa độ `(-1.5, 2.0)`.

## 2. Cố định camera

Trước khi hiệu chuẩn, hãy cố định hoàn toàn:

- vị trí, chiều cao và góc nghiêng camera;
- tiêu cự, zoom và hướng camera;
- độ phân giải camera trong tệp cấu hình;
- vị trí kiosk so với các mốc sàn.

Nếu camera bị di chuyển hoặc thay đổi zoom sau khi hiệu chuẩn, cần hiệu chuẩn lại.

## 3. Đặt và đo các mốc trên sàn

Đặt tối thiểu 4 mốc trên cùng một mặt sàn. Nên dùng 8–12 mốc để RANSAC loại bỏ sai số tốt hơn.

Các mốc tốt nên:

- trải rộng từ gần đến xa và từ trái sang phải trong vùng camera nhìn thấy;
- không nằm trên cùng một đường thẳng;
- có tâm dễ xác định trên hình ảnh;
- được đo từ gốc `(0, 0)` bằng thước, không ước lượng bằng mắt.

Không dùng điểm trên tường, bàn hoặc vật thể cao vì homography này chỉ mô hình hóa mặt sàn.

Ghi tọa độ thực `(x, y)` của từng mốc ra giấy trước khi mở công cụ.

## 4. Chuẩn bị cấu hình

Tạo cấu hình riêng để không chỉnh sửa tệp ví dụ:

```powershell
Copy-Item config\kiosk.example.yaml config\kiosk.yaml
```

Kiểm tra phần camera trong `config/kiosk.yaml`:

```yaml
camera:
  source: 0
  width: 1920
  height: 1080
  fps: 30
  resolution_mode: native
```

Nếu máy có nhiều camera, `source` có thể là `1`, `2`, v.v.

## 5. Mở công cụ hiệu chuẩn

Đóng Camera, Teams, Zoom hoặc ứng dụng khác đang sử dụng webcam, rồi chạy:

```powershell
uv run --extra visual-calibration kiosk-vision calibrate-visual `
  config\kiosk.yaml `
  --output config\kiosk.calibrated.yaml
```

Cửa sổ camera sẽ mở. Dòng đầu trong terminal cho biết độ phân giải gốc và độ phân giải khung hiệu
chuẩn. Với `resolution_mode: native`, `width` và `height` chỉ là mode ưu tiên gửi cho driver. Nếu
camera không hỗ trợ mode đó, hệ thống dùng nguyên độ phân giải camera thực sự trả về và không phóng
hay thu nhỏ hình. Khi thay camera, phải hiệu chuẩn lại vì độ phân giải, ống kính và góc nhìn thay đổi.

## 6. Chọn các điểm

1. Có thể nhấn `P` hoặc `Space` nếu muốn dừng hình tại một khung rõ nét. Việc dừng hình không bắt
   buộc.
2. Nhấp chuột trái chính xác vào tâm một mốc trên sàn. Video vẫn tiếp tục chạy.
3. Giữ cửa sổ camera đang được chọn và nhập tọa độ thực của mốc theo dạng `x,y`, ví dụ:

   ```text
   -1.5, 2.0
   ```

4. Nhấn Enter ngay trong cửa sổ camera. Điểm cùng nhãn tọa độ sẽ xuất hiện trên hình.
5. Lặp lại cho tất cả các mốc. Có thể nhấn `P` hoặc `Space` để tiếp tục hay dừng camera.

Sau khi có ít nhất 4 điểm hợp lệ, công cụ tự tính homography và vẽ các vùng lên camera:

- `detection`: vùng phát hiện bên ngoài;
- `approach`: vùng người dùng đang tiếp cận;
- `interaction`: vùng tương tác gần kiosk.

Các phím điều khiển:

| Phím | Chức năng |
|---|---|
| Chuột trái | Chọn một điểm ảnh; gõ tọa độ trực tiếp trong cửa sổ camera |
| `P` hoặc `Space` | Dừng/tiếp tục hình camera |
| `U` | Xóa điểm vừa thêm |
| `R` | Xóa toàn bộ điểm và làm lại |
| `S` | Lưu kết quả |
| `Q` hoặc `Esc` | Thoát |

Nếu nhấp nhầm, nhấn Enter mà không nhập tọa độ để hủy điểm đó, hoặc dùng `U` sau khi đã thêm.

## 7. Kiểm tra vùng ảo

Quan sát các đường vùng được chiếu lên sàn:

- Các cạnh phải đi qua đúng vị trí vật lý được mô tả trong `detection_polygon_m`,
  `approach_polygon_m` và `interaction_polygon_m`.
- Đường thẳng không nên bị gấp, giao chéo hoặc hội tụ vào vị trí bất thường.
- Sai số thường lớn hơn ở vùng nằm ngoài phạm vi các mốc. Hãy đặt mốc bao quanh toàn bộ khu vực
  cần theo dõi.

Nếu đường vùng sai lệch, dùng `U` để bỏ điểm cuối hoặc `R` để làm lại. Kiểm tra đặc biệt việc ghép
đúng điểm ảnh với tọa độ đã đo.

Lưu ý: công cụ dùng các polygon đang có trong tệp đầu vào để vẽ lớp phủ. Nếu muốn thay đổi kích
thước vùng, sửa các polygon trong `config/kiosk.yaml`, mở lại công cụ và kiểm tra trực quan lần nữa.

## 8. Lưu kết quả

Nhấn `S`. Với lệnh ở trên, công cụ tạo:

- `config/kiosk.calibrated.yaml`: cấu hình đầy đủ với homography mới;
- `config/kiosk.calibrated.points.json`: các cặp điểm ảnh–tọa độ sàn để kiểm tra hoặc tái sử dụng.

Tệp camera không được ghi xuống ổ đĩa. Cấu hình đầu vào `config/kiosk.yaml` cũng không bị ghi đè.

## 9. Xác thực bằng người thật

Kiểm tra cấu hình và camera:

```powershell
uv run kiosk-vision validate-config config\kiosk.calibrated.yaml
uv run --extra head-pose kiosk-vision doctor config\kiosk.calibrated.yaml --camera
```

Khởi động dịch vụ:

```powershell
uv run --extra head-pose kiosk-vision serve config\kiosk.calibrated.yaml
```

Đứng lần lượt lên các mốc đã đo rồi mở:

```text
http://127.0.0.1:8765/tracks
```

So sánh `world_xy` với tọa độ thực của mốc. Hệ thống sử dụng điểm giữa cạnh dưới của khung người
làm vị trí bàn chân, vì vậy hãy đứng thẳng và để camera thấy rõ bàn chân.

### Xem nhận diện trực tiếp trên camera

Để mở cửa sổ camera có khung người, trạng thái, tọa độ và thông số xử lý, chạy:

```powershell
uv run --extra visual-calibration kiosk-vision serve `
  config\kiosk.calibrated.yaml --preview
```

Cửa sổ hiển thị:

- khung và ID của từng người;
- trạng thái `PRESENT` hoặc `ENGAGED` và phần trăm khung hình mà bounding box chiếm;
- chữ `PERSON DETECTED` khi nhận diện được người;
- chữ `KIOSK IN USE` khi bounding box vượt ngưỡng sử dụng;
- điểm chân, tọa độ `x, y`, khoảng cách đến kiosk;
- các vùng `DETECTION`, `APPROACH` và `INTERACTION`;
- FPS và độ trễ xử lý.

Quyết định sử dụng kiosk không còn phụ thuộc chuỗi trạng thái, vùng calibration hay hướng khuôn mặt.
Trong phần `engagement` của YAML:

- `bbox_enter_ratio: 0.18`: kích hoạt khi box chiếm ít nhất 18% toàn bộ khung hình;
- `bbox_exit_ratio: 0.12`: giữ trạng thái cho đến khi box giảm dưới 12%, tránh nhấp nháy.

Mỗi camera và góc lắp có tỷ lệ khác nhau. Hãy xem con số `% frame` trên preview, đứng tại vị trí mà
người dùng thực sự thao tác, rồi đặt `bbox_enter_ratio` thấp hơn con số quan sát được một chút.

Nhấn `Q` hoặc `Esc` trong cửa sổ camera để đóng preview. API vẫn tiếp tục chạy; dùng `Ctrl+C`
trong terminal để dừng toàn bộ dịch vụ. Preview chỉ hiển thị cục bộ và không lưu ảnh hoặc video.

Nên kiểm tra thêm các vị trí không dùng để tính homography. Nếu sai số lớn hoặc thay đổi mạnh theo
vị trí, hãy đo lại mốc, tăng số điểm và bảo đảm tất cả điểm đều nằm trên cùng mặt sàn.

## Xử lý sự cố

### Không mở được camera

- Đóng ứng dụng khác đang dùng camera.
- Cho phép ứng dụng desktop truy cập camera trong Windows Privacy & security.
- Chạy lại với quyền truy cập camera trực tiếp.
- Thử đổi `camera.source` từ `0` sang `1` nếu có nhiều camera.

### Cửa sổ OpenCV không mở

Đảm bảo chạy đúng extra giao diện:

```powershell
uv sync --extra visual-calibration
```

Sau đó chạy lại lệnh `calibrate-visual`.

### Vùng ảo méo hoặc nằm ngoài màn hình

- Xác nhận thứ tự giữa `image_points` và `floor_points_m`.
- Không dùng bốn điểm gần như thẳng hàng.
- Thêm nhiều mốc ở các mép và phía xa vùng theo dõi.
- Kiểm tra đơn vị là mét, không phải centimet.
- Hiệu chuẩn lại nếu camera đã bị di chuyển.
