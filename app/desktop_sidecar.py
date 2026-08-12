"""Packaged localhost backend launched only by the Tauri desktop shell."""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
from pathlib import Path

import uvicorn


def _frozen_support() -> None:
    """Allow multiprocessing libraries used by local voice/vision to run in a frozen sidecar."""
    import multiprocessing

    multiprocessing.freeze_support()


def _exit_when_parent_exits(parent_pid: int) -> None:
    """Prevent a frozen worker from surviving if the desktop shell disappears."""
    if os.name != "nt" or parent_pid <= 0:
        return
    import ctypes

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        os._exit(0)

    def watch() -> None:
        try:
            ctypes.windll.kernel32.WaitForSingleObject(handle, infinite)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        os._exit(0)

    threading.Thread(target=watch, name="desktop-parent-watch", daemon=True).start()


def main() -> None:
    _frozen_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session-token", default=os.environ.get("AI_TEAM_OS_DESKTOP_SESSION_TOKEN"))
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    if not args.session_token:
        parser.error("desktop session token is required")
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    ready_file = Path(args.ready_file).resolve()
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    os.environ["AI_TEAM_OS_DATA_DIR"] = str(data_dir)
    os.environ["AI_TEAM_OS_DESKTOP_SESSION_TOKEN"] = args.session_token
    _exit_when_parent_exits(args.parent_pid)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(2048)
    port = int(sock.getsockname()[1])
    temp = ready_file.with_suffix(".tmp")
    temp.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    temp.replace(ready_file)
    config = uvicorn.Config(
        "app.api.server:app", host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
