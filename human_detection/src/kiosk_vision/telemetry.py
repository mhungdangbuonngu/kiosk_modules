from __future__ import annotations

import threading
import time
from collections import deque


class RuntimeMetrics:
    def __init__(self, window: int = 300):
        self.started_ms = time.monotonic_ns() // 1_000_000
        self.frames_captured = 0
        self.frames_processed = 0
        self.inference_errors = 0
        self.events_emitted = 0
        self.latencies_ms: deque[float] = deque(maxlen=window)
        self._lock = threading.Lock()

    def record_frame(self, latency_ms: float, events: int) -> None:
        with self._lock:
            self.frames_processed += 1
            self.events_emitted += events
            self.latencies_ms.append(latency_ms)

    def record_event(self) -> None:
        with self._lock:
            self.events_emitted += 1

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            values = sorted(self.latencies_ms)
            percentile = lambda p: values[min(len(values) - 1, int(len(values) * p))] if values else 0.0
            elapsed = max(0.001, (time.monotonic_ns() // 1_000_000 - self.started_ms) / 1000)
            return {
                "uptime_s": round(elapsed, 1), "frames_processed": self.frames_processed,
                "processing_fps": round(self.frames_processed / elapsed, 2),
                "inference_errors": self.inference_errors, "events_emitted": self.events_emitted,
                "latency_median_ms": round(percentile(0.5), 2),
                "latency_p95_ms": round(percentile(0.95), 2), "inference_backlog": 0,
            }
