import asyncio, sys, json
sys.path.insert(0, ".")
DOC_ID = "a1bd80c0-f7cc-490a-b727-62855b9c4b7b"

async def main():
    from app.core.database import async_session_maker
    from sqlalchemy import select
    from app.models.document import Document
    from app.utils.storage import get_storage
    from app.rag.parser import parse_document
    from app.rag.chunker import semantic_chunk
    import uuid

    async with async_session_maker() as db:
        row = await db.execute(select(Document).where(Document.id == uuid.UUID(DOC_ID)))
        doc = row.scalar_one()
        print("heading_tree:", json.dumps(doc.heading_tree, ensure_ascii=False, indent=2))

    # Download and parse
    file_bytes = await get_storage().download_file(doc.s3_key)
    from app.rag.parser import parse_document
    result = await parse_document(file_bytes, doc.file_type)
    md = result["content"]
    print(f"\nMarkdown length: {len(md)} chars")

    # Show first 3000 chars of markdown to see heading structure
    print("\n--- FIRST 3000 CHARS OF MARKDOWN ---")
    print(md[:3000])

asyncio.run(main())
