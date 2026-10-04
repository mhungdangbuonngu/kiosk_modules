from kiosk_vision.config import AppConfig
from kiosk_vision.models import EventType, TrackedDetection, TrackState
from kiosk_vision.pipeline import VisionPipeline


def config() -> AppConfig:
    return AppConfig.model_validate({
        "calibration": {
            "homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "kiosk_xy_m": [0, 0],
            "detection_polygon_m": [[-3, 0], [3, 0], [3, 4], [-3, 4]],
            "approach_polygon_m": [[-2, 0], [2, 0], [2, 3], [-2, 3]],
            "interaction_polygon_m": [[-1, 0], [1, 0], [1, 1.2], [-1, 1.2]],
        },
        "engagement": {
            "bbox_enter_ratio": 0.18,
            "bbox_exit_ratio": 0.12,
            "lost_track_ms": 500,
        },
    })


def person(track_id: int, area_ratio: float) -> TrackedDetection:
    # Tests use a 100 x 100 frame and a full-height box, so width percent equals area percent.
    return TrackedDetection(track_id, (0, 0, area_ratio * 100, 100), 0.9)


def test_bbox_threshold_engages_holds_and_leaves():
    pipeline = VisionPipeline(config())
    assert pipeline.update([person(7, 0.17)], 0, frame_size=(100, 100)) == []

    engaged = pipeline.update([person(7, 0.20)], 100, frame_size=(100, 100))
    assert [event.event for event in engaged] == [EventType.USER_ENGAGED]
    assert pipeline.tracks[7].state == TrackState.ENGAGED

    # Hysteresis keeps the session active between the enter and exit thresholds.
    assert pipeline.update([person(7, 0.15)], 200, frame_size=(100, 100)) == []
    assert pipeline.tracks[7].state == TrackState.ENGAGED

    left = pipeline.update([person(7, 0.11)], 300, frame_size=(100, 100))
    assert [event.event for event in left] == [EventType.USER_LEFT]
    assert pipeline.tracks[7].state == TrackState.PRESENT


def test_largest_box_becomes_active_and_is_sticky():
    pipeline = VisionPipeline(config())
    pipeline.update([person(1, 0.20), person(2, 0.25)], 0, frame_size=(100, 100))
    assert pipeline.engine.active_track_id == 2

    pipeline.update([person(1, 0.30), person(2, 0.15)], 100, frame_size=(100, 100))
    assert pipeline.engine.active_track_id == 2


def test_track_loss_emits_left_only_after_grace_period():
    pipeline = VisionPipeline(config())
    pipeline.update([person(1, 0.20)], 0, frame_size=(100, 100))
    assert pipeline.update([], 300, frame_size=(100, 100)) == []
    lost = pipeline.update([], 501, frame_size=(100, 100))
    assert [event.event for event in lost] == [EventType.USER_LEFT]


def test_bbox_area_is_clipped_to_frame():
    pipeline = VisionPipeline(config())
    detection = TrackedDetection(1, (-20, -10, 50, 110), 0.9)
    pipeline.update([detection], 0, frame_size=(100, 100))
    assert pipeline.tracks[1].bbox_area_ratio == 0.5


def test_disabled_head_pose_skips_score_computation(monkeypatch):
    pipeline = VisionPipeline(config())

    def unexpected(*args):
        raise AssertionError("Disabled head pose must not calculate facing scores")

    monkeypatch.setattr(pipeline.engine, "facing_score", unexpected)
    pipeline.update([person(1, 0.20)], 0, frame_size=(100, 100))
    assert pipeline.tracks[1].facing_score is None


def test_current_video_thresholds_enter_at_30_hold_at_25_exit_below_25():
    from kiosk_vision.config import load_config

    current, _ = load_config("config/kiosk.video.yaml")
    pipeline = VisionPipeline(current)
    assert pipeline.update([person(1, .299)], 0, frame_size=(100, 100)) == []
    assert [event.event for event in pipeline.update(
        [person(1, .30)], 100, frame_size=(100, 100))] == [EventType.USER_ENGAGED]
    assert pipeline.update([person(1, .25)], 200, frame_size=(100, 100)) == []
    assert [event.event for event in pipeline.update(
        [person(1, .249)], 300, frame_size=(100, 100))] == [EventType.USER_LEFT]
