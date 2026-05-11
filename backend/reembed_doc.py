"""Re-index any document from DB into Pinecone with canonical section_id metadata.

Usage:
    # Re-index một document cụ thể bằng document_id:
    python reembed_doc.py --doc-id <uuid>

    # Re-index TẤT CẢ documents trong DB:
    python reembed_doc.py --all

    # Dry-run: chỉ in thông tin, không upsert:
    python reembed_doc.py --doc-id <uuid> --dry-run
"""
import asyncio
import argparse
import hashlib
import json
import uuid
import sys
import os
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

PARSER_VERSION = "v2.2"
CLEANER_VERSION = "v1.4"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_tree_hash(tree: dict) -> str:
    return hashlib.sha256(
        json.dumps(tree or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _markdown_cache_key(doc_id: str, file_hash: str, tree_hash: str) -> str:
    raw = f"{doc_id}:{file_hash}:{PARSER_VERSION}:{CLEANER_VERSION}:{tree_hash}"
    return f"markdown_cache:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _markdown_cache_file(cache_key: str) -> Path:
    cache_dir = Path(__file__).resolve().parent / ".cache" / "markdown"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{cache_key.split(':', 1)[-1]}.txt"


async def _load_markdown_cache(cache_key: str, redis) -> str | None:
    try:
        cached = await redis.get(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    path = _markdown_cache_file(cache_key)
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


async def _save_markdown_cache(cache_key: str, markdown: str, redis) -> None:
    try:
        await redis.set(cache_key, markdown, ttl=7 * 24 * 60 * 60)
    except Exception:
        pass
    try:
        _markdown_cache_file(cache_key).write_text(markdown, encoding="utf-8")
    except Exception:
        pass


async def reembed_document(
    doc_id: uuid.UUID,
    dry_run: bool = False,
    skip_alignment: bool = False,
) -> bool:
    """Re-index one document. Returns True on success."""
    from app.core.database import async_session_maker
    from app.rag.vector_store import VectorStore
    from app.rag.parser import parse_document
    from app.rag.cleaner import clean_markdown
    from app.rag.structure import detect_heading_tree_llm
    from app.rag.chunker import semantic_chunk
    from app.rag.embedder import embed_chunks
    from app.rag.exercise_grouper import build_exercise_groups
    from app.rag.alignment import align_exercise_groups
    from app.rag.gemini_key_pool import GeminiKeyPool
    from app.core.config import get_settings
    from app.utils.storage import get_storage
    from app.core.redis_client import get_redis_client
    from sqlalchemy import select, update
    from app.models.document import Document

    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            print(f"[ERROR] Document {doc_id} not found in DB!")
            return False

        print(f"\n{'='*60}")
        print(f"Document: {doc.original_filename}")
        print(f"ID: {doc.id}  |  status={doc.processing_status}")
        print(f"{'='*60}")

        print("Downloading from storage...")
        try:
            file_bytes = await get_storage().download_file(doc.s3_key)
        except Exception as e:
            print(f"[ERROR] Download failed: {e}")
            return False
        print(f"Downloaded: {len(file_bytes):,} bytes")

        stored_tree = doc.heading_tree if isinstance(doc.heading_tree, dict) else {}
        redis = get_redis_client()
        file_hash = _sha256_bytes(file_bytes)
        initial_tree_hash = _stable_tree_hash(stored_tree)
        md_cache_key = _markdown_cache_key(str(doc.id), file_hash, initial_tree_hash)
        md = await _load_markdown_cache(md_cache_key, redis)

        if md:
            print(f"Using cached markdown: {len(md):,} chars")
        else:
            print("Parsing...")
            try:
                parse_result = await parse_document(file_bytes, doc.file_type)
                md = parse_result["content"]
            except Exception as e:
                print(f"[ERROR] Parse failed: {e}")
                return False
            print(f"Parsed: {len(md):,} chars")

            # Clean the raw markdown (strip boilerplate noise, normalise whitespace)
            try:
                clean_result = clean_markdown(md)
                md = clean_result.cleaned
                print(f"Cleaned: {len(md):,} chars")
            except Exception as e:
                print(f"[WARN] clean_markdown failed ({e}) — using raw parse output")

            await _save_markdown_cache(md_cache_key, md, redis)
            print("Saved markdown cache.")

        # Prefer the heading_tree already stored in Postgres — it was produced by the
        # full detect_heading_tree_gemini_pdf + LLM pipeline during upload and is
        # already canonical (ch1/ch2/ch3).  Only re-detect when the stored tree is
        # missing or empty, to avoid overwriting a clean tree with a potentially
        # different LLM run.
        if stored_tree.get("chapters"):
            print(f"Using heading_tree from DB ({len(stored_tree['chapters'])} chapters).")
            tree = stored_tree
        else:
            print("heading_tree missing in DB — re-detecting via LLM...")
            try:
                tree = await detect_heading_tree_llm(md)
            except Exception as e:
                print(f"[WARN] LLM heading detection failed ({e}), proceeding with empty tree")
                tree = {"chapters": []}

        chapters = tree.get("chapters", [])
        print(f"Chapters ({len(chapters)}):")
        for c in chapters:
            secs = c.get("sections", [])
            print(f"  {c['chapter_id']}: {c['title'][:60]}")
            for s in secs:
                print(f"    {s['section_id']}: {s['title'][:50]}")

        print("\nChunking (with canonical section_id from heading_tree)...")
        try:
            chunks = semantic_chunk(md, tree)
        except Exception as e:
            print(f"[ERROR] Chunking failed: {e}")
            return False
        print(f"Chunks: {len(chunks)}")

        # Verify section_id assignment
        with_sec_id = sum(1 for c in chunks if c.get("section_id"))
        print(f"  Chunks with section_id: {with_sec_id}/{len(chunks)}")

        if skip_alignment:
            print("LLM exercise alignment: skipped by --skip-alignment")
        else:
            unknown_chunks = [c for c in chunks if c.get("section_confidence", "unknown") == "unknown"]
            groups = build_exercise_groups(unknown_chunks, str(doc_id))
            print(f"\nExercise groups detected: {len(groups)}")
            try:
                settings = get_settings()
                alignment_keys = settings.GEMINI_ALIGNMENT_KEYS
                pool = GeminiKeyPool(redis, keys=alignment_keys) if alignment_keys else GeminiKeyPool(redis)
                chunks, align_report = await align_exercise_groups(
                    chunks=chunks,
                    groups=groups,
                    heading_tree=tree,
                    pool=pool,
                    fallback_pool=GeminiKeyPool(redis) if alignment_keys else None,
                    redis=redis,
                )
                print(
                    "  LLM aligned: "
                    f"{align_report.llm_aligned} groups | "
                    f"unknown: {align_report.unknown} | "
                    f"cache_hits: {align_report.cache_hits} | "
                    f"batches_called: {align_report.batches_called} | "
                    f"invalid_ids: {align_report.invalid_ids} | "
                    f"skipped_no_key: {align_report.skipped_no_key}"
                )
                if align_report.errors:
                    print("  alignment warnings:")
                    for err in align_report.errors[:5]:
                        print(f"    - {err}")
                if align_report.samples:
                    print("  sample alignments:")
                    for sample in align_report.samples[:10]:
                        print(
                            "    "
                            f"{sample['group_id'][:70]} -> "
                            f"{sample['chapter_id']} / {sample['section_id']} "
                            f"({sample['reason']})"
                        )
            except Exception as e:
                print(f"[WARN] LLM exercise alignment failed ({e}) — keeping unknown metadata")

        with_sec_id_after = sum(1 for c in chunks if c.get("section_id"))
        print(f"  Chunks with section_id after alignment: {with_sec_id_after}/{len(chunks)}")

        if dry_run:
            print("\n[DRY RUN] Skipping embed + upsert.")

            # chapter_confidence distribution
            from collections import Counter
            ch_conf = Counter(c.get("chapter_confidence", "unknown") for c in chunks)
            sec_conf = Counter(c.get("section_confidence", "unknown") for c in chunks)
            print(f"\n  chapter_confidence distribution: {dict(ch_conf)}")
            print(f"  section_confidence distribution: {dict(sec_conf)}")

            # per-chapter breakdown
            ch_breakdown: dict = {}
            for c in chunks:
                ch_id = c.get("chapter_id", "(none)")
                cc = c.get("chapter_confidence", "unknown")
                bd = ch_breakdown.setdefault(ch_id, Counter())
                bd[cc] += 1
            print("  per-chapter breakdown:")
            for ch_id, bd in sorted(ch_breakdown.items()):
                print(f"    {ch_id:20s}  " + "  ".join(f"{k}={v}" for k, v in sorted(bd.items())))

            # sample inferred chunks
            inferred = [c for c in chunks if c.get("chapter_confidence") == "inferred"]
            if inferred:
                print(f"\n  Sample inferred chunks ({len(inferred)} total):")
                for c in inferred[:5]:
                    print(f"    chunk={c['chunk_id']:30s} | candidate={c.get('candidate_chapter_ids')} "
                          f"| content_start={c.get('content','')[:50]!r}")

            # sample of first 5 chunks
            print("\n  First 5 chunks:")
            for c in chunks[:5]:
                print(f"    chunk={c['chunk_id']} | chapter_id={c['chapter_id']} | "
                      f"ch_conf={c.get('chapter_confidence','?')} | "
                      f"section_id={c.get('section_id','(empty)')}")
            return True

        print("\nEmbedding (this may take a while)...")
        redis = get_redis_client()
        try:
            chunks = await embed_chunks(chunks, str(doc_id), redis)
        except Exception as e:
            print(f"[ERROR] Embedding failed: {e}")
            return False
        print(f"Embedded: {len(chunks)} chunks")

        print("Upserting to Pinecone...")
        vs = VectorStore()

        # Delete ALL old vectors for this document first, so no stale metadata
        # from previous runs survives in Pinecone.
        print("  Deleting old vectors...")
        try:
            await vs.delete_all_document_vectors(str(doc_id))
        except Exception as e:
            print(f"  [WARN] Delete old vectors failed: {e} — continuing anyway")

        by_ch: dict = {}
        for c in chunks:
            by_ch.setdefault(c.get("chapter_id") or "ch_unknown", []).append(c)

        for ch in chapters:
            ch_id = ch["chapter_id"]
            ch_chunks = by_ch.get(ch_id, [])
            if ch_chunks:
                await vs.upsert_chunks(str(doc_id), ch_id, ch_chunks)
                print(f"  {ch_id}: {len(ch_chunks)} chunks upserted")
            else:
                print(f"  {ch_id}: no chunks")

        # Handle chunks without a valid chapter (ch_unknown)
        unknown_chunks = by_ch.get("ch_unknown", [])
        if unknown_chunks:
            await vs.upsert_chunks(str(doc_id), "ch_unknown", unknown_chunks)
            print(f"  ch_unknown: {len(unknown_chunks)} chunks upserted")

        # Update DB: total_chunks + heading_tree (canonical)
        await db.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(total_chunks=len(chunks), heading_tree=tree)
        )
        await db.commit()
        print(f"\nDONE — {len(chunks)} chunks re-indexed into Pinecone.")
        return True


async def main():
    parser = argparse.ArgumentParser(description="Re-index documents into Pinecone")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc-id", type=str, help="UUID of document to re-index")
    group.add_argument("--all", action="store_true", help="Re-index ALL documents in DB")
    parser.add_argument("--dry-run", action="store_true", help="Print info without upserting")
    parser.add_argument("--skip-alignment", action="store_true", help="Skip LLM exercise alignment")
    args = parser.parse_args()

    if args.doc_id:
        try:
            doc_uuid = uuid.UUID(args.doc_id)
        except ValueError:
            print(f"[ERROR] Invalid UUID: {args.doc_id}")
            sys.exit(1)
        success = await reembed_document(
            doc_uuid,
            dry_run=args.dry_run,
            skip_alignment=args.skip_alignment,
        )
        sys.exit(0 if success else 1)

    elif args.all:
        from app.core.database import async_session_maker
        from sqlalchemy import select
        from app.models.document import Document
        async with async_session_maker() as db:
            result = await db.execute(select(Document.id, Document.original_filename))
            docs = result.all()

        print(f"Found {len(docs)} documents to re-index.")
        failed = []
        for doc_id, filename in docs:
            print(f"\nProcessing: {filename} ({doc_id})")
            success = await reembed_document(
                doc_id,
                dry_run=args.dry_run,
                skip_alignment=args.skip_alignment,
            )
            if not success:
                failed.append((doc_id, filename))

        print(f"\n{'='*60}")
        print(f"Re-index complete: {len(docs) - len(failed)}/{len(docs)} succeeded.")
        if failed:
            print("Failed:")
            for doc_id, fn in failed:
                print(f"  {doc_id}: {fn}")
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
