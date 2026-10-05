"""Serve only a hash-verified synthetic demo snapshot and exported reports."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response


_ALLOWED_FILES = {"snapshot.json", "technical_report.md", "literature_review.md"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_demo_app(snapshot_dir: str | Path, *, allowed_hosts: list[str] | None = None) -> FastAPI:
    """No InvestigationService, workspace, source connector, model or write API is created."""
    root = Path(snapshot_dir).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("demo snapshot manifest is unavailable or invalid") from exc
    if not isinstance(files, dict) or set(files) != _ALLOWED_FILES:
        raise ValueError("demo manifest must list exactly the fixed snapshot and two report files")
    for name, checksum in files.items():
        path = (root / name).resolve()
        if path.parent != root or not isinstance(checksum, str) or len(checksum) != 64 or _digest(path) != checksum:
            raise ValueError(f"demo artifact failed its SHA-256 check: {name}")
    try:
        snapshot = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("demo snapshot JSON is unreadable") from exc
    demo = snapshot.get("demo") if isinstance(snapshot, dict) else None
    result = demo.get("result") if isinstance(demo, dict) else None
    if snapshot.get("profile") != "demo" or not isinstance(result, dict) or result.get("synthetic") is not True:
        raise ValueError("demo snapshot is not marked as a synthetic Golden Demo")
    hostnames = set()
    for raw in allowed_hosts or ["127.0.0.1", "localhost"]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip().lower().rstrip(".")
        if value.startswith("[") and value.endswith("]") and ":" in value:
            value = value[1:-1]
        elif ":" in value or "/" in value or "*" in value:
            raise ValueError("demo allowed_hosts must contain exact hostnames")
        hostnames.add(value)
    if not hostnames:
        raise ValueError("demo allowed_hosts must contain at least one hostname")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    allowed_gets = {"/api/v1/demo"}

    @app.middleware("http")
    async def isolate(request: Request, call_next):
        hostname = (request.url.hostname or "").lower().rstrip(".")
        if hostname not in hostnames:
            return JSONResponse({"code": "RH_DEMO_HOST", "message": "host is not allowed"}, status_code=403)
        path = request.url.path
        if path.startswith("/api/"):
            report_route = path.startswith("/api/v1/demo/reports/") or path.startswith("/api/v1/demo/download/")
            if request.method != "GET" or (path not in allowed_gets and not report_route):
                return JSONResponse({"code": "RH_DEMO_READ_ONLY", "message": "demo API is read-only"}, status_code=403)
        elif path != "/" and path != "/health":
            return JSONResponse({"code": "RH_DEMO_NOT_FOUND", "message": "demo page is not available"}, status_code=404)
        return await call_next(request)

    def verified_file(name: str) -> bytes:
        if name not in files:
            raise ValueError("artifact is not on the demo allow list")
        path = root / name
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != files[name]:
            raise ValueError("demo artifact hash changed after startup")
        return content

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return HTMLResponse(_DEMO_HTML)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "profile": "demo", "synthetic": True, "read_only": True}

    @app.get("/api/v1/demo")
    def demo_read():
        return snapshot

    @app.get("/api/v1/demo/reports/{name}")
    def report_read(name: str):
        if name not in {"technical_report.md", "literature_review.md"}:
            return JSONResponse({"code": "RH_DEMO_REPORT_NOT_FOUND", "message": "report is not on the allow list"}, status_code=404)
        try:
            return Response(verified_file(name), media_type="text/markdown; charset=utf-8", headers={"Cache-Control": "no-store"})
        except (OSError, ValueError):
            return JSONResponse({"code": "RH_DEMO_ARTIFACT_HASH", "message": "report failed its integrity check"}, status_code=503)

    @app.get("/api/v1/demo/download/{name}")
    def report_download(name: str):
        if name not in {"technical_report.md", "literature_review.md"}:
            return JSONResponse({"code": "RH_DEMO_REPORT_NOT_FOUND", "message": "report is not on the allow list"}, status_code=404)
        try:
            content = verified_file(name)
            return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
        except (OSError, ValueError):
            return JSONResponse({"code": "RH_DEMO_ARTIFACT_HASH", "message": "report failed its integrity check"}, status_code=503)

    return app


_DEMO_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research Harness synthetic demo</title>
<style>body{font:16px system-ui,sans-serif;max-width:900px;margin:3rem auto;padding:0 1rem;color:#18222c}header{border-bottom:1px solid #ccd4dc}small{color:#526170}li{margin:.6rem 0}button{margin-left:.7rem}pre{white-space:pre-wrap;background:#f4f6f8;padding:1rem;max-height:65vh;overflow:auto}</style></head>
<body><header><h1>Research Harness · Synthetic demo</h1><p>This fixed example uses synthetic data. It cannot start research runs or connect to research sources.</p><small id="state">Loading frozen report snapshot…</small></header><main><h2>Reports</h2><ul id="reports"></ul><h2 id="report-title">Report preview</h2><pre id="report">Choose a report above.</pre></main>
<script>
const state=document.querySelector('#state'), list=document.querySelector('#reports'), preview=document.querySelector('#report');
fetch('/api/v1/demo').then(r=>{if(!r.ok)throw Error('Snapshot unavailable');return r.json()}).then(({demo})=>{
 if(!demo||demo.result?.synthetic!==true)throw Error('Snapshot is not synthetic');
 state.textContent='Frozen synthetic run · '+(demo.status?.status||'completed');
 for(const report of demo.reports||[]){const li=document.createElement('li'), open=document.createElement('a'), download=document.createElement('a');
  open.href='#';open.textContent=report.type+' ('+report.language+')';open.onclick=async e=>{e.preventDefault();const r=await fetch('/api/v1/demo/reports/'+encodeURIComponent(report.filename));if(!r.ok){preview.textContent='Report unavailable';return}preview.textContent=await r.text();document.querySelector('#report-title').textContent=report.type};
  download.href='/api/v1/demo/download/'+encodeURIComponent(report.filename);download.textContent='Download';download.setAttribute('download',report.filename);li.append(open,' ',download);list.append(li)}
}).catch(e=>{state.textContent='Demo unavailable: '+e.message});
</script></body></html>"""
