"""Bounded real OpenAlex/collection probe; stores public results, never headers."""
from __future__ import annotations
import argparse
import json
import os
import time
from pathlib import Path
import requests
from research_harness import literature


class ObservedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.events = []

    def get(self, url, **kwargs):
        start = time.perf_counter()
        event = {"endpoint": url.split("?")[0]}
        params = kwargs.get("params", {})
        event["params"] = {k: v for k, v in params.items() if k != "api_key"}
        try:
            response = super().get(url, **kwargs)
            event["http_status"] = response.status_code
            if event["endpoint"] == literature.OPENALEX_URL and response.status_code == 200:
                payload = response.json()
                event["meta"] = payload.get("meta", {})
                event["ids"] = [x.get("id") for x in payload.get("results", [])]
            return response
        except requests.RequestException as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["seconds"] = round(time.perf_counter() - start, 3)
            self.events.append(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    session = ObservedSession()
    start = time.perf_counter()
    try:
        result = literature.search(config, session=session)
    except literature.LiteratureError as exc:
        result = exc.as_dict()
    report = {"module": literature.__file__, "key_present": bool(os.environ.get("OPENALEX_API_KEY")),
              "config": config, "seconds": round(time.perf_counter()-start, 3),
              "http": session.events, "result": result}
    (args.output / "search.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "candidates.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"seconds": report["seconds"], "http_statuses": [x.get("http_status") for x in session.events],
                      "records": len(result.get("records", [])), "search_status": result.get("search_status", result.get("error"))}))


if __name__ == "__main__":
    main()
