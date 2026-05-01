"""Patch process_document to save parse results before embed step."""
import re

path = "app/services/document_service.py"
content = open(path, "r", encoding="utf-8").read()

# Find the method start and end
start = content.find("    async def process_document(self, document_id: UUID)")
end = content.find("\n    def get_presigned_url", start)

if start == -1:
    print("ERROR: method not found")
    exit(1)

new_method = '''    async def process_document(self, document_id: UUID) -> dict:
        """Run the full RAG pipeline: parse -> chunk -> (embed+Pinecone optional)."""
        import logging
        _log = logging.getLogger("document.process")
        try:
            await self.update_status(document_id, "processing")
            result = await self.db.execute(select(Document).where(Document.id == document_id))
            document = result.scalar_one_or_none()
            if not document:
                raise DocumentServiceError("Document not found")

            from app.utils.storage import get_storage
            file_bytes = await get_storage().download_file(document.s3_key)

            parse_result = await parse_document(file_bytes, document.file_type)
            markdown_content = parse_result["content"]
            total_pages = parse_result.get("page_count", 0)
            _log.info("Parsed %s: %d pages, %d chars", document_id, total_pages, len(markdown_content))

            heading_tree = detect_heading_tree(markdown_content)
            total_chapters = len(heading_tree.get("chapters", []))
            chunks = semantic_chunk(markdown_content, heading_tree)
            doc_id_str = str(document_id)
            for chunk in chunks:
                chunk["document_id"] = doc_id_str
            _log.info("Chunked %s: %d chunks, %d chapters", document_id, len(chunks), total_chapters)

            # Save parse results immediately — visible even if embed step fails
            await self.update_processing_result(
                document_id=document_id,
                heading_tree=heading_tree,
                total_chapters=total_chapters,
                total_pages_or_slides=total_pages,
                total_chunks=len(chunks),
            )
            await self.update_status(document_id, "processed")

            # Embed + Pinecone — graceful degradation if OpenAI key invalid
            try:
                from app.core.redis_client import get_redis_client
                redis = get_redis_client()
                enriched = await embed_chunks(chunks, doc_id_str, redis)
                chapter_groups: dict[str, list[dict]] = {}
                for chunk in enriched:
                    chapter_groups.setdefault(chunk.get("chapter_id", "unknown"), []).append(chunk)
                for chapter_id, chapter_chunks in chapter_groups.items():
                    await self.vector_store.upsert_chunks(
                        document_id=doc_id_str, chapter_id=chapter_id, chunks=chapter_chunks,
                    )
                await self.update_status(document_id, "indexed")
                _log.info("Indexed %s: %d vectors", document_id, len(enriched))
                return {"document_id": doc_id_str, "chunks_created": len(enriched),
                        "total_pages": total_pages, "processing_status": "indexed"}
            except Exception as embed_err:
                _log.warning("Embed skipped for %s (parse OK): %s", document_id, embed_err)
                return {"document_id": doc_id_str, "chunks_created": len(chunks),
                        "total_pages": total_pages, "processing_status": "processed",
                        "embed_error": str(embed_err)}

        except Exception as e:
            _log.exception("process_document failed %s: %s", document_id, e)
            await self.update_status(document_id, "failed", error_message=str(e))
            return {"document_id": str(document_id), "processing_status": "failed", "error": str(e)}
'''

new_content = content[:start] + new_method + content[end:]
open(path, "w", encoding="utf-8").write(new_content)
print(f"SUCCESS: replaced method (start={start}, end={end})")
print(f"New file size: {len(new_content)} bytes")
