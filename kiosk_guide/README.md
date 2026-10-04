# kiosk_guide — lớp hướng dẫn từng bước có lồng tiếng

Lớp phủ hướng dẫn cho kiosk: làm sáng phần tử thật trên trang, đọc lời thoại
bằng mp3, chờ người dùng bấm nút hoặc chờ một điều kiện, và đi tiếp được khi
chuyển sang trang khác.

Cả thư mục này dùng độc lập: JavaScript thuần, không cần build, không phụ thuộc
thư viện hay backend nào. Muốn dùng trong app khác thì **chép nguyên thư mục**
vào app đó.

```
kiosk_guide/
├── guide.js             # engine: Tour, Narrator, vùng sáng, chuyển trang giữa chừng
├── guide.css            # giao diện lớp phủ (mọi class có tiền tố kg-)
├── PresenceDetector.js  # chỗ cắm camera nhận diện người — guide.js bắt buộc cần
├── tour-config.js       # KỊCH BẢN của kiosk chứng thực: các bước, lời thoại, selector
├── voice-config.js      # bật/tắt giọng đọc, âm lượng
├── audio/               # mp3, tên file = id của bước (xem audio/README.md)
├── guide-script.csv     # lời thoại từng bước, dùng để thu/sinh mp3
├── check_audio.py       # dò mp3 còn thiếu, lời thoại lệch giữa CSV và tour-config.js
└── demo.html            # trang mẫu chạy độc lập, kịch bản tự viết
```

Xem nhanh: `cd kiosk_guide && python3 -m http.server 8000` rồi mở
<http://localhost:8000/demo.html>.

## 1. Nhúng vào trang

Đặt ở cuối `<body>`, **đúng thứ tự** (đổi `kiosk_guide/` theo nơi bạn để thư mục):

```html
<link rel="stylesheet" href="kiosk_guide/guide.css">   <!-- trong <head> -->

<body data-kiosk-page="home">
    ...
    <script src="kiosk_guide/PresenceDetector.js"></script>
    <script src="kiosk_guide/voice-config.js"></script>
    <script src="kiosk_guide/tour-config.js"></script>
    <script src="kiosk_guide/guide.js"></script>
</body>
```

- `data-kiosk-page` trên `<body>` cho engine biết đang ở trang nào. Trang không có
  thuộc tính này thì hướng dẫn không chạy. Giá trị phải khớp trường `page` của
  các bước trong kịch bản.
- `guide.js` phải là thẻ `<script>` thường (không `type="module"`, không nạp động):
  nó tự tìm `audio/` cạnh chính nó nên không cần sửa đường dẫn mp3.
- Hướng dẫn trải qua nhiều trang thì nhúng như trên ở **mọi** trang đó. Bước đang dở
  được lưu trong `sessionStorage` và trang mới tự đi tiếp.

## 2. Khởi động hướng dẫn

Chưa cắm camera thì engine hiện nút **"Bắt đầu hướng dẫn"** ở góc dưới phải, trên
trang chứa bước đầu tiên (`entryStep`). Khi có nguồn nhận diện người, cắm vào
`PresenceDetector` thì nút tự ẩn, không phải sửa `guide.js`:

```js
const presence = window.KioskGuide.presence;
presence.useSource(emit => {
    // có người đứng trước kiosk -> emit();   người đi rồi -> presence.clear();
    return () => { /* dọn dẹp */ };
});
```

Gọi trực tiếp từ code của app:

| Lệnh | Việc |
|---|---|
| `KioskGuide.start()` / `KioskGuide.start('scan-intro')` | bắt đầu từ bước đầu của trang / từ một bước |
| `KioskGuide.goTo(id)`, `KioskGuide.next()` | nhảy bước |
| `KioskGuide.stop()` | tắt hướng dẫn |
| `KioskGuide.isActive()` | đang chạy không |

Khi hướng dẫn chạy, `<html>` có class `kg-tour-active`. App dùng class này để ẩn
những gì không muốn đè lên lớp phủ, ví dụ `.kg-tour-active #my-panel { display:none }`.

