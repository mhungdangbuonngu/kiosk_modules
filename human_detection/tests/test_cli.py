from kiosk_vision.cli import parser
from kiosk_vision.config import load_config


def test_camera_commands_default_to_installed_camera_recording():
    for command in ("serve", "doctor", "validate-config", "calibrate-visual"):
        args = parser().parse_args([command])
        assert args.config == "config/kiosk.video.yaml"
    config, _ = load_config("config/kiosk.video.yaml")
    assert config.camera.source == "example/WIN_20260930_16_18_37_Pro.mp4"
    assert config.camera.resolution_mode == "native"


def test_explicit_camera_config_overrides_recording_default():
    args = parser().parse_args(["serve", "config/kiosk.production.yaml", "--preview"])
    assert args.config == "config/kiosk.production.yaml"
    assert args.preview


def test_preview_recording_can_run_with_or_without_a_window():
    args = parser().parse_args(["serve", "--record-preview", "diagnostics/output.mp4"])
    assert args.record_preview == "diagnostics/output.mp4"
    assert not args.preview
    args = parser().parse_args(["serve", "--preview", "--record-preview", "output.mp4"])
    assert args.preview
