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
import uuid
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")


async def reembed_document(doc_id: uuid.UUID, dry_run: bool = False) -> bool:
    """Re-index one document. Returns True on success."""
    from app.core.database import async_session_maker
    from app.rag.vector_store import VectorStore
    from app.rag.parser import parse_document
    from app.rag.cleaner import clean_markdown
    from app.rag.structure import detect_heading_tree_llm
    from app.rag.chunker import semantic_chunk
    from app.rag.embedder import embed_chunks
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

        # Prefer the heading_tree already stored in Postgres — it was produced by the
        # full detect_heading_tree_gemini_pdf + LLM pipeline during upload and is
        # already canonical (ch1/ch2/ch3).  Only re-detect when the stored tree is
        # missing or empty, to avoid overwriting a clean tree with a potentially
        # different LLM run.
        stored_tree = doc.heading_tree if isinstance(doc.heading_tree, dict) else {}
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

        if dry_run:
            print("\n[DRY RUN] Skipping embed + upsert.")

            # chapter_confidence distribution
            from collections import Counter
            ch_conf = Counter(c.get("chapter_confidence", "unknown") for c in chunks)
            print(f"\n  chapter_confidence distribution: {dict(ch_conf)}")

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
            by_ch.setdefault(c.get("chapter_id", "ch_unknown"), []).append(c)

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
    args = parser.parse_args()

    if args.doc_id:
        try:
            doc_uuid = uuid.UUID(args.doc_id)
        except ValueError:
            print(f"[ERROR] Invalid UUID: {args.doc_id}")
            sys.exit(1)
        success = await reembed_document(doc_uuid, dry_run=args.dry_run)
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
            success = await reembed_document(doc_id, dry_run=args.dry_run)
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
