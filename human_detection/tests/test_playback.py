import cv2
import numpy as np

from kiosk_vision.playback import PlaybackBar


def test_timeline_drag_clamps_and_releases_outside_bar():
    bar = PlaybackBar(101, 25)
    assert bar.mouse_action(cv2.EVENT_LBUTTONDOWN, 524, 1164, 1048, 1080) == 50
    assert bar.mouse_action(cv2.EVENT_MOUSEMOVE, -100, 900, 1048, 1080) == 0
    assert bar.mouse_action(cv2.EVENT_MOUSEMOVE, 2000, 900, 1048, 1080) == 100
    assert bar.mouse_action(cv2.EVENT_LBUTTONUP, 274, 900, 1048, 1080) == 25
    assert not bar.dragging
    assert bar.mouse_action(cv2.EVENT_MOUSEMOVE, 500, 1164, 1048, 1080) is None


def test_buttons_are_outside_image_and_timeline_does_not_change_pixels():
    bar = PlaybackBar(101, 25)
    assert bar.mouse_action(cv2.EVENT_LBUTTONDOWN, 60, 100, 1920, 1080) is None
    assert bar.mouse_action(cv2.EVENT_LBUTTONDOWN, 60, 1110, 1920, 1080) == "play"
    assert bar.mouse_action(cv2.EVENT_LBUTTONDOWN, 180, 1110, 1920, 1080) == "previous"
    assert bar.mouse_action(cv2.EVENT_LBUTTONDOWN, 300, 1110, 1920, 1080) == "next"
    frame = np.full((1080, 1920, 3), 123, dtype=np.uint8)
    display = bar.render(frame, 50, paused=True, editing=False)
    assert display.shape == (1192, 1920, 3)
    np.testing.assert_array_equal(display[:1080], frame)
    assert bar.format_time(62.5) == "01:02.50"