## 3. Viết kịch bản cho app của bạn

Có hai cách:

1. **Dùng lại luồng chứng thực** (trang chủ → màn hình quét giấy tờ): giữ
   `tour-config.js`, chỉ cần DOM của bạn có các selector nó trỏ tới (bảng dưới)
   và khai báo hooks (mục 4).
2. **Luồng khác hẳn**: thay `tour-config.js` bằng file của bạn, cũng gán
   `window.KIOSK_TOUR_CONFIG = { entryStep, steps: [...] }`. `demo.html` là ví dụ
   ngắn. Danh sách đầy đủ các trường của một bước nằm ở đầu `tour-config.js`.

Selector mà `tour-config.js` hiện đang trỏ tới:

| Trang (`page`) | Selector | Phần tử |
|---|---|---|
| `home` | `.feature-card[data-service-id]` | các ô chọn quầy lấy số |
| `home` | `.feature-card[href="index2.html"]` | ô "Dịch vụ chứng thực", bấm vào thì chuyển trang |
| `scan` | `#camera-viewport`, `#video` | khung camera và thẻ video trong đó |
| `scan` | `#capture-btn`, `#reset-btn`, `#certify-btn` | nút Chụp ảnh / Xóa tất cả / Chứng thực |
| `scan` | `.image-item:first-child .delete-btn` | nút X trên ảnh đã chụp (đi kèm luật `.kg-show-delete-btn` trong `guide.css`) |

Không tìm thấy selector sau 10 giây thì bước đó vẫn hiện lời thoại, chỉ không có
vùng sáng, và console có cảnh báo `[guide] khong tim thay muc tieu`.

## 4. Hooks: chỗ kịch bản đọc trạng thái của app

`tour-config.js` chỉ đọc trạng thái app ở 3 hàm. Mặc định chúng đọc `window.App`
của app quét giấy tờ gốc. App khác thì khai báo **trước** khi nạp `tour-config.js`,
không cần sửa file:

```html
<script>
window.KIOSK_GUIDE_HOOKS = {
    documentDetected: () => myScanner.hasDocument,      // camera đã thấy giấy tờ chưa
    capturedCount:    () => myStore.images.length,      // đã chụp bao nhiêu ảnh
    certifySucceeded: () => myState.submitted === true  // đã nộp hồ sơ xong chưa
};
</script>
```

## 5. Giọng đọc

- Tên file mp3 = `id` của bước (`welcome.mp3`, ...), để trong `audio/`. Bước nào thiếu
  mp3 thì chỉ hiện chữ.
- `voice-config.js`: `enabled: false` tắt hẳn tiếng (ẩn nút loa), `volume` 0–1, `dir`
  nếu muốn để mp3 ở chỗ khác.
- Sửa lời thoại thì sửa cả `say` trong `tour-config.js` và `guide-script.csv`, thu lại
  mp3, rồi chạy `python3 kiosk_guide/check_audio.py` để kiểm tra.

## 6. Giao diện

Đổi màu bằng cách ghi đè biến CSS trong stylesheet của app:

```css
:root {
    --kg-accent: #0a7d4f;
    --kg-panel-bg: #fff;
    --kg-panel-fg: #111;
}
```

Lớp phủ dùng `z-index` rất cao (`2147483000+`) để nằm trên mọi thứ. Bước
`modal: false` hạ xuống `40` để modal của app (z-index 50 trở lên) vẫn đè lên được.

## 7. Chế độ dev

Thêm `?dev=1` vào URL (hoặc `localStorage.kiosk_guide_dev = '1'`) để hiện nút
"DEV: bỏ qua bước này" ở các bước đang chờ bấm nút / chờ điều kiện.

## Khoá lưu trữ dùng

`sessionStorage.kiosk_guide_state` (bước đang dở, hết hạn sau 30 phút),
`localStorage.kiosk_guide_muted` (người dùng đã tắt tiếng), `localStorage.kiosk_guide_dev`.
