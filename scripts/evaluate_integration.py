"""Evaluate three frozen result bundles without executing a model or source."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_harness.integration_evaluation import EvaluationInputError, evaluate_bundle


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs_no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True, help="frozen case JSON, including frozen evidence and comparison contract")
    parser.add_argument("--results-dir", type=Path, required=True, help="directory containing rag.json, paperqa.json and storm.json")
    parser.add_argument("--annotations", type=Path, help="optional manually completed annotation JSON")
    parser.add_argument("--output", type=Path, help="write evaluation JSON here; stdout when omitted")
    args = parser.parse_args(argv)
    try:
        case = _read(args.case)
        runs = {name: _read(args.results_dir / f"{name}.json") for name in ("rag", "paperqa", "storm")}
        annotations = _read(args.annotations) if args.annotations else None
        report = evaluate_bundle(case, runs, annotations)
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, ValueError, EvaluationInputError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
