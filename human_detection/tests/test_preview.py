import numpy as np

from kiosk_vision.models import PersonTrack, TrackState
from kiosk_vision.preview import render_preview


def test_render_preview_draws_detection_status_without_mutating_frame():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    track = PersonTrack(
        id=7,
        bbox=(100, 80, 260, 320),
        confidence=0.9,
        first_seen_ms=0,
        last_seen_ms=1000,
        foot_point=(180, 320),
        world_xy=(0.5, 1.2),
        distance_to_kiosk=1.3,
        state=TrackState.ENGAGED,
    )

    rendered = render_preview(frame, [track], 7, {"processing_fps": 15.0})

    assert np.count_nonzero(rendered) > 0
    assert np.count_nonzero(frame) == 0
    assert tuple(rendered[80, 100]) != (0, 0, 0)
