from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrackState(str, Enum):
    PRESENT = "PRESENT"
    APPROACHING = "APPROACHING"
    CANDIDATE = "CANDIDATE"
    ENGAGED = "ENGAGED"
    ENGAGED_HOLD = "ENGAGED_HOLD"
    DEPARTING = "DEPARTING"


class EventType(str, Enum):
    USER_APPROACHING = "USER_APPROACHING"
    USER_ENGAGED = "USER_ENGAGED"
    USER_LEFT = "USER_LEFT"
    VISION_DEGRADED = "VISION_DEGRADED"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int = 0


@dataclass(frozen=True)
class TrackedDetection:
    track_id: int
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class HeadObservation:
    timestamp_ms: int
    yaw_deg: float
    pitch_deg: float
    confidence: float


@dataclass
class PersonTrack:
    id: int
    bbox: tuple[float, float, float, float]
    confidence: float
    first_seen_ms: int
    last_seen_ms: int
    foot_point: tuple[float, float] | None = None
    world_xy: tuple[float, float] | None = None
    velocity_xy: tuple[float, float] = (0.0, 0.0)
    radial_velocity_mps: float = 0.0
    distance_to_kiosk: float | None = None
    bbox_area_ratio: float = 0.0
    in_detection_zone: bool = False
    in_approach_zone: bool = False
    in_interaction_zone: bool = False
    face_visible: bool = False
    facing_score: float | None = None
    head: HeadObservation | None = None
    state: TrackState = TrackState.PRESENT
    state_since_ms: int = 0
    interaction_since_ms: int | None = None
    history: list[tuple[int, float, float]] = field(default_factory=list)
    emitted_approaching: bool = False
    emitted_engaged: bool = False

    @property
    def age_ms(self) -> int:
        return self.last_seen_ms - self.first_seen_ms


@dataclass(frozen=True)
class KioskVisionEvent:
    timestamp_ms: int
    event: EventType
    track_id: int | None
    distance_m: float | None
    facing_score: float | None
    engagement_confidence: float
    reason: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_ms": self.timestamp_ms,
            "event": self.event.value,
            "track_id": self.track_id,
            "distance_m": self.distance_m,
            "facing_score": self.facing_score,
            "engagement_confidence": self.engagement_confidence,
            "reason": list(self.reason),
        }
