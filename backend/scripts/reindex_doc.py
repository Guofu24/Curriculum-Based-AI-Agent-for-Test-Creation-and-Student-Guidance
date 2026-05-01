"""
Script để re-index document vào Pinecone với chapter_id đúng.
Chạy: python scripts/reindex_doc.py <document_id>
"""
import sys
import os
import asyncio

# Add backend to path so 'app' module can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DOC_ID = sys.argv[1] if len(sys.argv) > 1 else "b45c27c7-18b5-4ac8-a072-c647276a2f09"
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT_URL")
MINIO_ACCESS = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://examai:examai@localhost:5432/examai")


async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

    # 1. Load document from DB
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT id, user_id, s3_key, heading_tree, original_filename FROM documents WHERE id = :doc_id"),
            {"doc_id": DOC_ID}
        )
        row = result.fetchone()
        if not row:
            print(f"Document {DOC_ID} not found!")
            return
        doc_id, user_id, s3_key, heading_tree_raw, filename = row
        print(f"Found document: {filename} (id={doc_id})")

        # heading_tree is JSONB
        import json
        heading_tree = heading_tree_raw if heading_tree_raw else {}
        print(f"Heading tree chapters: {[ch.get('title','') for ch in heading_tree.get('chapters', [])]}")

    await engine.dispose()

    # 2. Download file from MinIO
    from minio import Minio
    minio_client = Minio(
        MINIO_ENDPOINT.replace("http://", ""),
        access_key=MINIO_ACCESS,
        secret_key=MINIO_SECRET,
        secure=False,
    )
    print(f"Downloading s3_key={s3_key} from MinIO...")
    data = minio_client.get_object(MINIO_BUCKET, s3_key)
    file_bytes = data.read()
    data.close()
    print(f"Downloaded {len(file_bytes)} bytes")

    # 3. Parse document
    sys.path.insert(0, os.path.dirname(__file__))
    from app.rag.parser import parse_document
    parse_result = await parse_document(file_bytes, "pdf")
    markdown_content = parse_result["content"]
    print(f"Parsed markdown: {len(markdown_content)} chars")

    # 4. Chunk với heading_tree (dùng semantic_chunk đã fix)
    from app.rag.chunker import semantic_chunk
    chunks = semantic_chunk(markdown_content, heading_tree)
    print(f"Chunked: {len(chunks)} chunks")

    # Print chapter_id distribution
    from collections import Counter
    ch_counts = Counter(ch.get("chapter_id", "???") for ch in chunks)
    for ch_id, cnt in ch_counts.items():
        print(f"  chapter_id={ch_id}: {cnt} chunks")

    # 5. Embed chunks
    from app.core.redis_client import get_redis_client
    from app.rag.embedder import embed_chunks
    redis = get_redis_client()
    chunks = await embed_chunks(chunks, str(doc_id), redis)
    print(f"Embedded {len(chunks)} chunks")

    # 6. Delete old vectors from Pinecone
    from pinecone import Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX)

    # List current namespaces for this doc
    try:
        stats = index.describe()
        namespaces = stats.get("namespaces", {})
        print(f"\nNamespaces currently in Pinecone ({len(namespaces)} total):")
        for ns_name, ns_info in namespaces.items():
            if str(doc_id) in ns_name:
                print(f"  {ns_name}: {ns_info.get('vector_count', 0)} vectors")
    except Exception as e:
        print(f"Could not list namespaces: {e}")

    # 7. Delete old namespaces
    chapters = [ch["chapter_id"] for ch in heading_tree.get("chapters", [])]
    for ch_id in chapters:
        old_ns = f"{doc_id}_{ch_id}"
        try:
            # First try the canonical namespace
            import unicodedata
            ns_ascii = unicodedata.normalize("NFD", old_ns)
            ns_ascii = "".join(c for c in ns_ascii if unicodedata.category(c) != "Mn")
            ns_ascii = "".join(c if ord(c) < 128 else "_" for c in ns_ascii)
            index.delete(delete_all=True, namespace=ns_ascii)
            print(f"  Deleted namespace: {ns_ascii}")
        except Exception as e:
            print(f"  Could not delete {old_ns}: {e}")

    # Also delete the WRONG namespaces that may exist (with bad chapter_ids)
    if True:
        # Try to detect and delete namespaces with bad chapter_ids
        try:
            stats = index.describe()
            namespaces = stats.get("namespaces", {})
            for ns_name in namespaces.keys():
                if str(doc_id) in ns_name:
                    # Check if this namespace is NOT a canonical chapter_id
                    suffix = ns_name.replace(str(doc_id), "").lstrip("_")
                    if suffix not in chapters:
                        print(f"  Deleting wrong namespace: {ns_name}")
                        index.delete(delete_all=True, namespace=ns_name)
        except Exception as e:
            print(f"  Error cleaning wrong namespaces: {e}")

    # 8. Upsert with correct chapter_ids
    from app.rag.vector_store import VectorStore
    vs = VectorStore()
    chapter_chunks: dict = {}
    for chunk in chunks:
        ch_id = chunk.get("chapter_id", "ch_unknown")
        chapter_chunks.setdefault(ch_id, []).append(chunk)

    for ch_id in chapters:
        chunks_for_ch = chapter_chunks.get(ch_id, [])
        if chunks_for_ch:
            await vs.upsert_chunks(str(doc_id), ch_id, chunks_for_ch)
            print(f"  Upserted {len(chunks_for_ch)} chunks → {doc_id}_{ch_id}")
        else:
            print(f"  No chunks for chapter {ch_id}")

    print("\nRe-index complete!")

    # Verify
    stats = index.describe()
    namespaces = stats.get("namespaces", {})
    print(f"\nNamespaces after re-index:")
    for ns_name, ns_info in namespaces.items():
        if str(doc_id) in ns_name:
            print(f"  {ns_name}: {ns_info.get('vector_count', 0)} vectors")


if __name__ == "__main__":
    asyncio.run(main())
