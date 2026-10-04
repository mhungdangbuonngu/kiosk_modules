# File mp3 giọng đọc hướng dẫn

Chỉ dùng **một giọng: nam – miền Bắc**. Tất cả file mp3 để thẳng trong thư mục này:

```
kiosk_guide/audio/
├── welcome.mp3
├── pick-ticket.mp3
└── ...
```

## Quy tắc đặt tên file

**Tên file = `id` của bước + `.mp3`**. Đủ bộ là 13 file:

| File mp3 | Nội dung đọc |
| --- | --- |
| `welcome.mp3` | Lời chào, hỏi chọn chứng thực hay lấy số |
| `pick-ticket.mp3` | Mời chọn quầy |
| `ticket-done.mp3` | Đang in phiếu, mời ngồi chờ |
| `pick-certify.mp3` | Mời chạm ô Dịch vụ chứng thực |
| `scan-intro.mp3` | Giới thiệu màn hình chứng thực |
| `scan-controls.mp3` | Giới thiệu các nút thao tác phía dưới |
| `scan-place.mp3` | Hướng dẫn đặt giấy tờ vào hộp quét |
| `scan-align.mp3` | Hướng dẫn căn chỉnh giấy tờ |
| `scan-capture.mp3` | Hướng dẫn bấm nút Chụp ảnh |
| `scan-reset.mp3` | Giải thích nút Xóa tất cả |
| `scan-delete-one.mp3` | Cách xóa riêng một ảnh bằng dấu X trên ảnh |
| `scan-submit.mp3` | Chụp thêm trang hoặc bấm Chứng thực để nộp |
| `scan-done.mp3` | Hoàn tất, mời lấy lại giấy tờ |

Lời thoại đầy đủ để sinh giọng nói nằm trong [`../guide-script.csv`](../guide-script.csv)
(cột `text_to_speak` là phần cần đọc, cột `audio_file` là tên file phải đặt).
Lời thoại gốc mà màn hình hiển thị nằm ở trường `say` trong
[`../tour-config.js`](../tour-config.js) — sửa lời thoại thì sửa cả hai chỗ và thu lại mp3.

## Bật/tắt giọng đọc

Trong [`../voice-config.js`](../voice-config.js): đặt `enabled: false` để tắt tiếng
hoàn toàn (ẩn luôn nút loa), `volume` để chỉnh âm lượng (0.0 – 1.0).

## Nút bật/tắt tiếng cho người dân

Góc phải bảng thoại có nút loa 🔊 / 🔇 — chạm để tắt hoặc bật tiếng.

- Lựa chọn được nhớ lại (localStorage), giữ nguyên khi chuyển từ trang chủ sang màn hình chứng thực.
- Bật lại tiếng → đọc lại lời thoại của bước đang đứng.

## Kiểm tra đã đủ file chưa

```
python kiosk_guide/check_audio.py
```

Script báo file mp3 còn thiếu, và cảnh báo nếu `guide-script.csv` lệch với
danh sách bước hoặc lời thoại trong `tour-config.js`.

## Lưu ý

- Thiếu file mp3 nào thì bước đó **chỉ hiện chữ**, hướng dẫn vẫn chạy bình thường — không lỗi.
- Đang đọc dở mà người dùng sang bước khác → tiếng cũ bị cắt ngay, phát tiếng bước mới.
- Trình duyệt chặn tự phát tiếng khi vừa chuyển trang (chưa có thao tác nào) → hệ thống
  tự phát lại ngay khi người dùng chạm vào màn hình lần đầu.
