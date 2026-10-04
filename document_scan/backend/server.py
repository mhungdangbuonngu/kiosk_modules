"""Server mẫu chạy độc lập: API document scan + phục vụ luôn thư mục frontend/ để thử.

    cd document_scan/backend
    pip install -r requirements.txt
    python server.py                       # http://localhost:8000/  (trang demo)
    python server.py --host 0.0.0.0 --port 9000

App của bạn đã có FastAPI thì không cần file này — chỉ cần:

    from document_scan.api import create_router
    app.include_router(create_router())
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # import được package document_scan dù chạy từ thư mục nào

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from document_scan.api import create_router  # noqa: E402

FRONTEND_DIR = os.path.join(os.path.dirname(HERE), "frontend")


def create_app() -> FastAPI:
    app = FastAPI(title="Document Scan")
    # Cho phép frontend ở origin khác gọi thẳng (khi không đi qua reverse proxy).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-DocScan-Result"])
    app.include_router(create_router())
    if os.path.isdir(FRONTEND_DIR):
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
