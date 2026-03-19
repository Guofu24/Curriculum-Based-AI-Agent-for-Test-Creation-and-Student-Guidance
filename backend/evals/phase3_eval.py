"""Phase 3 internal evaluation helpers."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


DEFAULT_DATASET_ROOT = Path(__file__).with_name("datasets") / "physics"
VALID_SPLITS = {"dev", "held_out", "all"}
GENERATION_ERROR_CATEGORIES = {
    "wrong_answer_key",
    "ambiguous_options",
    "duplicate_question",
    "verbatim_copy",
}


def _sorted_sample_files(dataset_root: Path, split: str) -> list[Path]:
    if split == "all":
        paths = list((dataset_root / "dev").glob("*.json")) + list((dataset_root / "held_out").glob("*.json"))
    else:
        paths = list((dataset_root / split).glob("*.json"))
    return sorted(path for path in paths if path.is_file() and path.stem != "sample_template")


def _question_list(sample: dict) -> list[dict]:
    return [item for item in (sample.get("questions") or []) if isinstance(item, dict)]


def _normalize_scope(sample: dict) -> tuple[set[str], set[str]]:
    scope_payload = sample.get("scope") or {}
    allowed_scope = {
        str(item).strip()
        for item in (
            scope_payload.get("allowed_section_ids")
            or sample.get("allowed_scope_section_ids")
            or sample.get("expected_scope_section_ids")
            or []
        )
        if str(item).strip()
    }
    expected_coverage = {
        str(item).strip()
        for item in (
            scope_payload.get("expected_section_coverage")
            or sample.get("expected_section_coverage")
            or allowed_scope
        )
        if str(item).strip()
    }
    return allowed_scope, expected_coverage or allowed_scope


def _normalize_sample(payload: dict, source_path: Path, default_split: str | None = None) -> dict:
    split = str(payload.get("split") or default_split or source_path.parent.name or "dev").strip().lower()
    if split not in {"dev", "held_out"}:
        split = default_split or "dev"
    sample = dict(payload)
    sample["split"] = split
    sample["sample_id"] = str(sample.get("sample_id") or source_path.stem).strip()
    sample["source_path"] = str(source_path)
    sample.setdefault("document", {})
    sample.setdefault("scope", {})
    sample.setdefault("exam_request", {})
    sample.setdefault("normalized_spec", {})
    sample["questions"] = _question_list(sample)
    sample["version_count"] = int(sample.get("version_count") or 1)
    return sample


def load_eval_samples(
    *,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    split: str = "all",
    dataset: Path | None = None,
) -> list[dict]:
    normalized_split = str(split or "all").strip().lower()
    if normalized_split not in VALID_SPLITS:
        raise ValueError(f"Unsupported split '{split}'")

    if dataset:
        if dataset.is_dir():
            files = sorted(path for path in dataset.rglob("*.json") if path.stem != "sample_template")
        else:
            files = [dataset]
    else:
        files = _sorted_sample_files(dataset_root, normalized_split)

    samples: list[dict] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for index, item in enumerate(payload, start=1):
                if isinstance(item, dict):
                    legacy_path = Path(f"{path}#sample-{index}")
                    samples.append(_normalize_sample(item, legacy_path, default_split=normalized_split))
            continue
        if isinstance(payload, dict):
            samples.append(_normalize_sample(payload, path, default_split=normalized_split))

    return samples


def _classify_question(sample: dict, question: dict) -> tuple[list[str], dict]:
    allowed_scope, expected_coverage = _normalize_scope(sample)
    quality_signals = question.get("quality_signals") or {}
    evidence = [item for item in (question.get("source_evidence") or []) if isinstance(item, dict)]
    evidence_section_ids = {
        str(item.get("section_id") or "").strip()
        for item in evidence
        if str(item.get("section_id") or "").strip()
    }
    retrieval = question.get("retrieval") or {}
    top_section_ids = [
        str(item).strip()
        for item in (retrieval.get("top_section_ids") or [])
        if str(item).strip()
    ]
    expected_hit_ids = {
        str(item).strip()
        for item in (retrieval.get("expected_hit_section_ids") or expected_coverage)
        if str(item).strip()
    }
    warnings = [str(item).strip().lower() for item in (question.get("warnings") or []) if str(item).strip()]
    verifier_expectation = question.get("verifier_expectation") or {}
    actual_status = str(question.get("verification_status") or "").strip().lower()
    expected_status = str(verifier_expectation.get("expected_status") or "").strip().lower()

    scope_violation = bool(quality_signals.get("scope_leak"))
    if allowed_scope and evidence_section_ids and not evidence_section_ids.issubset(allowed_scope):
        scope_violation = True

    retrieval_score = 0.0
    if expected_hit_ids and top_section_ids:
        if top_section_ids[0] in expected_hit_ids:
            retrieval_score = 1.0
        elif any(item in expected_hit_ids for item in top_section_ids):
            retrieval_score = 0.5
    retrieval_hit = retrieval_score > 0

    categories: list[str] = []
    if scope_violation:
        categories.append("scope_leak")
    if bool(quality_signals.get("weak_evidence")) or not evidence or any(
        phrase in warning for phrase in ("grounding", "supported", "missing evidence", "weakly supported")
        for warning in warnings
    ):
        categories.append("weak_evidence")
    if not retrieval_hit:
        categories.append("retrieval_miss")
    if bool(quality_signals.get("wrong_answer_key")) or any(
        phrase in warning for phrase in ("correct_answer", "option labels", "4 options")
        for warning in warnings
    ):
        categories.append("wrong_answer_key")
    if bool(quality_signals.get("ambiguous_options")) or any(
        phrase in warning for phrase in ("ambiguous", "distractor")
        for warning in warnings
    ):
        categories.append("ambiguous_options")
    if quality_signals.get("duplicate_with_question_id") or any("duplicate" in warning for warning in warnings):
        categories.append("duplicate_question")
    if bool(quality_signals.get("verbatim_copy")):
        categories.append("verbatim_copy")
    if expected_status == "failed" and actual_status == "passed":
        categories.append("verifier_false_pass")
    if expected_status == "passed" and actual_status == "failed":
        categories.append("verifier_false_fail")

    return categories, {
        "allowed_scope": sorted(allowed_scope),
        "expected_coverage": sorted(expected_coverage),
        "evidence_section_ids": sorted(evidence_section_ids),
        "top_section_ids": top_section_ids,
        "expected_hit_ids": sorted(expected_hit_ids),
        "scope_violation": scope_violation,
        "evidence_covered": bool(evidence),
        "retrieval_score": retrieval_score,
        "retrieval_hit": retrieval_hit,
        "verifier_pass": actual_status == "passed",
        "verifier_warning": bool(question.get("warnings")),
        "actual_status": actual_status or None,
        "expected_status": expected_status or None,
    }


def flatten_question_rows(samples: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for sample in samples:
        for question in _question_list(sample):
            categories, derived = _classify_question(sample, question)
            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "split": sample["split"],
                    "document_id": str((sample.get("document") or {}).get("document_id") or "").strip() or None,
                    "version_count": int(sample.get("version_count") or 1),
                    "question_id": str(question.get("question_id") or question.get("question_number") or "").strip() or None,
                    "question_text": str(question.get("question_text") or "").strip(),
                    "regenerate_count": int(question.get("regenerate_count") or 0),
                    "human_edit_count": int(question.get("human_edit_count") or 0),
                    "error_categories": categories,
                    **derived,
                }
            )
    return rows


def _compute_metrics_from_rows(rows: list[dict]) -> dict:
    question_count = len(rows)
    question_denominator = max(question_count, 1)
    unique_samples = {row["sample_id"] for row in rows}
    sample_denominator = max(len(unique_samples), 1)

    category_counter: Counter[str] = Counter(
        category for row in rows for category in row["error_categories"]
    )

    return {
        "sample_count": len(unique_samples),
        "question_count": question_count,
        "scope_violation_rate": round(sum(1 for row in rows if row["scope_violation"]) / question_denominator, 4),
        "evidence_coverage_rate": round(sum(1 for row in rows if row["evidence_covered"]) / question_denominator, 4),
        "retrieval_hit_quality": round(sum(float(row["retrieval_score"]) for row in rows) / question_denominator, 4),
        "verifier_pass_rate": round(sum(1 for row in rows if row["verifier_pass"]) / question_denominator, 4),
        "verifier_warning_rate": round(sum(1 for row in rows if row["verifier_warning"]) / question_denominator, 4),
        "generation_issue_rate": round(
            sum(1 for row in rows if any(category in GENERATION_ERROR_CATEGORIES for category in row["error_categories"]))
            / question_denominator,
            4,
        ),
        "verifier_alignment_rate": round(
            sum(1 for row in rows if not {"verifier_false_pass", "verifier_false_fail"} & set(row["error_categories"]))
            / question_denominator,
            4,
        ),
        "avg_regenerate_count": round(sum(int(row["regenerate_count"]) for row in rows) / question_denominator, 4),
        "avg_human_edit_count": round(sum(int(row["human_edit_count"]) for row in rows) / question_denominator, 4),
        "version_churn": round(
            sum(max(int(row["version_count"]) - 1, 0) for row in rows) / sample_denominator,
            4,
        ),
        "top_error_categories": [
            {"category": category, "count": count}
            for category, count in category_counter.most_common(8)
        ],
    }


def build_phase3_report(
    *,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    split: str = "all",
    dataset: Path | None = None,
) -> dict:
    samples = load_eval_samples(dataset_root=dataset_root, split=split, dataset=dataset)
    rows = flatten_question_rows(samples)
    split_breakdown = {
        current_split: _compute_metrics_from_rows([row for row in rows if row["split"] == current_split])
        for current_split in ("dev", "held_out")
        if any(row["split"] == current_split for row in rows)
    }

    error_rows = [
        {
            "sample_id": row["sample_id"],
            "split": row["split"],
            "question_id": row["question_id"],
            "question_text": row["question_text"],
            "error_categories": row["error_categories"],
        }
        for row in rows
        if row["error_categories"]
    ]

    return {
        "meta": {
            "dataset_root": str(dataset_root),
            "dataset": str(dataset) if dataset else None,
            "split": split,
        },
        "metrics": _compute_metrics_from_rows(rows),
        "split_breakdown": split_breakdown,
        "error_rows": error_rows,
        "question_rows": rows,
    }


def build_error_analysis(
    *,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    split: str = "all",
    dataset: Path | None = None,
    report: dict | None = None,
) -> dict:
    phase3_report = report or build_phase3_report(
        dataset_root=dataset_root,
        split=split,
        dataset=dataset,
    )
    buckets: dict[str, dict] = {}

    for row in phase3_report["error_rows"]:
        for category in row["error_categories"]:
            bucket = buckets.setdefault(
                category,
                {
                    "category": category,
                    "count": 0,
                    "samples": [],
                },
            )
            bucket["count"] += 1
            if len(bucket["samples"]) < 5:
                bucket["samples"].append(
                    {
                        "sample_id": row["sample_id"],
                        "split": row["split"],
                        "question_id": row["question_id"],
                        "question_text": row["question_text"],
                    }
                )

    categories = sorted(
        buckets.values(),
        key=lambda item: (-item["count"], item["category"]),
    )
    return {
        "meta": dict(phase3_report["meta"]),
        "metrics": dict(phase3_report["metrics"]),
        "categories": categories,
        "sample_count": sum(item["count"] for item in categories),
    }


def render_console_report(report: dict) -> str:
    metrics = report["metrics"]
    lines = [
        "Phase 3 Eval Report",
        f"- Split: {report['meta']['split']}",
        f"- Samples: {metrics['sample_count']}",
        f"- Questions: {metrics['question_count']}",
        "",
        "Scope quality",
        f"- scope_violation_rate: {metrics['scope_violation_rate']:.2%}",
        f"- retrieval_hit_quality: {metrics['retrieval_hit_quality']:.2%}",
        "",
        "Evidence quality",
        f"- evidence_coverage_rate: {metrics['evidence_coverage_rate']:.2%}",
        "",
        "Generation quality",
        f"- generation_issue_rate: {metrics['generation_issue_rate']:.2%}",
        "",
        "Verification quality",
        f"- verifier_pass_rate: {metrics['verifier_pass_rate']:.2%}",
        f"- verifier_warning_rate: {metrics['verifier_warning_rate']:.2%}",
        f"- verifier_alignment_rate: {metrics['verifier_alignment_rate']:.2%}",
        "",
        "Review friction",
        f"- avg_regenerate_count: {metrics['avg_regenerate_count']:.2f}",
        f"- avg_human_edit_count: {metrics['avg_human_edit_count']:.2f}",
        f"- version_churn: {metrics['version_churn']:.2f}",
        "",
        "Top error categories",
    ]
    if metrics["top_error_categories"]:
        lines.extend(
            f"- {item['category']}: {item['count']}"
            for item in metrics["top_error_categories"]
        )
    else:
        lines.append("- none")

    if report["error_rows"]:
        lines.extend(["", "Trace samples"])
        lines.extend(
            f"- {row['sample_id']} / {row['question_id'] or 'question'}: {', '.join(row['error_categories'])}"
            for row in report["error_rows"][:5]
        )

    return "\n".join(lines)


def render_error_analysis_report(report: dict) -> str:
    lines = [
        "Phase 3 Error Analysis",
        f"- Split: {report['meta']['split']}",
        f"- Categorized errors: {report['sample_count']}",
        "",
        "Top categories",
    ]

    if not report["categories"]:
        lines.append("- none")
        return "\n".join(lines)

    for category in report["categories"]:
        lines.append(f"- {category['category']}: {category['count']}")
        for sample in category["samples"][:3]:
            question_id = sample["question_id"] or "question"
            lines.append(
                f"  {sample['sample_id']} / {question_id} ({sample['split']})"
            )

    return "\n".join(lines)


def write_json_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_report(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "split",
        "document_id",
        "question_id",
        "question_text",
        "scope_violation",
        "evidence_covered",
        "retrieval_score",
        "verifier_pass",
        "verifier_warning",
        "expected_status",
        "actual_status",
        "regenerate_count",
        "human_edit_count",
        "version_count",
        "error_categories",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            payload["error_categories"] = ",".join(row["error_categories"])
            writer.writerow({key: payload.get(key) for key in fieldnames})
