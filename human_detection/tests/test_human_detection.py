import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from human_detection.client import HumanDetectionClient
from human_detection.engine import DEFAULT_CONFIG, PROJECT_ROOT, HumanDetector, project_zone
from human_detection.server import create_server_app
from kiosk_vision.config import AppConfig, load_config
from kiosk_vision.models import Detection, HeadObservation


def kiosk_config(head_pose: bool = False) -> AppConfig:
    # Khung hieu chuan 1280x720: u 0..1280 -> x -1..1 m, v 720..0 -> y 0..4 m,
    # tuc chan cham day khung = dung sat kiosk.
    return AppConfig.model_validate({
        "camera": {"width": 1280, "height": 720},
        "calibration": {
            "homography": [[1 / 640, 0, -1], [0, -4 / 720, 4], [0, 0, 1]],
            "kiosk_xy_m": [0, 0],
            "detection_polygon_m": [[-3, 0], [3, 0], [3, 4], [-3, 4]],
            "approach_polygon_m": [[-2, 0.8], [2, 0.8], [2, 2.5], [-2, 2.5]],
            "interaction_polygon_m": [[-1, 0], [1, 0], [1, 1.2], [-1, 1.2]],
        },
        "head_pose": {"enabled": head_pose},
        "engagement": {"bbox_enter_ratio": 0.2, "bbox_exit_ratio": 0.1, "lost_track_ms": 500},
    })


class FakeDetector:
    """Tra ve dung cac khung nguoi dat san, theo toa do cua frame dang xu ly."""

    last_latency_ms = 1.0

    def __init__(self, boxes=()):
        self.boxes = list(boxes)

    def detect(self, frame):
        return [Detection(tuple(map(float, box)), 0.9) for box in self.boxes]


class FakeHeadPose:
    """Moi nguoi trong vung approach/interaction deu nhin thang vao kiosk."""

    def observe(self, frame, tracks, timestamp_ms):
        return {track.id: HeadObservation(timestamp_ms, 0.0, 0.0, 1.0) for track in tracks
                if track.in_interaction_zone or track.in_approach_zone}

    def close(self):
        pass


# Ti le = dien tich khung / 1280x720. Nguong trong kiosk_config: vao 0.2, ra 0.1.
# Moi khung deu dung giua, chan o v=684 -> y = 0.2 m (trong vung interaction).
STANDING = (400, 100, 880, 684)       # 0.304: dung sat kiosk
LEANING_BACK = (480, 150, 800, 684)   # 0.185: duoi nguong vao, tren nguong ra
STEPPING_AWAY = (560, 300, 720, 684)  # 0.067: duoi nguong ra
# Nguoi nho (0.021), chan o v=540 -> y = 1.0 m: VAN trong vung interaction.
PASSING = (600, 300, 680, 540)
FRAME = np.zeros((720, 1280, 3), np.uint8)


def run(engine, times, frame=FRAME):
    events = []
    for t in times:
        result, new = engine.process(frame, t)
        events += new
    return result, events


def engaged_engine(head_pose=None):
    engine = HumanDetector(kiosk_config(head_pose is not None), "abc", FakeDetector([STANDING]),
                            head_pose, calibration_frame=(1280, 720))
    result, events = run(engine, range(1000, 2500, 100))
    return engine, result, events


def test_large_person_engages_at_once_then_leaves_after_grace():
    engine, result, events = engaged_engine()
    assert [(e["event"], e["reason"]) for e in events] == [
        ("USER_ENGAGED", ["bbox_area_ratio_above_enter_threshold"])]
    assert events[0]["timestamp_ms"] == 1000       # khong con cho dwell/huong dau
    track = result["tracks"][0]
    assert track["state"] == "ENGAGED" and track["active"] and track["seen"]
    assert track["bboxAreaRatio"] == pytest.approx(480 * 584 / (1280 * 720), abs=1e-4)
    assert track["worldXY"] == pytest.approx([0.0, 0.2], abs=1e-3)
    assert track["zones"] == {"detection": True, "approach": False, "interaction": True}
    assert track["facingScore"] is None            # head pose tat

    engine.detector.boxes = []
    result, new = engine.process(FRAME, 2500)       # con trong lost_track_ms: giu nguyen
    assert new == [] and result["tracks"][0]["seen"] is False
    result, new = engine.process(FRAME, 3100)
    assert [(e["event"], e["reason"]) for e in new] == [("USER_LEFT", ["track_lost"])]
    assert result["tracks"] == []


def test_small_person_in_interaction_zone_never_engages():
    # Vung tren san khong con quyet dinh: chi % khung.
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector([PASSING]), None,
                            calibration_frame=(1280, 720))
    result, events = run(engine, range(1000, 4000, 100))
    assert events == [] and result["activeTrackId"] is None
    track = result["tracks"][0]
    assert track["zones"]["interaction"] and track["state"] == "PRESENT"
    assert track["bboxAreaRatio"] == pytest.approx(80 * 240 / (1280 * 720), abs=1e-4)


