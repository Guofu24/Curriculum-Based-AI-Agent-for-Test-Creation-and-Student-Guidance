"""Run the Phase 3 evaluation dataset and quality report."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evals.phase3_eval import (
    DEFAULT_DATASET_ROOT,
    build_phase3_report,
    render_console_report,
    write_csv_report,
    write_json_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 3 quality evaluation")
    parser.add_argument("--split", default="all", choices=["all", "dev", "held_out"])
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    args = parser.parse_args()

    report = build_phase3_report(
        dataset_root=args.dataset_root,
        split=args.split,
        dataset=args.dataset,
    )
    print(render_console_report(report))

    if args.json_out:
        write_json_report(report, args.json_out)
    if args.csv_out:
        write_csv_report(report["question_rows"], args.csv_out)


if __name__ == "__main__":
    main()
