from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path

from .capture import LatestFrameCapture
from .config import AppConfig
from .detector import YoloXOnnxDetector
from .head_pose import MediaPipeHeadPose
from .models import EventType, KioskVisionEvent
from .pipeline import VisionPipeline
from .preview import PreviewWindow, render_preview
from .recording import PreviewVideoWriter
from .service import EventBroker
from .telemetry import RuntimeMetrics
from .tracking import ByteTrackAdapter, IoUTracker

logger = logging.getLogger(__name__)


class VisionRuntime:
    def __init__(self, config: AppConfig, pipeline: VisionPipeline, metrics: RuntimeMetrics,
                 broker: EventBroker, development_tracker: bool = False,
                 preview: bool = False, record_preview: str | None = None):
        self.config = config
        self.pipeline = pipeline
        self.metrics = metrics
        self.broker = broker
        self.preview = PreviewWindow(config) if preview else None
        self.recorder = (PreviewVideoWriter(record_preview, config.camera.fps, config.camera.source)
                         if record_preview else None)
        self.capture = LatestFrameCapture(config.camera)
        self.detector = YoloXOnnxDetector(config.detector)
        self.tracker = (IoUTracker(max_missing=config.tracker.track_buffer_frames)
                        if development_tracker else ByteTrackAdapter(
                            config.tracker.track_threshold, config.tracker.match_threshold,
                            config.tracker.track_buffer_frames, config.camera.fps))
        self.head_pose = MediaPipeHeadPose(config.head_pose) if config.head_pose.enabled else None
        self.model_checksums = {"detector": self.detector.model_checksum}
        if self.head_pose:
            self.model_checksums["head_pose"] = hashlib.sha256(
                Path(config.head_pose.model_path).read_bytes()).hexdigest()
            self.model_checksums["face_detector"] = hashlib.sha256(
                Path(config.head_pose.face_detector_model_path).read_bytes()).hexdigest()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self.capture.start()
        self._task = asyncio.create_task(self._run(), name="vision-runtime")

    async def stop(self) -> None:
        self._stop.set()
        try:
            if self._task:
                await self._task
        finally:
            self.capture.stop()
            if self.head_pose:
                self.head_pose.close()
            if self.preview:
                self.preview.close()
            if self.recorder:
                self.recorder.close()

    async def _run(self) -> None:
        sequence, last_inference_ms, last_head_ms = -1, -1, -1
        offline_reported = False
        consecutive_errors = 0
        degraded_reported = False
        while not self._stop.is_set():
            packet = self.capture.latest(sequence)
            if packet is None:
                if not self.capture.online and not offline_reported:
                    await self._publish_system_event(EventType.CAMERA_OFFLINE,
                                                     (self.capture.last_error or "camera_offline",))
                    offline_reported = True
                await asyncio.sleep(0.005)
                continue
            offline_reported = False
            sequence = packet.sequence
            if packet.timestamp_ms - last_inference_ms < self.config.detector.inference_interval_ms:
                await asyncio.sleep(0)
                continue
            started = time.perf_counter()
            try:
                detections = await asyncio.to_thread(self.detector.detect, packet.frame)
                tracked = (self.tracker.update(detections, packet.frame.shape[:2])
                           if isinstance(self.tracker, ByteTrackAdapter)
                           else self.tracker.update(detections))
                # Attach calibrated geometry before selecting head-pose crops.
                events = self.pipeline.update(
                    tracked, packet.timestamp_ms, frame_size=packet.frame.shape[:2])
                heads = {}
                if (self.head_pose and packet.timestamp_ms - last_head_ms >=
                        self.config.head_pose.process_interval_ms):
                    heads = await asyncio.to_thread(self.head_pose.observe, packet.frame,
                                                    list(self.pipeline.tracks.values()), packet.timestamp_ms)
                    last_head_ms = packet.timestamp_ms
                    for track_id, observation in heads.items():
                        if track_id in self.pipeline.tracks:
                            self.pipeline.tracks[track_id].head = observation
                            self.pipeline.tracks[track_id].face_visible = True
                    events.extend(self.pipeline.engine.update(self.pipeline.tracks, packet.timestamp_ms))
                for event in events:
                    await self.broker.publish(event.as_dict())
                    logger.info("vision_event %s", event.as_dict())
                self.metrics.record_frame((time.perf_counter() - started) * 1000, len(events))
                if (self.preview and self.preview.open) or self.recorder:
                    annotated = render_preview(
                        packet.frame, list(self.pipeline.tracks.values()),
                        self.pipeline.engine.active_track_id, self.metrics.snapshot(), self.config)
                if self.recorder:
                    try:
                        await asyncio.to_thread(self.recorder.write, annotated, packet.timestamp_ms)
                    except Exception:
                        logger.exception("preview_recording_failed; recording stopped")
                        self.recorder.close()
                        self.recorder = None
                if self.preview and self.preview.open:
                    try:
                        self.preview.show_rendered(annotated)
                    except Exception:
                        logger.exception("preview_failed")
                        self.preview.close()
                consecutive_errors = 0
                degraded_reported = False
                last_inference_ms = packet.timestamp_ms
            except Exception:
                self.metrics.inference_errors += 1
                consecutive_errors += 1
                logger.exception("vision_frame_failed")
                if consecutive_errors >= 5 and not degraded_reported:
                    await self._publish_system_event(EventType.VISION_DEGRADED,
                                                     ("repeated_inference_errors",))
                    degraded_reported = True
                await asyncio.sleep(0.05)

    async def _publish_system_event(self, kind: EventType, reasons: tuple[str, ...]) -> None:
        event = KioskVisionEvent(time.monotonic_ns() // 1_000_000, kind, None, None, None, 0.0,
                                 reasons)
        await self.broker.publish(event.as_dict())
        self.metrics.record_event()
        logger.warning("vision_event %s", event.as_dict())
