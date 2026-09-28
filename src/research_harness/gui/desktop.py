"""Windows desktop entry point with an embedded WebView2 window."""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from .app import create_app, load_context_registry
from .control import remove_descriptor, write_descriptor


def _show_webview2_guidance(error: Exception) -> None:
    message = ("Research Harness could not open its desktop window.\n\n"
               "This Windows installation may not have the Microsoft Edge WebView2 Evergreen Runtime. "
               "Install it from https://developer.microsoft.com/microsoft-edge/webview2/ and restart the application.\n\n"
               f"Details: {error}")
    print(message, file=sys.stderr, flush=True)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Research Harness — WebView2 required", 0x10)
        except Exception:
            pass


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))


def _default_workspace() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "ResearchHarnessGUI-workspace"
    return Path.cwd() / ".local" / "gui-desktop-workspace"


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Harness local desktop GUI")
    parser.add_argument("--workspace", type=Path, default=_default_workspace())
    parser.add_argument("--library-workspace", type=Path, help="read-only RAG library workspace")
    parser.add_argument("--context-config", type=Path, help="trusted local workspace/library registration JSON")
    parser.add_argument("--port", type=int, default=0, help="0 selects a free local port")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    static_dir = _bundle_root() / "frontend" / "dist"
    if not (static_dir / "index.html").is_file():
        parser.error(f"Frontend files missing: {static_dir}")
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(workspace / "desktop.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    config = Path(sys.executable).resolve().parent / "library-workspace.txt" if getattr(sys, "frozen", False) else None
    configured = Path(config.read_text(encoding="utf-8").strip()) if config and config.is_file() else None
    library_workspace = (args.library_workspace or configured or workspace).resolve()
    if library_workspace != workspace and not ((library_workspace / "rag.sqlite").is_file() and (library_workspace / "qdrant").is_dir()):
        raise FileNotFoundError(f"Configured literature library is unavailable: {library_workspace}")
    bundled_context_config=Path(sys.executable).resolve().parent/"gui-contexts.json" if getattr(sys,"frozen",False) else None
    context_config=args.context_config or bundled_context_config
    context_registrations=load_context_registry(context_config) if context_config and context_config.is_file() else ({},{})
    model_config = Path(sys.executable).resolve().parent / "rag-model-cache.txt" if getattr(sys, "frozen", False) else None
    if model_config and model_config.is_file():
        model_cache = Path(model_config.read_text(encoding="utf-8").strip()).resolve()
        if not model_cache.is_dir():
            raise FileNotFoundError(f"Configured RAG model cache is unavailable: {model_cache}")
        os.environ["RAG_MODEL_CACHE"] = str(model_cache)
        os.environ["HF_HUB_OFFLINE"] = "1"
    mcp_config = Path(sys.executable).resolve().parent / "mcp-python.txt" if getattr(sys, "frozen", False) else None
    mcp_python = Path(mcp_config.read_text(encoding="utf-8").strip()) if mcp_config and mcp_config.is_file() else Path(sys.executable)
    token = secrets.token_urlsafe(32)
    server_ref = {}
    window_ref = {}
    def shutdown_desktop() -> None:
        server_ref["server"].should_exit = True
        window = window_ref.get("window")
        if window is not None:
            window.destroy()
    app = create_app(workspace, static_dir=static_dir, token=token, library_workspace=library_workspace,
                     desktop_shutdown=shutdown_desktop, mcp_python=mcp_python,
                     registered_workspaces=context_registrations[0],registered_libraries=context_registrations[1])

    # Holding the socket until Uvicorn starts avoids accidentally opening an
    # unrelated service if the selected port is taken in the meantime.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen(128)
    port = listener.getsockname()[1]
    write_descriptor(workspace, f"http://127.0.0.1:{port}", token)
    listener.set_inheritable(True)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server_ref["server"] = server

    print(f"Research Harness GUI: http://127.0.0.1:{port}/", flush=True)
    print(f"Workspace: {workspace}; library: {library_workspace}", flush=True)
    try:
        if args.no_browser:
            server.run(sockets=[listener])
        else:
            try:
                import webview
            except Exception as exc:
                _show_webview2_guidance(exc)
                return
            webview.settings["ALLOW_DOWNLOADS"] = True
            worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            worker.start()
            for _ in range(100):
                if server.started:
                    break
                if not worker.is_alive():
                    raise RuntimeError("Local GUI service stopped before the window opened")
                time.sleep(0.1)
            else:
                raise TimeoutError("Local GUI service did not start")
            window_ref["window"] = webview.create_window("CirootHarness", f"http://127.0.0.1:{port}/",
                                                           width=1440, height=900, min_size=(850, 600))
            try:
                webview.start(gui="edgechromium", private_mode=False, storage_path=str(workspace / "webview"))
            except Exception as exc:
                _show_webview2_guidance(exc)
            finally:
                server.should_exit = True
                worker.join(timeout=10)
    finally:
        remove_descriptor(workspace)
        listener.close()


if __name__ == "__main__":
    main()
