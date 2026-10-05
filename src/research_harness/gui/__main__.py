"""Run the local research service or the isolated read-only demo projection."""
from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
from pathlib import Path

import uvicorn


def resolve_server_settings(host: str, raw_allowed_hosts: str | None, profile: str) -> tuple[str, list[str], str]:
    """Validate the bind/profile boundary before importing or constructing an app."""
    if profile not in {"research", "demo"}:
        raise ValueError("profile must be 'research' or 'demo'")
    host = host.strip().lower()
    if not host:
        raise ValueError("host must not be empty")
    is_loopback = host == "localhost"
    try:
        is_loopback = is_loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if raw_allowed_hosts is None:
        if not is_loopback:
            raise ValueError("non-loopback binding requires explicit --allowed-hosts or RH_ALLOWED_HOSTS")
        allowed = ["127.0.0.1", "localhost", "[::1]"]
    else:
        allowed = list(dict.fromkeys(value.strip().lower().rstrip(".") for value in raw_allowed_hosts.split(",") if value.strip()))
        if not allowed:
            raise ValueError("allowed-hosts must list at least one exact hostname")
    if any("*" in value or "/" in value or (":" in value and not (value.startswith("[") and value.endswith("]"))) for value in allowed):
        raise ValueError("allowed-hosts entries must be exact hostnames or bracketed IPv6 addresses")
    wildcard_bind = host in {"0.0.0.0", "::"}
    if not is_loopback and not wildcard_bind and host not in allowed and f"[{host}]" not in allowed:
        raise ValueError("a specific non-loopback bind address must also appear in allowed-hosts")
    return host, allowed, profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Research Harness or its read-only synthetic demo")
    parser.add_argument("--workspace", default=os.environ.get("RH_WORKSPACE"))
    parser.add_argument("--library-workspace", default=os.environ.get("RH_LIBRARY_WORKSPACE"))
    parser.add_argument("--static-dir", default=os.environ.get("RH_STATIC_DIR"))
    parser.add_argument("--snapshot-dir", default=os.environ.get("RH_DEMO_SNAPSHOT"))
    parser.add_argument("--context-config", default=os.environ.get("RH_CONTEXT_CONFIG"))
    parser.add_argument("--host", default=os.environ.get("RH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RH_PORT", "8765")))
    parser.add_argument("--profile", choices=("research", "demo"), default=os.environ.get("RH_PROFILE", "research"))
    parser.add_argument("--allowed-hosts", default=os.environ.get("RH_ALLOWED_HOSTS"), help="comma-separated exact HTTP Host names")
    args = parser.parse_args(argv)
    try:
        host, allowed_hosts, profile = resolve_server_settings(args.host, args.allowed_hosts, args.profile)
        if not 1 <= args.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if profile == "demo":
            if not args.snapshot_dir:
                raise ValueError("--snapshot-dir or RH_DEMO_SNAPSHOT is required for the demo profile")
            from .demo_app import create_demo_app
            app = create_demo_app(args.snapshot_dir, allowed_hosts=allowed_hosts)
            uvicorn.run(app, host=host, port=args.port, server_header=False)
            return 0
        if not args.workspace:
            raise ValueError("--workspace or RH_WORKSPACE is required for the research profile")
        from .app import create_app, load_context_registry
        from .control import remove_descriptor, write_descriptor

        token = os.environ.get("RH_SESSION_TOKEN") or secrets.token_urlsafe(32)
        contexts = load_context_registry(args.context_config) if args.context_config else ({}, {})
        app = create_app(Path(args.workspace), static_dir=args.static_dir, token=token,
                         library_workspace=args.library_workspace,
                         registered_workspaces=contexts[0], registered_libraries=contexts[1],
                         profile=profile, allowed_hosts=allowed_hosts)
        workspace = Path(args.workspace)
        descriptor_enabled = host in {"127.0.0.1", "localhost"}
        if descriptor_enabled:
            write_descriptor(workspace, f"http://127.0.0.1:{args.port}", token)
        try:
            uvicorn.run(app, host=host, port=args.port, server_header=False)
        finally:
            if descriptor_enabled:
                remove_descriptor(workspace)
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
