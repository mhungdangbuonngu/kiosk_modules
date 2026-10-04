"""
Server HTTP cua human_detection — chay thanh tien trinh rieng de app khac goi vao.

Dung khi app cua ban KHONG chay chung moi truong Python voi package nay (MediaPipe
<=0.10.21 chi co wheel toi Python 3.12, va package khoa numpy<2, OpenCV<4.12).

    uv run human-detection                                  # config/kiosk.yaml, 127.0.0.1:8765
    uv run human-detection --config duong/dan.yaml --port 8766 --calibration-frame 1920x1080
    uv run human-detection --cors-origin http://localhost:3000   # cho trinh duyet goi thang

Endpoint — mac dinh chi nghe 127.0.0.1, khong co xac thuc:
    POST /frame?timestampMs=   than request = mot anh JPEG/PNG -> track + su kien + vung
    POST /reset                bo het track, bat dau phien moi
    GET  /status               cau hinh dang chay (vung tren san, khung hieu chuan...)
    GET  /health, /tracks, /events, WS /events/ws    giu nguyen cua kiosk-vision

Frame nhan nguyen byte anh trong than request (khong multipart): moi truong da khoa
khong co python-multipart, va cung khoi boc/go them mot lop.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request

import kiosk_vision
from kiosk_vision.config import load_config
from kiosk_vision.service import create_app

from .engine import DEFAULT_CONFIG, HumanDetector

logger = logging.getLogger("human_detection")


def create_server_app(detector: HumanDetector, cors_origins: list[str] | None = None) -> FastAPI:
    """App cua kiosk-vision (/health, /tracks, /events, /events/ws) + endpoint nhan frame."""
    app = create_app(detector.config, detector.checksum, pipeline=detector.pipeline,
                     run_vision=False)
    broker, metrics = app.state.broker, app.state.metrics
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins,
                           allow_methods=["GET", "POST"], allow_headers=["*"])

    async def publish(events: list[dict]) -> None:
        for event in events:
            await broker.publish(event)
            logger.info("vision_event %s", event)

    @app.post("/frame")
    async def frame(request: Request, timestampMs: float | None = None):
        content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail="Than request rong, can mot anh JPEG")
        try:
            result, events = await asyncio.to_thread(detector.process_jpeg, content, timestampMs)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            metrics.inference_errors += 1
            logger.exception("frame_failed")
            raise HTTPException(status_code=500, detail=f"Loi xu ly frame: {error}") from error
        metrics.record_frame(result["ms"], len(events))
        await publish(events)
        return result

    @app.post("/reset")
    async def reset():
        events = await asyncio.to_thread(detector.reset)
        await publish(events)
        return {**detector.status(metrics.snapshot()), "events": events}

    @app.get("/status")
    async def status():
        return detector.status(metrics.snapshot())

    return app


def _frame_size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"can dang RONGxCAO, vd. 1920x1080 (nhan {text!r})")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("rong/cao phai > 0")
    return width, height


def main(argv=None) -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(
        prog="human-detection",
        description="Server nhan dien nguoi dung kiosk: POST frame -> track + su kien.")
    parser.add_argument("--config", default=env("HUMAN_DETECTION_CONFIG", str(DEFAULT_CONFIG)),
                        help="file YAML (mac dinh: config/kiosk.yaml)")
    parser.add_argument("--host", default=env("HUMAN_DETECTION_HOST"),
                        help="mac dinh lay service.host trong YAML (127.0.0.1)")
    parser.add_argument("--port", type=int, default=env("HUMAN_DETECTION_PORT"),
                        help="mac dinh lay service.port trong YAML (8765)")
    parser.add_argument("--calibration-frame", type=_frame_size,
                        default=env("HUMAN_DETECTION_CALIBRATION_FRAME"),
                        help="co khung luc hieu chuan homography, vd. 1920x1080 "
                             "(mac dinh: camera.width x camera.height trong YAML)")
    parser.add_argument("--onnx-threads", type=int, default=env("HUMAN_DETECTION_ONNX_THREADS", 0),
                        help="so luong ONNX Runtime cho YOLOX; 0 = tu chon (nua so CPU, toi da 8)")
    parser.add_argument("--cors-origin", action="append", default=None,
                        help="cho phep trang web o origin nay goi thang (lap lai duoc; '*' = tat ca)")
    parser.add_argument("--development-tracker", action="store_true",
                        help="tracker IoU don gian thay ByteTrack, chi de do loi")
    args = parser.parse_args(argv)
    if isinstance(args.calibration_frame, str):     # gia tri tu bien moi truong
        args.calibration_frame = _frame_size(args.calibration_frame)

    config, checksum = load_config(args.config)
    logging.basicConfig(level=config.service.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    host = args.host or config.service.host
    port = int(args.port or config.service.port)

    detector = HumanDetector.load(config, checksum, args.config, args.calibration_frame,
                                  args.onnx_threads, args.development_tracker)
    cw, ch = detector.calibration_frame
    logger.info("kiosk-vision %s, cau hinh %s (%s)", kiosk_vision.__version__,
                args.config, checksum[:12])
    logger.info("khung hieu chuan %dx%d (%s), YOLOX %d luong, head pose %s, tracker %s",
                cw, ch, detector.calibration_frame_source, detector.onnx_threads,
                "bat" if detector.head_pose else "TAT", detector.status()["tracker"])
    logger.info("nghe http://%s:%d", host, port)
    try:
        # Tat access log: app gui ~8 frame/giay, log tung request la ngap man hinh.
        uvicorn.run(create_server_app(detector, args.cors_origin), host=host, port=port,
                    access_log=False)
    finally:
        detector.close()


if __name__ == "__main__":
    main()
