from __future__ import annotations

from .config import EngagementConfig, HeadPoseConfig
from .models import EventType, KioskVisionEvent, PersonTrack, TrackState


class EngagementEngine:
    """Direct bounding-box occupancy decision with hysteresis."""

    def __init__(self, config: EngagementConfig, head_config: HeadPoseConfig):
        self.config = config
        self.head_config = head_config
        self.active_track_id: int | None = None

    def facing_score(self, track: PersonTrack, now_ms: int) -> float | None:
        head = track.head
        if head is None or now_ms - head.timestamp_ms > self.head_config.observation_ttl_ms:
            return None
        yaw = max(0.0, 1.0 - abs(head.yaw_deg) / self.head_config.max_yaw_deg)
        pitch = max(0.0, 1.0 - abs(head.pitch_deg) / self.head_config.max_pitch_deg)
        return min(yaw, pitch) * head.confidence

    def update(self, tracks: dict[int, PersonTrack], now_ms: int) -> list[KioskVisionEvent]:
        events: list[KioskVisionEvent] = []
        for track in tracks.values():
            track.facing_score = (self.facing_score(track, now_ms)
                                  if self.head_config.enabled else None)

        current = tracks.get(self.active_track_id) if self.active_track_id is not None else None
        if current and current.emitted_engaged and (
                current.bbox_area_ratio < self.config.bbox_exit_ratio):
            self._transition(current, TrackState.PRESENT, now_ms)
            events.append(self._event(
                current, now_ms, EventType.USER_LEFT, 1.0,
                ("bbox_area_ratio_below_exit_threshold",)))
            current.emitted_engaged = False
            self.active_track_id = None

        if self.active_track_id is None:
            candidates = [
                track for track in tracks.values()
                if track.bbox_area_ratio >= self.config.bbox_enter_ratio
            ]
            if candidates:
                self.active_track_id = max(candidates, key=lambda track: track.bbox_area_ratio).id

        active = tracks.get(self.active_track_id) if self.active_track_id is not None else None
        if active is not None and not active.emitted_engaged:
            self._transition(active, TrackState.ENGAGED, now_ms)
            events.append(self._event(
                active, now_ms, EventType.USER_ENGAGED,
                self._confidence(active),
                ("bbox_area_ratio_above_enter_threshold",)))
            active.emitted_engaged = True

        for track in tracks.values():
            if track.id != self.active_track_id:
                self._transition(track, TrackState.PRESENT, now_ms)
        return events

    def track_lost(self, track: PersonTrack, now_ms: int) -> KioskVisionEvent | None:
        if track.id == self.active_track_id:
            self.active_track_id = None
        if track.emitted_engaged:
            return self._event(track, now_ms, EventType.USER_LEFT, 0.8, ("track_lost",))
        return None

    @staticmethod
    def _transition(track: PersonTrack, state: TrackState, now_ms: int) -> None:
        if track.state != state:
            track.state = state
            track.state_since_ms = now_ms

    def _confidence(self, track: PersonTrack) -> float:
        threshold = self.config.bbox_enter_ratio
        return round(min(1.0, track.bbox_area_ratio / max(threshold, 1e-9)), 3)

    @staticmethod
    def _event(track: PersonTrack, now_ms: int, kind: EventType, confidence: float,
               reasons: tuple[str, ...]) -> KioskVisionEvent:
        return KioskVisionEvent(now_ms, kind, track.id, track.distance_to_kiosk,
                                track.facing_score, confidence, reasons)
