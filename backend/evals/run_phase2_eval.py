"""Minimal internal evaluation runner for the active Physics PDF workflow.

Run from `backend/`:
    python evals/run_phase2_eval.py
    python evals/run_phase2_eval.py --dataset evals/samples/physics_phase2_eval.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_DATASET = Path(__file__).with_name("samples") / "physics_phase2_eval.json"


def load_dataset(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Eval dataset must be a JSON array")
    return payload


def compute_metrics(samples: list[dict]) -> dict:
    total_questions = 0
    scope_violations = 0
    evidence_covered = 0
    retrieval_hits = 0
    verifier_passes = 0
    total_regenerates = 0
    total_human_edits = 0

    for sample in samples:
        expected_sections = {
            str(item).strip()
            for item in sample.get("expected_scope_section_ids") or []
            if str(item).strip()
        }
        for question in sample.get("questions") or []:
            total_questions += 1
            evidence = [
                item
                for item in question.get("source_evidence") or []
                if isinstance(item, dict)
            ]
            if evidence:
                evidence_covered += 1
            evidence_section_ids = {
                str(item.get("section_id") or "").strip()
                for item in evidence
                if str(item.get("section_id") or "").strip()
            }
            if expected_sections and evidence_section_ids and not evidence_section_ids.issubset(expected_sections):
                scope_violations += 1
            if expected_sections and not evidence_section_ids:
                scope_violations += 1

            top_hits = [
                str(item).strip()
                for item in question.get("retrieval", {}).get("top_section_ids") or []
                if str(item).strip()
            ]
            if expected_sections and any(item in expected_sections for item in top_hits):
                retrieval_hits += 1

            if str(question.get("verification_status") or "").strip().lower() == "passed":
                verifier_passes += 1

            total_regenerates += int(question.get("regenerate_count") or 0)
            total_human_edits += int(question.get("human_edit_count") or 0)

    denominator = max(total_questions, 1)
    return {
        "sample_count": len(samples),
        "question_count": total_questions,
        "scope_violation_rate": round(scope_violations / denominator, 4),
        "evidence_coverage_rate": round(evidence_covered / denominator, 4),
        "retrieval_hit_quality": round(retrieval_hits / denominator, 4),
        "verifier_pass_rate": round(verifier_passes / denominator, 4),
        "avg_regenerate_count": round(total_regenerates / denominator, 4),
        "avg_human_edit_count": round(total_human_edits / denominator, 4),
    }


def render_report(metrics: dict) -> str:
    return "\n".join(
        [
            "Phase 2 Eval Report",
            f"- Samples: {metrics['sample_count']}",
            f"- Questions: {metrics['question_count']}",
            f"- Scope violation rate: {metrics['scope_violation_rate']:.2%}",
            f"- Evidence coverage rate: {metrics['evidence_coverage_rate']:.2%}",
            f"- Retrieval hit quality: {metrics['retrieval_hit_quality']:.2%}",
            f"- Verifier pass rate: {metrics['verifier_pass_rate']:.2%}",
            f"- Avg regenerate count: {metrics['avg_regenerate_count']:.2f}",
            f"- Avg human edit count: {metrics['avg_human_edit_count']:.2f}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run minimal Phase 2 eval metrics")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()

    samples = load_dataset(args.dataset)
    metrics = compute_metrics(samples)
    print(render_report(metrics))


if __name__ == "__main__":
    main()
