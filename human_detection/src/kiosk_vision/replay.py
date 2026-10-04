from __future__ import annotations

import json
from pathlib import Path

from .config import AppConfig
from .models import HeadObservation, TrackedDetection
from .pipeline import VisionPipeline


def replay_jsonl(config: AppConfig, path: str | Path) -> list[dict[str, object]]:
    """Replay labeled/precomputed observations without storing or loading customer video."""
    pipeline = VisionPipeline(config)
    events: list[dict[str, object]] = []
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            timestamp = int(row["timestamp_ms"])
            tracked = [TrackedDetection(int(item["track_id"]), tuple(item["bbox"]),
                                        float(item.get("confidence", 1.0)))
                       for item in row.get("tracks", [])]
            heads = {int(item["track_id"]): HeadObservation(
                        timestamp, float(item["yaw_deg"]), float(item["pitch_deg"]),
                        float(item.get("confidence", 1.0)))
                     for item in row.get("heads", [])}
            events.extend(event.as_dict() for event in pipeline.update(tracked, timestamp, heads))
    return events