def test_hysteresis_keeps_user_between_thresholds_and_releases_below_exit():
    engine, _, _ = engaged_engine()
    engine.detector.boxes = [LEANING_BACK]
    result, events = run(engine, range(2500, 3500, 100))
    assert events == [] and result["tracks"][0]["state"] == "ENGAGED"

    engine.detector.boxes = [STEPPING_AWAY]
    result, events = run(engine, range(3500, 4500, 100))
    assert [(e["event"], e["reason"]) for e in events] == [
        ("USER_LEFT", ["bbox_area_ratio_below_exit_threshold"])]
    assert result["activeTrackId"] is None and result["tracks"][0]["state"] == "PRESENT"


def test_downscaled_frame_gives_same_ratio_and_engages():
    # Trinh duyet gui frame nho hon khung hieu chuan: % khung phai tinh tren chinh
    # frame do, khong phai co camera.width/height trong YAML (se ra 1/4 -> khong ENGAGED).
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector([(200, 50, 440, 342)]), None,
                            calibration_frame=(1280, 720))
    result, events = engine.process(np.zeros((360, 640, 3), np.uint8), 0)
    assert [e["event"] for e in events] == ["USER_ENGAGED"]
    track = result["tracks"][0]
    assert track["bboxAreaRatio"] == pytest.approx(480 * 584 / (1280 * 720), abs=1e-4)
    assert track["worldXY"] == pytest.approx([0.0, 0.2], abs=1e-3)


def test_smaller_frame_with_same_aspect_maps_to_same_floor_point():
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector([(280, 100, 360, 342)]), None,
                            calibration_frame=(1280, 720))
    result, _ = engine.process(np.zeros((360, 640, 3), np.uint8), 0)
    assert result["calibration"] == {"frame": {"width": 1280, "height": 720},
                                     "scale": [2.0, 2.0], "aspectMismatch": False}
    assert result["tracks"][0]["worldXY"] == pytest.approx([0.0, 0.2], abs=1e-3)
    # Vung ve theo toa do cua chinh frame gui len: y = 0 m nam o day frame 640x360.
    assert max(v for _, v in result["zones"]["interaction"]) == pytest.approx(360, abs=0.5)


def test_other_aspect_ratio_is_flagged():
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector(), None,
                            calibration_frame=(1280, 720))
    result, _ = engine.process(np.zeros((480, 640, 3), np.uint8), 0)
    assert result["calibration"]["aspectMismatch"] is True


def test_calibration_frame_falls_back_to_yaml_camera_size():
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector(), None)
    assert engine.calibration_frame == (1280, 720)
    assert engine.status()["calibrationFrame"]["source"] == "kiosk YAML camera.width/height"


def test_clock_going_backwards_closes_the_session():
    engine, _, _ = engaged_engine()
    result, new = engine.process(FRAME, 5)          # trang tai lai: performance.now() ve 0
    assert result["notes"] == ["clock_reset"]
    # Phien cu dong; nguoi van dung do nen phien moi (track moi) ENGAGED lai ngay.
    assert [(e["event"], e["reason"]) for e in new] == [
        ("USER_LEFT", ["clock_reset"]),
        ("USER_ENGAGED", ["bbox_area_ratio_above_enter_threshold"])]
    assert [(t["state"], t["ageMs"]) for t in result["tracks"]] == [("ENGAGED", 0)]


def test_frame_size_change_starts_a_new_session():
    engine, _, _ = engaged_engine()
    engine.detector.boxes = [(280, 100, 360, 342)]
    result, new = engine.process(np.zeros((360, 640, 3), np.uint8), 2600)
    assert result["notes"] == ["frame_size_changed"]
    assert [e["event"] for e in new] == ["USER_LEFT"]


def test_zone_projection_drops_the_part_behind_the_camera():
    # Anh dong nhat (u, v, w) = (x, y, y - 1): diem san co y < 1 nam sau camera.
    inverse = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, -1.0]])
    polygon = project_zone(inverse, [(-1, 0), (1, 0), (1, 3), (-1, 3)])
    assert len(polygon) == 4
    assert all(np.isfinite(value) for point in polygon for value in point)
    assert all(v > 0 for _, v in polygon)          # khong co dinh nao bi lat sang phia kia
    assert project_zone(inverse, [(-1, 0), (1, 0), (1, 0.5)]) is None


def test_negated_homography_projects_the_same_zones():
    # H va -H la cung mot phep chieu; cong cu hieu chuan co the tra ve dau nao cung duoc.
    config = kiosk_config()
    flipped = config.model_copy(update={"calibration": config.calibration.model_copy(update={
        "homography": (-np.asarray(config.calibration.homography)).tolist()})})
    zones = [HumanDetector(c, "abc", FakeDetector([STANDING]), None, calibration_frame=(1280, 720))
             .process(FRAME, 0)[0] for c in (config, flipped)]
    assert all(zones[0]["zones"].values())
    assert zones[1]["zones"] == zones[0]["zones"]
    assert zones[1]["tracks"][0]["worldXY"] == zones[0]["tracks"][0]["worldXY"]


