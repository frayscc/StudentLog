"""Local production launcher. This file becomes StudentLog.exe in Phase 4."""
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import uvicorn

from backend.app.config import settings


def wait_and_open(port: int) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                webbrowser.open(f"http://127.0.0.1:{port}")
                return
        except OSError:
            time.sleep(0.2)


def main() -> None:
    if not settings.frontend_dist.exists():
        raise SystemExit("未找到前端正式版文件，请先在 frontend 目录执行 npm run build。")
    threading.Thread(target=wait_and_open, args=(settings.studentlog_port,), daemon=True).start()
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=settings.studentlog_port, log_level="warning")


if __name__ == "__main__":
    main()
