from kiosk_vision.models import Detection
from kiosk_vision.tracking import ByteTrackAdapter, IoUTracker


def test_iou_tracker_keeps_identity_and_expires():
    tracker = IoUTracker(match_iou=0.2, max_missing=1)
    first = tracker.update([Detection((0, 0, 10, 10), 0.9)])[0]
    second = tracker.update([Detection((1, 0, 11, 10), 0.8)])[0]
    assert first.track_id == second.track_id
    tracker.update([])
    tracker.update([])
    new = tracker.update([Detection((1, 0, 11, 10), 0.8)])[0]
    assert new.track_id != first.track_id


def test_bytetrack_adapter_keeps_identity():
    tracker = ByteTrackAdapter(track_thresh=0.4, match_thresh=0.8, track_buffer=30, fps=15)
    detections = [Detection((10, 10, 100, 200), 0.9)]
    first = tracker.update(detections, (480, 640))
    second = tracker.update(detections, (480, 640))
    assert len(first) == len(second) == 1
    assert first[0].track_id == second[0].track_id
