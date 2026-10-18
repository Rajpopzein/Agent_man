"""Standalone browser-hosted distribution of Agent Man."""
import argparse
import multiprocessing
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

import uvicorn
from fastapi.staticfiles import StaticFiles


def main():
    parser = argparse.ArgumentParser(description="Agent Man desktop launcher")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    # Reserve the socket before starting the runtime; a running dev server is safe.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", args.port))
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    from app.main import app

    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    web_dir = bundle / "web" if getattr(sys, "frozen", False) else bundle / "apps/web/dist"
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, loop="asyncio"))

    def open_when_ready():
        while not server.started and not server.should_exit:
            time.sleep(0.1)
        if server.started:
            webbrowser.open(url)

    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"Agent Man: {url}\nKeep this window open. Press Ctrl+C to stop Agent Man.", flush=True)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
