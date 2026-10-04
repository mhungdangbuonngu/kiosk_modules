"""
HumanDetector — nhan dien nguoi dung dang dung truoc kiosk tu tung frame camera.

Moi frame di dung trinh tu cua kiosk_vision/runtime.py (VisionRuntime._run):
YOLOX -> ByteTrack -> VisionPipeline.update (homography san, 3 vung, % khung cua
tung nguoi, trang thai) -> [head pose (YuNet + MediaPipe) -> EngagementEngine.update
lan nua, neu YAML bat head_pose]. Nguoi dung kiosk = nguoi co khung chiem tu
engagement.bbox_enter_ratio dien tich frame tro len, roi di khi xuong duoi
bbox_exit_ratio; vung tren san chi de xem, khong quyet dinh.

Khac runtime.py o cho KHONG tu mo camera: app goi process(frame) / process_jpeg(bytes)
voi frame tu bat ky nguon nao (OpenCV, trinh duyet POST len, video...). Upstream
(kiosk_vision) sua _run thi phai sua theo process() o duoi.

Dung trong Python (cung moi truong Python 3.10-3.12 voi package nay):

    from human_detection import HumanDetector, load_config
    config, checksum = load_config("config/kiosk.yaml")
    detector = HumanDetector.load(config, checksum)
    result, events = detector.process(frame_bgr)      # frame numpy BGR

Khong cung moi truong duoc (vd. app Python 3.13 / numpy 2, Node, C#...) thi chay
server.py thanh tien trinh rieng va goi qua HTTP — xem client.py.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import kiosk_vision
from kiosk_vision.config import AppConfig, DetectorConfig
from kiosk_vision.detector import YoloXOnnxDetector
from kiosk_vision.engagement import EngagementEngine
from kiosk_vision.geometry import SpatialMapper
from kiosk_vision.head_pose import MediaPipeHeadPose
from kiosk_vision.models import EventType, KioskVisionEvent, PersonTrack
from kiosk_vision.pipeline import VisionPipeline
from kiosk_vision.tracking import ByteTrackAdapter, IoUTracker

logger = logging.getLogger("human_detection")

# Goc thu muc human_detection/ (chua models/, config/). Chi dung khi chay tu ma nguon;
# cai dat noi khac thi truyen root= hoac dat bien moi truong HUMAN_DETECTION_HOME.
PROJECT_ROOT = Path(os.environ.get("HUMAN_DETECTION_HOME") or Path(__file__).resolve().parents[2])
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "kiosk.yaml"

# Ten vung trong JSON tra ve -> truong tuong ung trong CalibrationConfig.
ZONES = (
    ("detection", "detection_polygon_m"),
    ("approach", "approach_polygon_m"),
    ("interaction", "interaction_polygon_m"),
)


def auto_threads(n) -> int:
    """So luong ONNX Runtime cho YOLOX. 0 = tu chon: nua so CPU logic, toi da 8.

    Cung cong thuc voi camera 1 (yolo_detector._auto_threads). Mac dinh ONNX
    Runtime dung HET nhan vat ly: tren may dev 256 luong do duoc ~400ms/frame,
    gioi han 8 luong chi con ~20ms.
    """
    n = int(n or 0)
    if n > 0:
        return n
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def make_detector(config: DetectorConfig, threads: int) -> YoloXOnnxDetector:
    """YoloXOnnxDetector goc, thay session ONNX Runtime bang session gioi han so luong.

    Detector goc khong cho truyen so luong, nen lam nhu camera 1
    (yolo_detector._tune_onnx_session): tao session moi roi thay vao.
    """
    import onnxruntime as ort

    detector = YoloXOnnxDetector(config)
    options = ort.SessionOptions()
    options.enable_profiling = False
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    detector.session = ort.InferenceSession(config.model_path, options,
                                            providers=detector.session.get_providers())
    detector.input_name = detector.session.get_inputs()[0].name
    return detector


def resolve_model_paths(config: AppConfig, root: Path) -> AppConfig:
    """Duong dan model tuong doi trong YAML tinh tu thu muc goc human_detection/.

    kiosk-vision goc chay voi thu muc hien hanh la goc project nen YAML de duong
    dan tuong doi; tien trinh nay thi co the duoc chay tu bat ky dau.
    """
    def absolute(path: str) -> str:
        return path if Path(path).is_absolute() else str(root / path)

    return config.model_copy(update={
        "detector": config.detector.model_copy(
            update={"model_path": absolute(config.detector.model_path)}),
        "head_pose": config.head_pose.model_copy(update={
            "model_path": absolute(config.head_pose.model_path),
            "face_detector_model_path": absolute(config.head_pose.face_detector_model_path),
        }),
    })


def scaled_homography(homography, calibration_size, frame_size) -> list[list[float]]:
    """Homography cho frame co kich thuoc `frame_size`.

    H goc doi pixel cua khung hieu chuan -> met tren san. Frame gui len co the nho
    hon (trinh duyet thu nho cho nhe duong truyen), nen doi pixel frame ve pixel
    khung hieu chuan truoc roi moi ap H. Chi dung khi hai khung cung ti le — lech
    ti le nghia la camera dang cat/khac mode, toa do san se sai (xem aspect_mismatch).
    """
    cw, ch = calibration_size
    fw, fh = frame_size
    scale = np.diag([cw / fw, ch / fh, 1.0])
    return (np.asarray(homography, dtype=np.float64) @ scale).tolist()


def floor_to_image(homography, frame_size) -> np.ndarray:
    """Nghich dao cua H (met -> pixel), doi dau sao cho diem san NHIN THAY co w > 0.

    Homography chi xac dinh sai khac mot he so, ke ca DAU: H va -H cho cung toa do
    san, va cong cu hieu chuan tra ve dau nao cung duoc (H cua video hieu chuan
    20261001 cho w < 0 o moi diem truoc camera). project_zone lai dua vao dau cua w
    de bo phan sau camera, nen chuan dau theo diem giua mep duoi frame — chac chan
    la san truoc kiosk.
    """
    h = np.asarray(homography, dtype=np.float64)
    inverse = np.linalg.inv(h)
    fw, fh = frame_size
    return -inverse if (h @ np.array([fw / 2, fh, 1.0]))[2] < 0 else inverse


def project_zone(inverse: np.ndarray, polygon_m) -> list[list[float]] | None:
    """Da giac tren san (met) -> da giac tren anh, bo phan nam SAU camera.

    Diem san sau mat phang anh cho w <= 0: chia cho w se lat no sang phia ben kia
    va ve ra hinh rac. Cat da giac tai w = eps trong toa do dong nhat (phep chieu
    tuyen tinh o do nen noi suy thang la dung) roi moi chia.
    """
    points = [inverse @ np.array([x, y, 1.0]) for x, y in polygon_m]
    w_max = max(point[2] for point in points)
    if w_max <= 0:
        return None
    eps = 1e-3 * w_max
    clipped = []
    for i, current in enumerate(points):
        previous = points[i - 1]
        if (current[2] > eps) != (previous[2] > eps):
            t = (eps - previous[2]) / (current[2] - previous[2])
            clipped.append(previous + t * (current - previous))
        if current[2] > eps:
            clipped.append(current)
    if len(clipped) < 3:
        return None
    return [[round(float(p[0] / p[2]), 1), round(float(p[1] / p[2]), 1)] for p in clipped]


def _num(value, digits: int):
    """So -> so da lam tron; None/NaN/vo cuc -> None (JSON khong chua duoc NaN).

    Chan dung ngang duong chan troi thi homography cho toa do vo cuc — hiem,
    nhung mot gia tri NaN la ca response 500.
    """
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def _pair(values, digits: int):
    return None if values is None else [_num(value, digits) for value in values]


def _event_json(event: KioskVisionEvent) -> dict:
    """Su kien giu nguyen dinh dang cua kiosk-intent (/events, /events/ws)."""
    data = event.as_dict()
    data["distance_m"] = _num(data["distance_m"], 3)
    data["facing_score"] = _num(data["facing_score"], 3)
    return data


class HumanDetector:
    """Giu trang thai giua cac frame: tracker, cac track va may trang thai tuong tac.

    Frame phai toi DUNG thu tu thoi gian va tu MOT camera: hai trang cung day frame
    thi hai dong thoi gian xen nhau, track nhay lung tung.
    """

    def __init__(self, config: AppConfig, checksum: str, detector, head_pose,
                 calibration_frame: tuple[int, int] | None = None,
                 development_tracker: bool = False, onnx_threads: int | None = None,
                 config_path: str | None = None):
        self.config = config
        self.checksum = checksum
        self.config_path = config_path
        self.detector = detector
        self.head_pose = head_pose
        self.development_tracker = development_tracker
        self.onnx_threads = onnx_threads
        self.model_checksums: dict[str, str] = {}
        if calibration_frame:
            self.calibration_frame = (int(calibration_frame[0]), int(calibration_frame[1]))
            self.calibration_frame_source = "argument"
        else:
            self.calibration_frame = (config.camera.width, config.camera.height)
            self.calibration_frame_source = "kiosk YAML camera.width/height"
        # /health va /tracks cua kiosk-intent giu tham chieu toi DUNG object nay, nen
        # doi co frame hay reset deu sua ben trong chu khong tao pipeline moi.
        self.pipeline = VisionPipeline(config)
        self.tracker = self._make_tracker()
        self.frame_size: tuple[int, int] | None = None
        self.zones_image: dict[str, list[list[float]] | None] = {}
        self._lock = threading.Lock()
        self._last_timestamp_ms: int | None = None
        self._last_head_ms: int | None = None

    @classmethod
    def load(cls, config: AppConfig, checksum: str, config_path: str | None = None,
             calibration_frame: tuple[int, int] | None = None, onnx_threads: int = 0,
             development_tracker: bool = False, root: Path | str | None = None) -> HumanDetector:
        """Nap model that theo cau hinh YAML. Duong dan model tuong doi tinh tu `root`."""
        config = resolve_model_paths(config, Path(root) if root else PROJECT_ROOT)
        threads = auto_threads(onnx_threads)
        detector = make_detector(config.detector, threads)
        head_pose = MediaPipeHeadPose(config.head_pose) if config.head_pose.enabled else None
        engine = cls(config, checksum, detector, head_pose, calibration_frame,
                     development_tracker, threads, config_path)
        engine.model_checksums["detector"] = detector.model_checksum
        if head_pose:
            for name, path in (("face_detector", config.head_pose.face_detector_model_path),
                               ("head_pose", config.head_pose.model_path)):
                engine.model_checksums[name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return engine

    def close(self) -> None:
        if self.head_pose:
            self.head_pose.close()

    # ---------- trang thai ----------

    def _make_tracker(self):
        tracker = self.config.tracker
        if self.development_tracker:
            return IoUTracker(max_missing=tracker.track_buffer_frames)
        return ByteTrackAdapter(tracker.track_threshold, tracker.match_threshold,
                                tracker.track_buffer_frames, self.config.camera.fps)

    def aspect_mismatch(self, size: tuple[int, int]) -> bool:
        cw, ch = self.calibration_frame
        return abs((size[0] / size[1]) / (cw / ch) - 1.0) > 0.01

    def _set_frame_size(self, size: tuple[int, int]) -> None:
        """Doi homography va vung ve tren anh theo co frame dang nhan."""
        homography = scaled_homography(self.config.calibration.homography,
                                       self.calibration_frame, size)
        calibration = self.config.calibration.model_copy(update={"homography": homography})
        self.pipeline.mapper = SpatialMapper(calibration)
        inverse = floor_to_image(homography, size)
        self.zones_image = {name: project_zone(inverse, getattr(calibration, attribute))
                            for name, attribute in ZONES}
        self.frame_size = size
        cw, ch = self.calibration_frame
        if self.aspect_mismatch(size):
            logger.warning("frame %dx%d KHAC ti le khung hieu chuan %dx%d (%s) — toa do san "
                           "se sai. Kiem tra camera/do phan giai hoac hieu chuan lai.",
                           size[0], size[1], cw, ch, self.calibration_frame_source)
        else:
            logger.info("frame %dx%d, khung hieu chuan %dx%d -> he so %.3f",
                        size[0], size[1], cw, ch, cw / size[0])

    def _end_session(self, reason: str) -> list[KioskVisionEvent]:
        """Bo het track. Nguoi dang tuong tac thi phat USER_LEFT de ben nghe dong phien."""
        events = [
            KioskVisionEvent(self._last_timestamp_ms, EventType.USER_LEFT, track.id,
                             track.distance_to_kiosk, track.facing_score, 1.0, (reason,))
            for track in self.pipeline.tracks.values()
            if track.emitted_engaged and self._last_timestamp_ms is not None
        ]
        self.pipeline.tracks.clear()
        self.pipeline.engine = EngagementEngine(self.config.engagement, self.config.head_pose)
        self.tracker = self._make_tracker()
        self._last_timestamp_ms = None
        self._last_head_ms = None
        return events

    def reset(self) -> list[dict]:
        with self._lock:
            events = self._end_session("session_reset")
        return [_event_json(event) for event in events]

    # ---------- xu ly frame ----------

    def process_jpeg(self, content: bytes, timestamp_ms: float | None = None):
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Khong doc duoc anh")
        return self.process(frame, timestamp_ms)

    def process(self, frame: np.ndarray, timestamp_ms: float | None = None):
        """Mot frame -> (ket qua cho trang goi, cac su kien moi).

        `timestamp_ms` la dong ho don dieu cua ben CHUP frame (performance.now() cua
        trinh duyet), de van toc khong bi lech theo do tre mang. Khong gui thi lay
        dong ho cua tien trinh nay luc nhan. Dong ho di lui (trang vua tai lai,
        performance.now() dem lai tu 0) = phien moi.
        """
        if frame is None or frame.size == 0:
            raise ValueError("Frame rong")
        with self._lock:
            now_ms = (int(timestamp_ms) if timestamp_ms is not None
                      else time.monotonic_ns() // 1_000_000)
            size = (int(frame.shape[1]), int(frame.shape[0]))
            events: list[KioskVisionEvent] = []
            notes: list[str] = []
            if self._last_timestamp_ms is not None and now_ms < self._last_timestamp_ms:
                events += self._end_session("clock_reset")
                notes.append("clock_reset")
            if size != self.frame_size:
                if self.frame_size is not None:
                    events += self._end_session("frame_size_changed")
                    notes.append("frame_size_changed")
                self._set_frame_size(size)
            self._last_timestamp_ms = now_ms

            # Tu day den het la VisionRuntime._run cua kiosk-intent, bo phan doc camera.
            started = time.perf_counter()
            detections = self.detector.detect(frame)
            tracked = (self.tracker.update(detections, frame.shape[:2])
                       if isinstance(self.tracker, ByteTrackAdapter)
                       else self.tracker.update(detections))
            # Gan toa do san + vung truoc, head pose chon nguoi can xet theo vung.
            # frame_size: % khung tinh tren chinh frame gui len, khong phai co trong YAML.
            events += self.pipeline.update(tracked, now_ms, frame_size=frame.shape[:2])
            head_ms = None
            if self.head_pose and (self._last_head_ms is None or now_ms - self._last_head_ms
                                   >= self.config.head_pose.process_interval_ms):
                head_started = time.perf_counter()
                heads = self.head_pose.observe(frame, list(self.pipeline.tracks.values()), now_ms)
                head_ms = (time.perf_counter() - head_started) * 1000
                self._last_head_ms = now_ms
                for track_id, observation in heads.items():
                    if track_id in self.pipeline.tracks:
                        self.pipeline.tracks[track_id].head = observation
                        self.pipeline.tracks[track_id].face_visible = True
                events += self.pipeline.engine.update(self.pipeline.tracks, now_ms)
            total_ms = (time.perf_counter() - started) * 1000

            active = self.pipeline.engine.active_track_id
            event_dicts = [_event_json(event) for event in events]
            cw, ch = self.calibration_frame
            result = {
                "timestampMs": now_ms,
                # Moi toa do pixel ben duoi theo chinh anh gui len.
                "frame": {"width": size[0], "height": size[1]},
                "calibration": {
                    "frame": {"width": cw, "height": ch},
                    "scale": [round(cw / size[0], 4), round(ch / size[1], 4)],
                    "aspectMismatch": self.aspect_mismatch(size),
                },
                "ms": round(total_ms, 1),
                "timing": {
                    "detectorMs": _num(getattr(self.detector, "last_latency_ms", None), 1),
                    "headPoseMs": _num(head_ms, 1),
                },
                "activeTrackId": active,
                "tracks": [self._track_json(track, now_ms, active)
                           for track in self.pipeline.tracks.values()],
                "events": event_dicts,
                "zones": self.zones_image,
                "notes": notes,
            }
        return result, event_dicts

    @staticmethod
    def _track_json(track: PersonTrack, now_ms: int, active_id: int | None) -> dict:
        head = track.head
        return {
            "id": track.id,
            "state": track.state.value,
            # False = frame nay khong thay, dang giu trong lost_track_ms cho khoi mat phien.
            "seen": track.last_seen_ms == now_ms,
            "active": track.id == active_id,
            "bbox": [round(float(v), 1) for v in track.bbox],
            # Dien tich khung (cat theo mep frame) / dien tich frame — dai luong quyet dinh ENGAGED.
            "bboxAreaRatio": _num(track.bbox_area_ratio, 4),
            "confidence": _num(track.confidence, 3),
            "footPoint": _pair(track.foot_point, 1),
            "worldXY": _pair(track.world_xy, 3),
            "distanceM": _num(track.distance_to_kiosk, 3),
            "velocityMps": _pair(track.velocity_xy, 3),
            # Am = dang tien lai gan kiosk.
            "radialVelocityMps": _num(track.radial_velocity_mps, 3),
            "zones": {
                "detection": track.in_detection_zone,
                "approach": track.in_approach_zone,
                "interaction": track.in_interaction_zone,
            },
            "faceVisible": track.face_visible,
            "facingScore": _num(track.facing_score, 3),
            "head": None if head is None else {
                "yawDeg": _num(head.yaw_deg, 1),
                "pitchDeg": _num(head.pitch_deg, 1),
                "ageMs": now_ms - head.timestamp_ms,
            },
            "ageMs": track.age_ms,
            "stateMs": now_ms - track.state_since_ms,
        }

    def status(self, metrics: dict | None = None) -> dict:
        calibration = self.config.calibration
        head = self.config.head_pose
        cw, ch = self.calibration_frame
        return {
            "engine": "kiosk-intent",
            "version": kiosk_vision.__version__,
            "config": self.config_path,
            "configChecksum": self.checksum,
            "calibrationFrame": {"width": cw, "height": ch,
                                 "source": self.calibration_frame_source},
            "frameSize": (None if self.frame_size is None
                          else {"width": self.frame_size[0], "height": self.frame_size[1]}),
            "kioskXY": list(calibration.kiosk_xy_m),
            "zonesM": {name: [list(point) for point in getattr(calibration, attribute)]
                       for name, attribute in ZONES},
            "headPose": self.head_pose is not None,
            "headPoseLimits": {"maxYawDeg": head.max_yaw_deg, "maxPitchDeg": head.max_pitch_deg,
                               "observationTtlMs": head.observation_ttl_ms},
            "engagement": self.config.engagement.model_dump(),
            "tracker": "IoU (development)" if self.development_tracker else "ByteTrack",
            "onnxThreads": self.onnx_threads,
            "modelChecksums": self.model_checksums,
            "activeTrackId": self.pipeline.engine.active_track_id,
            "tracks": len(self.pipeline.tracks),
            "metrics": metrics,
        }
