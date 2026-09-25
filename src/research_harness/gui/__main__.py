import argparse
import secrets
from pathlib import Path

import uvicorn
from .app import create_app, load_context_registry
from .control import remove_descriptor, write_descriptor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--static-dir")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--context-config", help="trusted local workspace/library registration JSON")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    contexts=load_context_registry(args.context_config) if args.context_config else ({}, {})
    app = create_app(Path(args.workspace), static_dir=args.static_dir, token=token, registered_workspaces=contexts[0], registered_libraries=contexts[1])
    workspace = Path(args.workspace)
    write_descriptor(workspace, f"http://127.0.0.1:{args.port}", token)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        remove_descriptor(workspace)


if __name__ == "__main__":
    main()
