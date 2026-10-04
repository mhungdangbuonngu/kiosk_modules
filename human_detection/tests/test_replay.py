import json

from test_engagement import config

from kiosk_vision.replay import replay_jsonl


def test_anonymous_observation_replay(tmp_path):
    scenario = tmp_path / "scenario.jsonl"
    rows = [
        {"timestamp_ms": 0, "tracks": [{"track_id": 3, "bbox": [0, 0, 100, 1080]}]},
        {"timestamp_ms": 600, "tracks": [{"track_id": 3, "bbox": [0, 0, 400, 1080]}]},
        {"timestamp_ms": 1200, "tracks": [{"track_id": 3, "bbox": [0, 0, 400, 1080]}]},
    ]
    scenario.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    events = replay_jsonl(config(), scenario)
    assert events[-1]["event"] == "USER_ENGAGED"
    assert events[-1]["track_id"] == 3
