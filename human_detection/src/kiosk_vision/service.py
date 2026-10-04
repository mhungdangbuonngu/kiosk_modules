from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import AppConfig
from .pipeline import VisionPipeline
from .telemetry import RuntimeMetrics


class EventBroker:
    def __init__(self, history_size: int = 100):
        self.history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        self.history.append(event)
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)


def create_app(config: AppConfig, config_checksum: str, pipeline: VisionPipeline | None = None,
               run_vision: bool = False, development_tracker: bool = False,
               preview: bool = False, record_preview: str | None = None) -> FastAPI:
    runtime = pipeline or VisionPipeline(config)
    metrics = RuntimeMetrics()
    broker = EventBroker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        controller = None
        if run_vision:
            from .runtime import VisionRuntime
            controller = VisionRuntime(config, runtime, metrics, broker, development_tracker,
                                       preview, record_preview)
            controller.start()
            app.state.controller = controller
        app.state.ready = True
        yield
        app.state.ready = False
        if controller:
            await controller.stop()

    app = FastAPI(title="Kiosk Vision", version="0.1.0", lifespan=lifespan)
    app.state.ready = False
    app.state.pipeline = runtime
    app.state.metrics = metrics
    app.state.broker = broker

    @app.get("/health")
    async def health() -> dict[str, Any]:
        controller = getattr(app.state, "controller", None)
        camera = ({"online": controller.capture.online,
                   "last_error": controller.capture.last_error,
                   "resolution": controller.capture.frame_size} if controller else None)
        models = controller.model_checksums if controller else {}
        healthy = app.state.ready and (controller is None or controller.capture.online)
        return {"status": "ok" if healthy else ("degraded" if app.state.ready else "starting"),
                "ready": app.state.ready,
                "config_checksum": config_checksum, "active_track_id": runtime.engine.active_track_id,
                "camera": camera, "model_checksums": models, "metrics": metrics.snapshot()}

    @app.get("/tracks")
    async def tracks() -> list[dict[str, object]]:
        return runtime.snapshot()

    @app.get("/events")
    async def events() -> list[dict[str, Any]]:
        return list(broker.history)

    @app.websocket("/events/ws")
    async def event_stream(socket: WebSocket) -> None:
        await socket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        broker.subscribers.add(queue)
        try:
            while True:
                await socket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            broker.subscribers.discard(queue)

    return app
