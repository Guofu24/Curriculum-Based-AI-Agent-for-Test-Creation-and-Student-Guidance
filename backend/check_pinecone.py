"""Check actual vectors via list + fetch."""
import asyncio
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.core.config import get_settings
settings = get_settings()

async def check():
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index = pc.Index(settings.PINECONE_INDEX)

    ns = "doc_b07288bcbd6d4da38c9d679f62873d3b"
    
    ids = []
    for id_list in index.list(namespace=ns, limit=10):
        ids.extend(id_list)
        if len(ids) >= 10:
            break
    
    print(f"Found {len(ids)} vector IDs")
    
    if ids:
        fetched = index.fetch(ids=ids[:3], namespace=ns)
        print(f"\nFetched metadata:")
        for vid, vec_data in fetched.vectors.items():
            meta = vec_data.metadata
            print(f"  id: {vid}")
            print(f"  chapter_id: {getattr(meta, 'get', lambda k,d: meta.__dict__.get(k, d) if hasattr(meta, '__dict__') else dict(meta).get(k,d))('chapter_id', 'MISSING')}")
            # Just print all metadata keys
            meta_dict = dict(meta) if not isinstance(meta, dict) else meta
            print(f"  ALL metadata keys: {list(meta_dict.keys())}")
            print(f"  chapter_id value: {meta_dict.get('chapter_id', 'MISSING')}")
            print(f"  chapter value: {meta_dict.get('chapter', 'MISSING')}")
            print()

asyncio.run(check())
