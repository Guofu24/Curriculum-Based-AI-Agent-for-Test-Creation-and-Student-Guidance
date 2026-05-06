"""Admin routes for user management and knowledge upload."""

import hashlib
import json
import logging
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.models.user import User
from app.models.textbook import TextbookKnowledge
from app.dependencies import get_current_admin, get_pagination_params
from app.schemas.auth import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


def _simple_chunk(text: str, max_chars: int = 1000) -> list[str]:
    """Split markdown text into chunks at paragraph boundaries."""
    paragraphs = re.split(r'\n{2,}', text)
    chunks: list[str] = []
    current = ''
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if current and len(current) + len(p) + 2 > max_chars:
            chunks.append(current)
            current = p
        else:
            current = (current + '\n\n' + p).strip() if current else p
    if current:
        chunks.append(current)
    return chunks


@router.get("/users", response_model=dict)
async def list_users(
    admin: User = Depends(get_current_admin),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
):
    """List all users (Admin only)."""
    offset, limit = pagination

    count_query = select(func.count(User.id))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "items": [UserResponse.model_validate(user) for user in users],
        "total": total,
        "page": (offset // limit) + 1,
        "size": limit,
    }


@router.get("/knowledge/namespaces")
async def list_namespaces(
    db: AsyncSession = Depends(get_db),
):
    """List all available knowledge namespaces (public — no admin required)."""
    from sqlalchemy import distinct
    result = await db.execute(
        select(distinct(TextbookKnowledge.namespace)).order_by(TextbookKnowledge.namespace)
    )
    namespaces = result.scalars().all()
    return {"namespaces": namespaces}


@router.get("/knowledge/chapters")
async def list_chapters(
    namespace: str,
    db: AsyncSession = Depends(get_db),
):
    """List distinct chapters for a given namespace (public — no admin required)."""
    from sqlalchemy import distinct
    result = await db.execute(
        select(distinct(TextbookKnowledge.chapter))
        .where(TextbookKnowledge.namespace == namespace)
        .order_by(TextbookKnowledge.chapter)
    )
    chapters = result.scalars().all()
    return {"namespace": namespace, "chapters": chapters}


@router.get("/knowledge/outline")
async def get_knowledge_outline(
    namespace: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return full outline: [{chapter, sections: [title, ...]}] for a namespace.
    Public — no admin auth required so the generation page can use it.
    """
    result = await db.execute(
        select(TextbookKnowledge.chapter, TextbookKnowledge.title)
        .where(TextbookKnowledge.namespace == namespace)
        .order_by(TextbookKnowledge.chapter, TextbookKnowledge.title)
    )
    rows = result.all()

    # Group by chapter preserving order
    outline: list[dict] = []
    chapter_index: dict[str, int] = {}
    for chapter, title in rows:
        if chapter not in chapter_index:
            chapter_index[chapter] = len(outline)
            outline.append({"chapter": chapter, "sections": []})
        outline[chapter_index[chapter]]["sections"].append(title)

    return {"namespace": namespace, "outline": outline}


@router.post("/knowledge/textbook")
async def upload_textbook_knowledge(
    namespace: str = Form(..., description="Namespace to store vectors (e.g. textbook_ly12)"),
    file: UploadFile = File(..., description="JSON file containing textbook data"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """
    Upload parsed textbook JSON and embed into Pinecone.
    Format expected: list of dicts with keys: chapter, title, url, content
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported.")

    try:
        content_bytes = await file.read()
        data = json.loads(content_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="JSON root must be a list.")

    # Validate structure
    for item in data:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="JSON list items must be objects.")
        for key in ["chapter", "title", "content"]:
            if key not in item:
                raise HTTPException(status_code=400, detail=f"Missing required key '{key}' in one of the items.")

    # 1. Store in PostgreSQL
    logger.info(f"Admin {admin.email} uploading {len(data)} items to namespace '{namespace}'")

    # Bug 2 fix: delete existing rows for this namespace before re-inserting
    await db.execute(delete(TextbookKnowledge).where(TextbookKnowledge.namespace == namespace))
    await db.flush()

    for item in data:
        db.add(TextbookKnowledge(
            namespace=namespace,
            chapter=item["chapter"],
            title=item["title"],
            url=item.get("url"),
            content=item["content"]
        ))

    await db.commit()
    
    # 2. Process and Embed into Pinecone (async background task ideally, but we'll do it synchronously or pass to a service)
    # We will invoke the RAG pipeline here.
    from app.rag.embedder import EmbeddingService
    from app.rag.vector_store import get_vector_store

    vs = get_vector_store()
    embedder = EmbeddingService(redis)

    all_chunks = []
    for item in data:
        chapter = item["chapter"]
        title = item["title"]
        content = item["content"]
        for idx, c in enumerate(_simple_chunk(content)):
            raw_id = f"{namespace}_{chapter}_{title}_{idx}"
            chunk_dict = {
                "chunk_id": hashlib.md5(raw_id.encode()).hexdigest(),
                "chapter": chapter,
                "chapter_id": chapter,
                "section": title,
                "section_id": title,
                "content": c,
                "content_type": "text",
            }
            all_chunks.append(chunk_dict)

    if not all_chunks:
        return {"message": "No chunks generated", "items_saved": len(data)}

    batch_size = 100
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        embeddings = await embedder.embed_texts([c["content"] for c in batch])
        for chunk, emb in zip(batch, embeddings):
            chunk["embedding"] = emb

    # Upsert to Pinecone
    # Note: the standard upsert_chunks in vector_store forces namespace = doc_{doc_id}.
    # We need to bypass it or add a custom method for textbook namespaces.
    # We'll use the client directly here for simplicity, or modify vector_store.
    
    pc_index = await vs._get_index()
    
    import numpy as np
    records = []
    for c in all_chunks:
        emb = c.get("embedding")
        if emb is None: continue
        emb_list = np.nan_to_num(emb, nan=0.0, posinf=1.0, neginf=-1.0).tolist()
        
        records.append({
            "id": c["chunk_id"],
            "values": emb_list,
            "metadata": {
                "document_id": namespace, # Treat namespace as document_id for metadata
                "chunk_id": c["chunk_id"],
                "chapter": c["chapter"],
                "chapter_id": c["chapter_id"],
                "section": c["section"],
                "section_id": c["section_id"],
                "content": c["content"][:2000],
                "content_type": "text"
            }
        })
    
    # Upsert to Pinecone in batches
    def _upsert_batch(batch_records, ns):
        for attempt in range(3):
            try:
                pc_index.upsert(vectors=batch_records, namespace=ns)
                return
            except Exception as e:
                if attempt == 2: raise
                logger.warning(f"Upsert retry {attempt+1} for {ns}")
                
    import asyncio
    loop = asyncio.get_running_loop()
    for i in range(0, len(records), 100):
        b = records[i:i+100]
        await loop.run_in_executor(None, _upsert_batch, b, namespace)
        
    return {
        "message": "Knowledge uploaded and embedded successfully",
        "items_saved": len(data),
        "chunks_embedded": len(records),
        "namespace": namespace
    }
