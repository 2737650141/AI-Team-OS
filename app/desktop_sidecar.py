"""Packaged localhost backend launched only by the Tauri desktop shell."""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path

import uvicorn


def _frozen_support() -> None:
    """Allow multiprocessing libraries used by local voice/vision to run in a frozen sidecar."""
    import multiprocessing

    multiprocessing.freeze_support()


def main() -> None:
    _frozen_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session-token", default=os.environ.get("AI_TEAM_OS_DESKTOP_SESSION_TOKEN"))
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args()
    if not args.session_token:
        parser.error("desktop session token is required")
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    ready_file = Path(args.ready_file).resolve()
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    os.environ["AI_TEAM_OS_DATA_DIR"] = str(data_dir)
    os.environ["AI_TEAM_OS_DESKTOP_SESSION_TOKEN"] = args.session_token

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
