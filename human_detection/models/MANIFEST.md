# Provisioned models

| Artifact | Source | SHA-256 |
|---|---|---|
| `yolox_nano.onnx` | [YOLOX 0.1.1rc0 release](https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx) | `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` |
| `face_detection_yunet.onnx` | [OpenCV Zoo YuNet](https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `face_landmarker.task` | [MediaPipe Face Landmarker](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task) | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |

Binary model artifacts are provisioned locally and intentionally ignored by Git. The setup script
verifies these hashes after download.

