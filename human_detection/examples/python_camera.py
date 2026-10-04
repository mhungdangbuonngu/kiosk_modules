"""
Vi du: app Python (bat ky phien ban nao) doc camera bang OpenCV, gui frame len
server human_detection, phan ung khi co nguoi dung vao / roi di.

    scripts/run.sh                                  # terminal 1: server
    pip install opencv-python                       # trong moi truong cua APP
    python examples/python_camera.py --camera 1     # terminal 2

App chi can file src/human_detection/client.py (thu vien chuan) + OpenCV de chup.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "human_detection"))
from client import HumanDetectionClient, HumanDetectionError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0, help="chi so camera OpenCV")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--fps", type=float, default=8.0, help="so frame gui moi giay")
    args = parser.parse_args()

    client = HumanDetectionClient(args.url)
    client.wait_until_ready()
    camera = cv2.VideoCapture(args.camera)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    period = 1.0 / args.fps
    try:
        while True:
            started = time.monotonic()
            ok, frame = camera.read()
            if not ok:
                print("Khong doc duoc camera", file=sys.stderr)
                time.sleep(1)
                continue
            # Thu nho truoc khi gui cho nhe; giu ti le khung (engine tu quy doi).
            frame = cv2.resize(frame, (1280, round(1280 * frame.shape[0] / frame.shape[1])))
            jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            try:
                result = client.send_frame(jpeg, timestamp_ms=started * 1000)
            except HumanDetectionError as error:
                print(error, file=sys.stderr)
                time.sleep(1)
                continue
            for event in result["events"]:
                if event["event"] == "USER_ENGAGED":
                    print(f"Co nguoi dung kiosk: track #{event['track_id']}")
                elif event["event"] == "USER_LEFT":
                    print(f"Nguoi dung #{event['track_id']} da roi di ({', '.join(event['reason'])})")
            time.sleep(max(0.0, period - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()


if __name__ == "__main__":
    main()
