"""
Vi du: dung HumanDetector truc tiep trong Python, khong qua HTTP.

Chi dung duoc khi app chay CUNG moi truong voi package nay (Python 3.10-3.12,
numpy<2, OpenCV<4.12), vd. `uv run python examples/in_process.py --camera 1`.
"""
import argparse
import time

import cv2

from human_detection import DEFAULT_CONFIG, HumanDetector, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", default="0", help="chi so camera OpenCV hoac duong dan video")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    config, checksum = load_config(args.config)
    detector = HumanDetector.load(config, checksum, args.config)
    source = int(args.camera) if args.camera.isdigit() else args.camera
    camera = cv2.VideoCapture(source)
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                break
            result, events = detector.process(frame, time.monotonic() * 1000)
            for event in events:
                print(event["event"], "track", event["track_id"], event["reason"])
            people = len(result["tracks"])
            print(f"\r{people} nguoi, dang dung kiosk: {result['activeTrackId']}, "
                  f"{result['ms']:.0f} ms   ", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()
        detector.close()


if __name__ == "__main__":
    main()
