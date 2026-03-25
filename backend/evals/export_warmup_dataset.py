"""Export a Phase 4 warmup dataset snapshot from the current database."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import async_session
from app.services.playbook.warmup_service import WarmupExportService


async def _run(output_path: Path) -> None:
    async with async_session() as session:
        report = await WarmupExportService(session).build_global_export()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "Phase 4 warmup export",
        f"- exam_cases: {len(report['exam_cases'])}",
        f"- question_cases: {len(report['question_cases'])}",
        f"- feedback_cases: {len(report['feedback_cases'])}",
        sep="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Phase 4 ACE warmup dataset")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/output/warmup_dataset.json"),
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.output))
    except Exception as exc:
        raise SystemExit(
            "Warmup export failed. Check that the configured database is reachable "
            f"before rerunning the command. Root cause: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
