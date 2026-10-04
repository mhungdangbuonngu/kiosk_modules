# kiosk_modules

Ba module tách ra từ kiosk chứng thực. Module nào cũng tự chứa, không phụ thuộc
module khác, nên có thể chép riêng từng thư mục vào app của bạn.

| Module | Việc | Công nghệ | Hướng dẫn |
|---|---|---|---|
| [`document_scan/`](document_scan/) | Camera số 1: tìm 4 góc tài liệu, cắt và nắn phẳng | Python (ONNX Runtime, OpenCV) + ES module, OpenCV.js | [README](document_scan/README.md) |
| [`human_detection/`](human_detection/) | Camera số 2: phát hiện có người đứng dùng kiosk (`USER_ENGAGED` / `USER_LEFT`) | Python 3.12 (YOLOX-Nano, ByteTrack, MediaPipe) | [README](human_detection/README.md) |
| [`kiosk_guide/`](kiosk_guide/) | Lớp hướng dẫn từng bước có lồng tiếng, trỏ vào phần tử thật trên trang | JavaScript thuần, không cần build | [README](kiosk_guide/README.md) |

## Ghép các module với nhau

- **human_detection → kiosk_guide**: khi nhận sự kiện `USER_ENGAGED` thì bắt đầu
  hướng dẫn, khi nhận `USER_LEFT` thì cho phép chào khách tiếp theo:

  ```js
  KioskGuide.presence.useSource(emit => {
      // USER_ENGAGED -> emit();   USER_LEFT -> KioskGuide.presence.clear();
      return () => { /* dọn dẹp */ };
  });
  ```

- **document_scan → kiosk_guide**: các bước quét giấy tờ trong hướng dẫn đọc trạng
  thái qua `window.KIOSK_GUIDE_HOOKS` (đã thấy giấy tờ chưa, đã chụp mấy ảnh, đã nộp
  xong chưa). Xem `kiosk_guide/README.md` mục 4.

## Model

- `document_scan/backend/models/docscan.onnx` đã có sẵn trong repo.
- Model của `human_detection` không đưa vào git. Chạy `human_detection/scripts/setup.sh`
  (hoặc `setup.ps1` trên Windows) để tải về và kiểm tra SHA-256, xem
  `human_detection/models/MANIFEST.md`.
