"""Small JSONL RPC client and accidental-I/O guard for engine workers."""
from __future__ import annotations

import json
import socket
import sqlite3
import sys
import os
import tempfile
from pathlib import Path
from typing import Any

from ..research_engine_protocol import PROTOCOL, decode_message, encode_message


def install_io_guard() -> None:
    """Block network and direct SQLite access in the child process.

    This is an application guard against accidental I/O, not an OS sandbox.
    """
    def deny_network(*_args, **_kwargs):
        raise PermissionError("network access is available only through core RPC")

    socket.create_connection = deny_network  # type: ignore[assignment]
    socket.getaddrinfo = deny_network  # type: ignore[assignment]
    socket.socket.connect = deny_network  # type: ignore[assignment]
    raw_sqlite_connect = sqlite3.connect

    def guarded_sqlite_connect(database, *args, **kwargs):
        if database == ":memory:":
            return raw_sqlite_connect(database, *args, **kwargs)
        cache_root = os.environ.get("RH_WORKER_CACHE_ROOT")
        if isinstance(cache_root, str) and cache_root:
            try:
                root = Path(cache_root).resolve()
                candidate = Path(os.fsdecode(database)).resolve()
                if root.name.startswith("rh-storm-home-") and (candidate == root or candidate.is_relative_to(root)):
                    return raw_sqlite_connect(database, *args, **kwargs)
            except (OSError, TypeError, ValueError):
                pass
        raise PermissionError("direct SQLite access is available only for the ephemeral STORM cache")

    sqlite3.connect = guarded_sqlite_connect  # type: ignore[assignment]
    allowed_roots = [Path(sys.prefix), Path(sys.base_prefix), Path(__file__).resolve().parents[1], Path(tempfile.gettempdir())]
    normalized = [os.path.normcase(str(path.resolve())) for path in allowed_roots]
    null_device = os.path.normcase(os.devnull)

    def audit(event, args):
        if event != "open" or not args:
            return
        path = args[0]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        if os.path.normcase(os.fsdecode(path)) == null_device:
            return
        try:
            candidate = os.path.normcase(str(Path(path).resolve()))
        except (OSError, TypeError, ValueError):
            raise PermissionError(f"worker file access is outside approved roots: {candidate}")
        if not any(candidate == root or candidate.startswith(root + os.sep) for root in normalized):
            raise PermissionError(f"worker file access is outside approved roots: {candidate}")

    sys.addaudithook(audit)


def read_message(stream) -> dict[str, Any]:
    line = stream.readline(1024 * 1024 + 1)
    if not line or len(line) > 1024 * 1024 or not line.endswith(b"\n"):
        raise ValueError("missing or oversized protocol line")
    message = decode_message(line[:-1])
    if message.get("protocol") != PROTOCOL:
        raise ValueError("protocol version mismatch")
    return message


class RpcClient:
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self.identity: dict[str, Any] | None = None
        self._pending: dict[str, dict[str, Any]] = {}

    def call(self, op: str, request_id: str, purpose: str, request: dict[str, Any]) -> dict[str, Any]:
        if op not in {"model_call", "embedding", "retrieve_frozen"} or not request_id or request_id in self._pending:
            raise ValueError("invalid or repeated RPC request")
        if self.identity is None:
            raise ValueError("RPC identity has not been set")
        self.stdout.write(encode_message({"protocol": PROTOCOL, "op": "rpc", "identity": self.identity,
            "rpc_op": op, "request_id": request_id, "purpose": purpose, "request": request}))
        self.stdout.flush()
        reply = read_message(self.stdin)
        if reply.get("op") != "rpc_result" or reply.get("identity") != self.identity or reply.get("request_id") != request_id:
            raise ValueError("RPC response identity mismatch")
        return reply
