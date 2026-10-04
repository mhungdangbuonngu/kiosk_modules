"""
Client HTTP cho server human_detection — CHI dung thu vien chuan Python (3.8+).

Chep nguyen file nay vao app cua ban la dung duoc, khong can cai numpy/OpenCV/
MediaPipe: app chay Python nao cung duoc, server chay moi truong rieng.

    from client import HumanDetectionClient
    hd = HumanDetectionClient("http://127.0.0.1:8765")
    result = hd.send_frame(jpeg_bytes)        # bytes JPEG cua mot frame camera
    if result["activeTrackId"] is not None:
        ...                                   # co nguoi dang dung dung truoc kiosk
    for event in result["events"]:            # USER_ENGAGED / USER_LEFT moi phat sinh
        print(event["event"], event["track_id"])

Gui frame THEO DUNG thu tu thoi gian va tu MOT camera. Nen gui ~5-10 frame/giay.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class HumanDetectionError(RuntimeError):
    """Server tra loi loi (status != 2xx) hoac khong ket noi duoc."""


class HumanDetectionClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._clock_origin = time.monotonic()

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str | None = None) -> Any:
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise HumanDetectionError(f"{method} {path} -> {error.code}: {detail}") from error
        except (urllib.error.URLError, OSError) as error:
            raise HumanDetectionError(f"Khong ket noi duoc {self.base_url}: {error}") from error

    def send_frame(self, jpeg: bytes, timestamp_ms: float | None = None) -> dict[str, Any]:
        """Gui mot frame (JPEG/PNG). `timestamp_ms` = dong ho don dieu luc CHUP frame;
        bo trong thi client tu lay dong ho don dieu cua chinh no."""
        if timestamp_ms is None:
            timestamp_ms = (time.monotonic() - self._clock_origin) * 1000
        return self._request("POST", f"/frame?timestampMs={timestamp_ms:.0f}", jpeg, "image/jpeg")

    def reset(self) -> dict[str, Any]:
        """Bo het track, bat dau phien moi (vd. khi app chuyen man hinh)."""
        return self._request("POST", "/reset")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def events(self) -> list[dict[str, Any]]:
        """~100 su kien gan nhat (USER_ENGAGED / USER_LEFT)."""
        return self._request("GET", "/events")

    def wait_until_ready(self, timeout: float = 60.0) -> None:
        """Doi server nap xong model (lan dau co the mat vai giay)."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                if self.health().get("ready"):
                    return
            except HumanDetectionError:
                pass
            if time.monotonic() > deadline:
                raise HumanDetectionError(f"Server {self.base_url} chua san sang sau {timeout}s")
            time.sleep(0.5)
