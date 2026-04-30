"""Migration: delete all old per-chapter namespaces from Pinecone to free quota.

Run this ONCE before reprocessing documents with single namespace.
"""
import asyncio
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.core.config import get_settings

settings = get_settings()


async def cleanup():
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index = pc.Index(settings.PINECONE_INDEX)

    stats = index.describe_index_stats()
    namespaces = stats.get("namespaces", {})

    print(f"Total namespaces: {len(namespaces)}")
    print(f"Total vectors: {stats.get('total_vector_count', 0)}")
    print()

    for ns, info in sorted(namespaces.items()):
        count = info.get("vector_count", 0)
        print(f"  {ns}: {count} vectors")

    print()
    confirm = input(f"Delete ALL {len(namespaces)} namespaces? (type YES to confirm): ")
    if confirm != "YES":
        print("Aborted.")
        return

    for ns in namespaces:
        try:
            index.delete(delete_all=True, namespace=ns)
            print(f"  Deleted: {ns}")
        except Exception as e:
            print(f"  FAILED: {ns} — {e}")

    print(f"\nDone! Deleted {len(namespaces)} namespaces.")
    print("Now reprocess your documents to use single namespace.")

asyncio.run(cleanup())