def test_http_frame_status_reset_and_upstream_endpoints_share_state():
    # Bat head pose trong YAML: engine.update chay them lan nua sau head pose,
    # khong duoc phat trung su kien.
    engine = HumanDetector(kiosk_config(head_pose=True), "abc", FakeDetector([STANDING]),
                            FakeHeadPose(), calibration_frame=(1280, 720))
    jpeg = cv2.imencode(".jpg", FRAME)[1].tobytes()
    with TestClient(create_server_app(engine)) as client:
        for t in range(1000, 2500, 100):
            response = client.post("/frame", content=jpeg, params={"timestampMs": t},
                                   headers={"Content-Type": "image/jpeg"})
            assert response.status_code == 200
        assert response.json()["activeTrackId"] is not None
        assert response.json()["tracks"][0]["facingScore"] == pytest.approx(1.0)
        # /events va /tracks la cua kiosk-intent: phai thay dung phien vua chay.
        assert [e["event"] for e in client.get("/events").json()] == ["USER_ENGAGED"]
        assert client.get("/tracks").json()[0]["state"] == "ENGAGED"
        assert client.get("/health").json()["active_track_id"] is not None

        status = client.post("/reset").json()
        assert status["tracks"] == 0 and status["activeTrackId"] is None
        assert [(e["event"], e["reason"]) for e in status["events"]] == [
            ("USER_LEFT", ["session_reset"])]
        assert client.get("/events").json()[-1]["reason"] == ["session_reset"]
        assert status["metrics"]["frames_processed"] == 15

        assert client.post("/frame", content=b"khong phai anh").status_code == 400
        assert client.post("/frame", content=b"").status_code == 400


VIDEO_YAML = PROJECT_ROOT / "config" / "kiosk.video.yaml"


def test_cors_is_off_by_default_and_on_when_asked():
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector(), None)
    headers = {"Origin": "http://app.local", "Access-Control-Request-Method": "POST"}
    with TestClient(create_server_app(engine)) as client:
        assert "access-control-allow-origin" not in client.options("/frame", headers=headers).headers
    with TestClient(create_server_app(engine, ["http://app.local"])) as client:
        response = client.options("/frame", headers=headers)
        assert response.headers["access-control-allow-origin"] == "http://app.local"


def test_stdlib_client_round_trip(monkeypatch):
    # Client chi dung urllib: noi no vao TestClient qua urlopen gia.
    engine = HumanDetector(kiosk_config(), "abc", FakeDetector([STANDING]), None,
                           calibration_frame=(1280, 720))
    jpeg = cv2.imencode(".jpg", FRAME)[1].tobytes()
    with TestClient(create_server_app(engine)) as http:
        class Response:
            def __init__(self, body):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(request, timeout):
            path = request.full_url.removeprefix("http://hd")
            response = http.request(request.get_method(), path, content=request.data)
            response.raise_for_status()
            return Response(response.content)

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        client = HumanDetectionClient("http://hd")
        client.wait_until_ready(timeout=1)
        result = client.send_frame(jpeg, timestamp_ms=1000)
        assert [e["event"] for e in result["events"]] == ["USER_ENGAGED"]
        assert client.status()["activeTrackId"] == result["activeTrackId"]
        assert [e["event"] for e in client.reset()["events"]] == ["USER_LEFT"]


@pytest.mark.skipif(not VIDEO_YAML.is_file(), reason="khong con kiosk.video.yaml")
def test_default_yaml_keeps_video_calibration_and_only_swaps_the_source():
    # Video hieu chuan quay tu chinh camera kiosk: giu nguyen moi thu tru nguon.
    ours, _ = load_config(DEFAULT_CONFIG)
    theirs, _ = load_config(VIDEO_YAML)
    same = {"camera": {"source"}}
    assert ours.model_dump(exclude=same) == theirs.model_dump(exclude=same)
    assert isinstance(ours.camera.source, int)      # camera, khong phai file video


MODELS = PROJECT_ROOT / "models"


@pytest.mark.skipif(not (MODELS / "yolox_nano.onnx").is_file(),
                    reason="chua co model — chay scripts/setup.sh mot lan de tai")
def test_real_models_load_with_capped_threads_and_process_an_empty_frame():
    config, checksum = load_config(DEFAULT_CONFIG)
    engine = HumanDetector.load(config, checksum, calibration_frame=(1920, 1080), onnx_threads=2)
    try:
        options = engine.detector.session.get_session_options()
        assert options.intra_op_num_threads == 2
        result, events = engine.process(FRAME, 0)   # 1280x720: cung ti le, engine tu quy doi
        assert result["tracks"] == [] and events == []
        assert result["calibration"]["aspectMismatch"] is False
        assert all(result["zones"][name] for name in ("detection", "approach", "interaction"))
        assert set(engine.model_checksums) == {"detector"}  # head pose tat trong YAML
    finally:
        engine.close()
