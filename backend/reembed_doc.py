"""Re-embed PTNK-Vat-ly-hien-dai.pdf into Pinecone."""
import asyncio
import uuid
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

DOC_ID = uuid.UUID("cd39e8af-e4f9-4caf-b3b5-3c150be65895")


async def main():
    from app.core.database import async_session_maker
    from app.services.document_service import DocumentService
    from app.rag.vector_store import VectorStore
    from app.rag.parser import parse_document
    from app.rag.structure import detect_heading_tree
    from app.rag.chunker import semantic_chunk
    from app.rag.embedder import embed_chunks
    from app.utils.storage import get_storage
    from app.core.redis_client import get_redis_client

    async with async_session_maker() as db:
        # Direct DB query bypassing user_id check
        from sqlalchemy import select
        from app.models.document import Document
        result = await db.execute(select(Document).where(Document.id == DOC_ID))
        doc = result.scalar_one_or_none()
        if not doc:
            print("Document not found!")
            return

        print(f"Found: {doc.original_filename}, status={doc.processing_status}")
        print("Downloading from S3...")
        file_bytes = await get_storage().download_file(doc.s3_key)
        print(f"Downloaded: {len(file_bytes):,} bytes")

        print("Parsing...")
        parse_result = await parse_document(file_bytes, doc.file_type)
        md = parse_result["content"]
        print(f"Parsed: {len(md):,} chars")

        print("Detecting structure...")
        tree = detect_heading_tree(md)
        chapters = tree.get("chapters", [])
        print(f"Chapters ({len(chapters)}):")
        for c in chapters:
            print(f"  {c['chapter_id']}: {c['title'][:60]}")

        print("Chunking...")
        chunks = semantic_chunk(md, tree)
        print(f"Chunks: {len(chunks)}")

        print("Embedding (this may take a while)...")
        redis = get_redis_client()
        chunks = await embed_chunks(chunks, str(DOC_ID), redis)
        print(f"Embedded: {len(chunks)} chunks")

        print("Upserting to Pinecone...")
        vs = VectorStore()
        by_ch: dict = {}
        for c in chunks:
            by_ch.setdefault(c.get("chapter_id", "ch_unknown"), []).append(c)

        for ch in chapters:
            ch_id = ch["chapter_id"]
            ch_chunks = by_ch.get(ch_id, [])
            if ch_chunks:
                await vs.upsert_chunks(str(DOC_ID), ch_id, ch_chunks)
                print(f"  {ch_id}: {len(ch_chunks)} chunks upserted")
            else:
                print(f"  {ch_id}: no chunks")

        # Update total_chunks in DB
        from sqlalchemy import update
        from app.models.document import Document
        await db.execute(
            update(Document)
            .where(Document.id == DOC_ID)
            .values(total_chunks=len(chunks), heading_tree=tree)
        )
        await db.commit()
        print(f"\nDONE — {len(chunks)} chunks indexed into Pinecone.")


if __name__ == "__main__":
    asyncio.run(main())
