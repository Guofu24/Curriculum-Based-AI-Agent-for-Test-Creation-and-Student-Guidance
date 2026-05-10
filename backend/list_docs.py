import asyncio, sys, json
sys.path.insert(0, ".")

async def main():
    from app.core.database import async_session_maker
    from sqlalchemy import select
    from app.models.document import Document

    async with async_session_maker() as db:
        rows = await db.execute(select(Document.id, Document.original_filename, Document.heading_tree))
        for doc_id, fname, tree in rows:
            if not isinstance(tree, dict):
                print(f"{doc_id} | {fname[:40]} | NO TREE")
                continue
            chs = tree.get("chapters", [])
            has_title = sum(1 for c in chs if c.get("title", "").strip())
            has_empty = sum(1 for c in chs if not c.get("title", "").strip())
            status = "OK" if has_title > 0 and has_empty == 0 else f"BROKEN(titles:{has_title} empty:{has_empty})"
            ch_titles = [c.get("title","")[:30] for c in chs[:3]]
            print(f"{doc_id} | {fname[:40]} | {status} | {ch_titles}")

asyncio.run(main())
