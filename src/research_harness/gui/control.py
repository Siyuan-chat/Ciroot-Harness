"""Managed control client for a running local GUI service.

This module deliberately contains no harness or SQLite access.  It is a small
HTTP client used by both the JSON CLI and the managed MCP bridge.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any


def _loopback_url(value: str) -> str:
    """Accept only a plain HTTP loopback origin with an explicit TCP port."""
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is None or not 1 <= parsed.port <= 65535):
        raise ValueError("invalid loopback URL")
    return f"http://{parsed.hostname}:{parsed.port}"


def write_descriptor(root: str | Path, base_url: str, token: str) -> Path:
    """Write a per-instance descriptor and a separate private token reference."""
    root = Path(root).resolve()
    base_url = _loopback_url(base_url)
    control_dir = root / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    token_path = control_dir / "session.token"
    descriptor = control_dir / "instance.json"
    token_path.write_text(token, encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:  # Windows ACLs are inherited from the user data directory.
        pass
    descriptor.write_text(json.dumps({"schema_version": "1", "base_url": base_url.rstrip("/"),
                                      "token_reference": token_path.name}, separators=(",", ":")), encoding="utf-8")
    return descriptor


def remove_descriptor(root: str | Path) -> None:
    """Revoke a managed connection when its owning service exits."""
    control_dir = Path(root).resolve() / "control"
    for name in ("instance.json", "session.token"):
        try: (control_dir / name).unlink()
        except FileNotFoundError: pass


class ControlClient:
    def __init__(self, descriptor: str | Path) -> None:
        path = Path(descriptor).resolve()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            token_name = value["token_reference"]
            if not isinstance(value["base_url"], str) or Path(token_name).name != token_name:
                raise ValueError("invalid descriptor")
            self.base_url = _loopback_url(value["base_url"])
            self.token = (path.parent / token_name).read_text(encoding="utf-8").strip()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("RH_GUI_CONTROL_DESCRIPTOR: managed GUI descriptor is unavailable") from exc
        if not self.token:
            raise ValueError("RH_GUI_CONTROL_DESCRIPTOR: managed GUI token is unavailable")

    def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(action, str) or not isinstance(payload, dict):
            return {"schema_version": "1", "code": "RH_GUI_CONTROL_INPUT", "message": "action and payload are required", "retryable": False}
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        headers = {"Content-Type": "application/json", "x-session-token": self.token}
        for field, header in (("workspace_id", "x-workspace-id"), ("library_id", "x-library-id"), ("collection_id", "x-collection-id")):
            if isinstance(scope.get(field), str): headers[header] = scope[field]
        data = json.dumps({"action": action, **payload}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + "/api/v1/control", data=data, headers=headers, method="POST")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try: return json.loads(exc.read().decode("utf-8"))
            except Exception: return {"schema_version":"1", "code":"RH_GUI_CONTROL_HTTP", "message":"managed GUI request failed", "retryable":False}
        except (urllib.error.URLError, OSError):
            return {"schema_version":"1", "code":"RH_GUI_CONTROL_UNAVAILABLE", "message":"managed GUI service is unavailable", "retryable":True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control a running Research Harness GUI instance")
    parser.add_argument("action")
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--input", default="-", help="JSON request file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = json.loads(raw)
        result = ControlClient(args.descriptor).call(args.action, payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"schema_version":"1", "code":"RH_GUI_CONTROL_INPUT", "message":"invalid control input", "retryable":False}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if "code" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
