import pytest

from kiosk_vision.config import CalibrationConfig
from kiosk_vision.geometry import SpatialMapper


def test_homography_and_zones():
    mapper = SpatialMapper(CalibrationConfig(
        homography=[[0.01, 0, 0], [0, 0.01, 0], [0, 0, 1]],
        kiosk_xy_m=(0, 0),
        detection_polygon_m=[(-3, 0), (3, 0), (3, 4), (-3, 4)],
        approach_polygon_m=[(-2, 1), (2, 1), (2, 3), (-2, 3)],
        interaction_polygon_m=[(-1, 0), (1, 0), (1, 1), (-1, 1)],
    ))
    assert mapper.image_to_floor((50, 200)) == pytest.approx((0.5, 2.0))
    assert mapper.zones((0.5, 2.0)) == (True, True, False)

