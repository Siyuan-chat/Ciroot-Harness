"""Verify one real OA PDF and offline reuse through installed public APIs."""
import argparse
import base64
import hashlib
import json
import time
from pathlib import Path
from research_harness import literature
from research_harness.investigation_sources import normalize


class NoNetwork:
    def get(self, *args, **kwargs):
        raise AssertionError("reuse attempted a network request")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--reuse", action="store_true")
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    start = time.perf_counter()
    result = literature.download(manifest, args.output, limit=1, session=NoNetwork() if args.reuse else None)
    report = {"module": literature.__file__, "reuse": args.reuse,
              "download_seconds": round(time.perf_counter()-start, 3), "catalog": result}
    for item in result["records"]:
        d = item["download"]
        if d["status"] != "success":
            continue
        pdf = args.output / d["path"]
        blob = pdf.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == d["sha256"]
        if args.reuse:
            report["pdf_bytes"] = len(blob)
            assert result["received_bytes"] == 0
            continue
        start = time.perf_counter()
        evidence = normalize({"document_id": item["record"]["source_id"], "version": d["sha256"],
                              "content_type": "application/pdf", "base64_bytes": base64.b64encode(blob).decode()})
        report["extraction_seconds"] = round(time.perf_counter()-start, 3)
        report["evidence_pages"] = len(evidence)
        report["physical_pages"] = [x["locator"]["value"] for x in evidence]
        report["pdf_bytes"] = len(blob)
        (args.output / "page-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    target = args.output / ("reuse-probe.json" if args.reuse else "download-probe.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "catalog"}, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ("outcome", "valid_pdf_count", "received_bytes")}))
    raise SystemExit(0 if result["valid_pdf_count"] == 1 else 4)


if __name__ == "__main__":
    main()
