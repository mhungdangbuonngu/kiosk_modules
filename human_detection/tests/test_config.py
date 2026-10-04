from pathlib import Path

import pytest
from pydantic import ValidationError

from kiosk_vision.config import AppConfig, load_config


def test_example_config_is_valid():
    config, checksum = load_config(Path("config/kiosk.example.yaml"))
    assert config.version == 1
    assert len(checksum) == 64
    assert config.service.diagnostic_media is False


def test_singular_homography_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({
            "calibration": {
                "homography": [[1, 0, 0], [1, 0, 0], [0, 0, 1]],
                "detection_polygon_m": [[0, 0], [1, 0], [0, 1]],
                "approach_polygon_m": [[0, 0], [1, 0], [0, 1]],
                "interaction_polygon_m": [[0, 0], [1, 0], [0, 1]],
            }
        })

