"""Read-only checker for document chunks stored in Pinecone.

Examples:
    python scripts/check_doc_chunks.py --doc-id <uuid> --section-id ch1_sec2
    python scripts/check_doc_chunks.py --doc-id <uuid> --section-id ch1_sec2 --show-content
    python scripts/check_doc_chunks.py --doc-id <uuid> --all-sections
    python scripts/check_doc_chunks.py --latest --section-id ch1_sec2

The script only reads Postgres and Pinecone. It does not start, stop, or modify
the running FastAPI/uvicorn backend.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class SectionInfo:
    section_id: str
    title: str
    chapter_id: str
    chapter_title: str
    level: str


def _to_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _short(text: Any, length: int) -> str:
    raw = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(raw) <= length:
        return raw
    return raw[: max(length - 3, 0)].rstrip() + "..."


def _collect_sections(heading_tree: dict) -> dict[str, SectionInfo]:
    sections: dict[str, SectionInfo] = {}
    for chapter in heading_tree.get("chapters", []) or []:
        chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
        chapter_title = str(chapter.get("title") or "")
        for section in chapter.get("sections", []) or []:
            section_id = str(section.get("section_id") or section.get("id") or "")
            section_title = str(section.get("title") or "")
            if section_id:
                sections[section_id] = SectionInfo(
                    section_id=section_id,
                    title=section_title,
                    chapter_id=chapter_id,
                    chapter_title=chapter_title,
                    level="section",
                )
            for subsection in section.get("subsections", []) or []:
                subsection_id = str(subsection.get("section_id") or subsection.get("id") or "")
                subsection_title = str(subsection.get("title") or "")
                if subsection_id:
                    title = f"{section_title} > {subsection_title}" if section_title else subsection_title
                    sections[subsection_id] = SectionInfo(
                        section_id=subsection_id,
                        title=title,
                        chapter_id=chapter_id,
                        chapter_title=chapter_title,
                        level="subsection",
                    )
    return sections


async def _load_document(doc_id: str | None, latest: bool) -> dict | None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            if latest:
                result = await conn.execute(
                    text(
                        """
                        SELECT id, original_filename, processing_status, total_chunks,
                               total_chapters, uploaded_at, heading_tree
                        FROM documents
                        ORDER BY uploaded_at DESC
                        LIMIT 1
                        """
                    )
                )
            else:
                result = await conn.execute(
                    text(
                        """
                        SELECT id, original_filename, processing_status, total_chunks,
                               total_chapters, uploaded_at, heading_tree
                        FROM documents
                        WHERE id = :doc_id
                        """
                    ),
                    {"doc_id": uuid.UUID(doc_id or "")},
                )
            row = result.mappings().first()
            return dict(row) if row else None
    finally:
        await engine.dispose()


def _namespace_count(index: Any, namespace: str) -> int | None:
    try:
        desc = _to_dict(index.describe_namespace(namespace))
        if "record_count" in desc:
            return int(desc["record_count"])
        if "vector_count" in desc:
            return int(desc["vector_count"])
    except Exception:
        pass

    try:
        stats = _to_dict(index.describe_index_stats())
        namespaces = stats.get("namespaces") or {}
        ns_info = namespaces.get(namespace) or {}
        if "vector_count" in ns_info:
            return int(ns_info["vector_count"])
    except Exception:
        pass
    return None


def _extract_ids_from_list_response(response: Any) -> tuple[list[str], str | None]:
    data = _to_dict(response)
    vectors = data.get("vectors") or []
    ids: list[str] = []
    for item in vectors:
        if isinstance(item, str):
            ids.append(item)
            continue
        item_data = _to_dict(item)
        item_id = item_data.get("id") or getattr(item, "id", None)
        if item_id:
            ids.append(str(item_id))

    pagination = data.get("pagination") or {}
    next_token = pagination.get("next") if isinstance(pagination, dict) else None
    return ids, next_token


def _iter_vector_ids(
    index: Any,
    namespace: str,
    page_size: int,
    scan_limit: int,
):
    seen = 0
    token: str | None = None
    while True:
        limit = page_size
        if scan_limit and seen + limit > scan_limit:
            limit = scan_limit - seen
        if limit <= 0:
            break

        response = index.list_paginated(
            namespace=namespace,
            limit=limit,
            pagination_token=token,
        )
        ids, token = _extract_ids_from_list_response(response)
        if not ids:
            break

        seen += len(ids)
        yield ids

        if not token or (scan_limit and seen >= scan_limit):
            break


def _fetch_metadata(index: Any, namespace: str, ids: list[str]) -> dict[str, dict]:
    response = index.fetch(ids=ids, namespace=namespace)
    data = _to_dict(response)
    vectors = data.get("vectors") or {}
    metadata_by_id: dict[str, dict] = {}
    for vector_id, vector in vectors.items():
        vector_data = _to_dict(vector)
        metadata = vector_data.get("metadata") or {}
        metadata_by_id[str(vector_id)] = metadata if isinstance(metadata, dict) else {}
    return metadata_by_id


def _scan_exact(
    index: Any,
    namespace: str,
    target_ids: set[str],
    sample_limit: int,
    content_chars: int,
    page_size: int,
    scan_limit: int,
) -> dict:
    counts: Counter[str] = Counter()
    chapter_counts: Counter[str] = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)
    scanned = 0

    for batch_ids in _iter_vector_ids(index, namespace, page_size, scan_limit):
        metadata_by_id = _fetch_metadata(index, namespace, batch_ids)
        for vector_id, metadata in metadata_by_id.items():
            scanned += 1
            section_id = str(metadata.get("section_id") or "")
            chapter_id = str(metadata.get("chapter_id") or "")
            key = section_id or "(empty)"
            counts[key] += 1
            if chapter_id:
                chapter_counts[chapter_id] += 1

            should_sample = not target_ids or section_id in target_ids
            if should_sample and len(samples[key]) < sample_limit:
                samples[key].append(
                    {
                        "vector_id": vector_id,
                        "chunk_id": metadata.get("chunk_id") or vector_id,
                        "chapter_id": chapter_id,
                        "section_id": section_id,
                        "section": metadata.get("section") or "",
                        "page_number": metadata.get("page_number") or "",
                        "content_type": metadata.get("content_type") or "",
                        "content": _short(metadata.get("content"), content_chars),
                    }
                )

    return {
        "mode": "exact",
        "counts": counts,
        "chapter_counts": chapter_counts,
        "samples": samples,
        "scanned": scanned,
    }


def _query_section_fallback(
    index: Any,
    namespace: str,
    section_id: str,
    top_k: int,
    embedding_dim: int,
    content_chars: int,
) -> dict:
    vector = [0.0] * embedding_dim
    if vector:
        vector[0] = 1.0

    response = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        filter={"section_id": {"$eq": section_id}},
        include_metadata=True,
        include_values=False,
    )
    data = _to_dict(response)
    matches = data.get("matches") or []
    samples: list[dict] = []
    for match in matches:
        match_data = _to_dict(match)
        metadata = match_data.get("metadata") or {}
        vector_id = match_data.get("id") or metadata.get("chunk_id") or ""
        samples.append(
            {
                "vector_id": vector_id,
                "chunk_id": metadata.get("chunk_id") or vector_id,
                "score": match_data.get("score"),
                "chapter_id": metadata.get("chapter_id") or "",
                "section_id": metadata.get("section_id") or "",
                "section": metadata.get("section") or "",
                "page_number": metadata.get("page_number") or "",
                "content_type": metadata.get("content_type") or "",
                "content": _short(metadata.get("content"), content_chars),
            }
        )
    return {"count_lower_bound": len(samples), "samples": samples}


def _print_tree(sections: dict[str, SectionInfo]) -> None:
    print("\nSections from DB heading_tree:")
    if not sections:
        print("  (no sections found in heading_tree)")
        return
    for section in sections.values():
        print(
            f"  {section.section_id:22s} | {section.level:10s} | "
            f"{section.chapter_id:8s} | {_short(section.title, 90)}"
        )


def _print_samples(samples: list[dict], show_content: bool) -> None:
    for sample in samples:
        page = f" page={sample['page_number']}" if sample.get("page_number") else ""
        score = ""
        if sample.get("score") is not None:
            score = f" score={sample['score']:.4f}"
        print(
            f"    - chunk_id={sample['chunk_id']} vector_id={sample['vector_id']}"
            f" chapter_id={sample.get('chapter_id', '')}"
            f" section_id={sample.get('section_id', '')}{page}{score}"
        )
        if sample.get("section"):
            print(f"      section={_short(sample['section'], 120)}")
        if show_content and sample.get("content"):
            print(f"      content={sample['content']}")


def _print_exact_report(
    result: dict,
    target_ids: list[str],
    sections: dict[str, SectionInfo],
    show_content: bool,
) -> None:
    counts: Counter[str] = result["counts"]
    samples: dict[str, list[dict]] = result["samples"]
    print(f"\nExact scan: fetched metadata for {result['scanned']} vectors")

    if target_ids:
        for section_id in target_ids:
            count = counts.get(section_id, 0)
            info = sections.get(section_id)
            title = f" ({info.title})" if info else " (not found in DB heading_tree)"
            status = "OK" if count else "MISSING"
            print(f"\n[{status}] section_id={section_id!r}: {count} chunks{title}")
            _print_samples(samples.get(section_id, []), show_content)
        return

    print("\nChunk count by section_id:")
    rows: list[tuple[str, int, str, str]] = []
    for section_id, info in sections.items():
        rows.append((section_id, counts.get(section_id, 0), info.level, info.title))
    for section_id, count in sorted(counts.items()):
        if section_id != "(empty)" and section_id not in sections:
            rows.append((section_id, count, "pinecone", "(not in DB heading_tree)"))
    if counts.get("(empty)", 0):
        rows.append(("(empty)", counts["(empty)"], "metadata", "chunks without section_id"))

    for section_id, count, level, title in rows:
        status = "OK" if count else "MISSING"
        print(f"  {status:7s} {section_id:24s} {count:5d} | {level:10s} | {_short(title, 90)}")


def _print_query_fallback_report(
    index: Any,
    namespace: str,
    target_ids: list[str],
    sections: dict[str, SectionInfo],
    top_k: int,
    embedding_dim: int,
    content_chars: int,
    show_content: bool,
) -> None:
    print("\nFallback mode: using Pinecone query filter per section.")
    print(f"Counts below are lower bounds capped by --top-k={top_k}, not exact totals.")

    for section_id in target_ids:
        info = sections.get(section_id)
        result = _query_section_fallback(
            index=index,
            namespace=namespace,
            section_id=section_id,
            top_k=top_k,
            embedding_dim=embedding_dim,
            content_chars=content_chars,
        )
        count = result["count_lower_bound"]
        title = f" ({info.title})" if info else " (not found in DB heading_tree)"
        status = "OK" if count else "MISSING"
        suffix = f"{count}+ chunks" if count >= top_k else f"{count} chunks"
        print(f"\n[{status}] section_id={section_id!r}: {suffix}{title}")
        _print_samples(result["samples"], show_content)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether a document section_id has real chunks in Pinecone."
    )
    doc_group = parser.add_mutually_exclusive_group(required=True)
    doc_group.add_argument("--doc-id", help="Document UUID from the documents table.")
    doc_group.add_argument(
        "--latest",
        action="store_true",
        help="Use the most recently uploaded document in the DB.",
    )
    parser.add_argument(
        "--section-id",
        action="append",
        default=[],
        help="Section id to check. Repeat this flag to check multiple sections.",
    )
    parser.add_argument(
        "--all-sections",
        action="store_true",
        help="Check every section_id found in the document heading_tree.",
    )
    parser.add_argument(
        "--list-tree",
        action="store_true",
        help="Print section ids from the DB heading_tree before checking Pinecone.",
    )
    parser.add_argument(
        "--no-exact",
        action="store_true",
        help="Skip list/fetch scan and use query-filter fallback only.",
    )
    parser.add_argument("--top-k", type=int, default=20, help="Fallback query limit.")
    parser.add_argument("--limit", type=int, default=5, help="Sample chunks per section.")
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Pinecone list/fetch batch size for exact scan.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=0,
        help="Max vectors to scan in exact mode. 0 means no limit.",
    )
    parser.add_argument("--show-content", action="store_true", help="Print content previews.")
    parser.add_argument("--content-chars", type=int, default=240, help="Preview length.")
    return parser


async def _amain() -> int:
    args = _build_parser().parse_args()

    if args.doc_id:
        try:
            uuid.UUID(args.doc_id)
        except ValueError:
            print(f"[ERROR] Invalid document UUID: {args.doc_id}")
            return 2

    from app.core.config import get_settings
    from app.rag.vector_store import _doc_namespace
    from pinecone import Pinecone

    settings = get_settings()
    document = await _load_document(args.doc_id, args.latest)
    if not document:
        print("[ERROR] Document not found.")
        return 1

    doc_id = str(document["id"])
    heading_tree = document.get("heading_tree") if isinstance(document.get("heading_tree"), dict) else {}
    sections = _collect_sections(heading_tree)

    target_ids = list(dict.fromkeys(args.section_id))
    if args.all_sections or not target_ids:
        target_ids = list(sections.keys())

    namespace = _doc_namespace(doc_id)
    print("Document:")
    print(f"  id: {doc_id}")
    print(f"  file: {document.get('original_filename')}")
    print(f"  status: {document.get('processing_status')}")
    print(f"  DB total_chunks: {document.get('total_chunks')}")
    print(f"  DB total_chapters: {document.get('total_chapters')}")
    print(f"  namespace: {namespace}")

    if args.list_tree or not args.section_id:
        _print_tree(sections)

    if not target_ids:
        print("\n[ERROR] No section_id to check. DB heading_tree has no sections.")
        return 1

    if not settings.PINECONE_API_KEY:
        print("\n[ERROR] PINECONE_API_KEY is empty in backend/.env.")
        return 1

    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index = pc.Index(settings.PINECONE_INDEX)

    ns_count = _namespace_count(index, namespace)
    print(f"\nPinecone index: {settings.PINECONE_INDEX}")
    print(f"Namespace vector_count: {ns_count if ns_count is not None else 'unknown'}")

    if not args.no_exact:
        try:
            result = _scan_exact(
                index=index,
                namespace=namespace,
                target_ids=set(args.section_id),
                sample_limit=max(args.limit, 0),
                content_chars=max(args.content_chars, 0),
                page_size=max(args.page_size, 1),
                scan_limit=max(args.scan_limit, 0),
            )
            if result["scanned"] == 0 and ns_count and ns_count > 0:
                print(
                    "\n[WARN] Exact scan listed 0 vector IDs, but the namespace has "
                    f"{ns_count} vectors. Falling back to metadata-filter query."
                )
                _print_query_fallback_report(
                    index=index,
                    namespace=namespace,
                    target_ids=target_ids,
                    sections=sections,
                    top_k=max(args.top_k, 1),
                    embedding_dim=max(int(settings.ST_EMBEDDING_DIM), 1),
                    content_chars=max(args.content_chars, 0),
                    show_content=args.show_content,
                )
                return 0
            _print_exact_report(
                result=result,
                target_ids=args.section_id,
                sections=sections,
                show_content=args.show_content,
            )
            return 0
        except Exception as exc:
            print(f"\n[WARN] Exact scan failed: {exc}")

    _print_query_fallback_report(
        index=index,
        namespace=namespace,
        target_ids=target_ids,
        sections=sections,
        top_k=max(args.top_k, 1),
        embedding_dim=max(int(settings.ST_EMBEDDING_DIM), 1),
        content_chars=max(args.content_chars, 0),
        show_content=args.show_content,
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
