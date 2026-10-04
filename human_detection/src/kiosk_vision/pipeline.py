from __future__ import annotations

import math
from collections.abc import Sequence

from .config import AppConfig
from .engagement import EngagementEngine
from .geometry import SpatialMapper
from .models import HeadObservation, KioskVisionEvent, PersonTrack, TrackedDetection


class VisionPipeline:
    """Joins anonymous tracker output, calibrated geometry, and engagement behavior."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.mapper = SpatialMapper(config.calibration)
        self.engine = EngagementEngine(config.engagement, config.head_pose)
        self.tracks: dict[int, PersonTrack] = {}

    def update(self, detections: Sequence[TrackedDetection], timestamp_ms: int,
               heads: dict[int, HeadObservation] | None = None,
               frame_size: tuple[int, int] | None = None) -> list[KioskVisionEvent]:
        seen: set[int] = set()
        heads = heads or {}
        frame_height, frame_width = frame_size or (
            self.config.camera.height, self.config.camera.width)
        frame_area = max(1, frame_height * frame_width)
        for item in detections:
            seen.add(item.track_id)
            foot = ((item.bbox[0] + item.bbox[2]) / 2.0, item.bbox[3])
            world = self.mapper.image_to_floor(foot)
            track = self.tracks.get(item.track_id)
            if track is None:
                track = PersonTrack(item.track_id, item.bbox, item.confidence,
                                    timestamp_ms, timestamp_ms, state_since_ms=timestamp_ms)
                self.tracks[item.track_id] = track
            previous_seen_ms = track.last_seen_ms
            elapsed_s = max(0.001, (timestamp_ms - previous_seen_ms) / 1000)
            old_distance = track.distance_to_kiosk
            if track.world_xy and timestamp_ms > track.last_seen_ms:
                instant = ((world[0] - track.world_xy[0]) / elapsed_s,
                           (world[1] - track.world_xy[1]) / elapsed_s)
                alpha = 0.35
                track.velocity_xy = tuple(alpha * instant[i] + (1 - alpha) * track.velocity_xy[i]
                                          for i in range(2))
            track.bbox, track.confidence = item.bbox, item.confidence
            x1 = min(max(item.bbox[0], 0.0), float(frame_width))
            y1 = min(max(item.bbox[1], 0.0), float(frame_height))
            x2 = min(max(item.bbox[2], 0.0), float(frame_width))
            y2 = min(max(item.bbox[3], 0.0), float(frame_height))
            track.bbox_area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / frame_area
            track.foot_point, track.world_xy, track.last_seen_ms = foot, world, timestamp_ms
            track.distance_to_kiosk = self.mapper.distance_to_kiosk(world)
            if old_distance is not None and timestamp_ms > previous_seen_ms:
                track.radial_velocity_mps = (track.distance_to_kiosk - old_distance) / elapsed_s
            track.in_detection_zone, track.in_approach_zone, track.in_interaction_zone = \
                self.mapper.zones(world)
            track.history.append((timestamp_ms, *world))
            del track.history[:-self.config.tracker.max_history]
            if item.track_id in heads:
                track.head = heads[item.track_id]
                track.face_visible = True
            else:
                track.face_visible = False

        events: list[KioskVisionEvent] = []
        for track_id, track in list(self.tracks.items()):
            if track_id in seen:
                continue
            if timestamp_ms - track.last_seen_ms > self.config.engagement.lost_track_ms:
                event = self.engine.track_lost(track, timestamp_ms)
                if event:
                    events.append(event)
                del self.tracks[track_id]
        events.extend(self.engine.update(self.tracks, timestamp_ms))
        return events

    def snapshot(self) -> list[dict[str, object]]:
        return [{
            "id": t.id, "state": t.state.value, "bbox": t.bbox, "world_xy": t.world_xy,
            "distance_m": t.distance_to_kiosk, "velocity_mps": t.velocity_xy,
            "bbox_area_ratio": t.bbox_area_ratio,
            "facing_score": t.facing_score, "face_visible": t.face_visible,
            "active": t.id == self.engine.active_track_id,
        } for t in self.tracks.values() if math.isfinite(t.distance_to_kiosk or 0.0)]
