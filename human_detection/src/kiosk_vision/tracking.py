from __future__ import annotations

from collections.abc import Sequence

from .models import Detection, TrackedDetection


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(1e-9, area_a + area_b - intersection)


class IoUTracker:
    """Dependency-free fallback tracker. Use ByteTrackAdapter in production."""

    def __init__(self, match_iou: float = 0.3, max_missing: int = 15):
        self.match_iou = match_iou
        self.max_missing = max_missing
        self._next_id = 1
        self._tracks: dict[int, tuple[tuple[float, float, float, float], int]] = {}

    def update(self, detections: Sequence[Detection]) -> list[TrackedDetection]:
        unmatched = set(self._tracks)
        result: list[TrackedDetection] = []
        for det in sorted(detections, key=lambda d: d.confidence, reverse=True):
            choices = [(self._tracks[tid][0], tid) for tid in unmatched]
            score, track_id = max(((_iou(det.bbox, box), tid) for box, tid in choices),
                                  default=(0.0, -1))
            if score < self.match_iou:
                track_id, self._next_id = self._next_id, self._next_id + 1
            else:
                unmatched.remove(track_id)
            self._tracks[track_id] = (det.bbox, 0)
            result.append(TrackedDetection(track_id, det.bbox, det.confidence))
        for track_id in list(unmatched):
            bbox, missing = self._tracks[track_id]
            if missing + 1 > self.max_missing:
                del self._tracks[track_id]
            else:
                self._tracks[track_id] = (bbox, missing + 1)
        return result


class ByteTrackAdapter:
    """Adapter for the detector-agnostic ByteTrack implementation in Supervision."""

    def __init__(self, track_thresh: float, match_thresh: float, track_buffer: int, fps: int):
        try:
            import supervision as sv
        except ImportError as exc:
            raise RuntimeError("Install the 'supervision' package to enable ByteTrack") from exc
        self._tracker = sv.ByteTrack(
            track_activation_threshold=track_thresh,
            lost_track_buffer=track_buffer,
            minimum_matching_threshold=match_thresh,
            frame_rate=fps,
        )

    def update(self, detections: Sequence[Detection], frame_size: tuple[int, int]) -> list[TrackedDetection]:
        import numpy as np
        import supervision as sv

        del frame_size
        boxes = np.asarray([d.bbox for d in detections], dtype=np.float32).reshape(-1, 4)
        scores = np.asarray([d.confidence for d in detections], dtype=np.float32)
        classes = np.zeros(len(detections), dtype=int)
        online = self._tracker.update_with_detections(sv.Detections(
            xyxy=boxes, confidence=scores, class_id=classes))
        if online.tracker_id is None:
            return []
        return [TrackedDetection(int(track_id), tuple(map(float, bbox)), float(score))
                for bbox, score, track_id in zip(
                    online.xyxy, online.confidence, online.tracker_id, strict=True)
                if int(track_id) >= 0]
