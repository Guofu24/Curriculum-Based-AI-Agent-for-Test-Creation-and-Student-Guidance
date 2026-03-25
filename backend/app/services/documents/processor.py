"""
Document processing pipeline for the active MVP runtime

Uses the `unstructured` library for intelligent document partitioning,
semantic-aware chunking, and hierarchical chapter/section tracking.

Pipeline:
  Step 1: Partition PDF â†’ structured elements (Title, NarrativeText, ListItem, ...)
  Step 2: Clean â†’ remove Header/Footer noise
  Step 3: Chapter & Hierarchy Tracking â†’ inject chapter/section metadata
  Step 4: Smart Chunking â†’ chunk_by_title with semantic boundaries
  Step 5: Output Formatting â†’ clean dicts for storage

Strategy: "fast" (pypdf backend, no Tesseract/Poppler needed).
To enable hi-res OCR + layout detection, change STRATEGY to "hi_res"
and install Tesseract + Poppler.
"""

import os
import re
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document

from app.core.config import settings

logger = logging.getLogger(__name__)

# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# Configuration
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

# Partitioning strategy: "fast" (no system deps) or "hi_res" (needs Tesseract + Poppler)
STRATEGY = "fast"

# Chunking parameters tuned for academic PDF documents
COMBINE_TEXT_UNDER_N_CHARS = 500   # Group short paragraphs together
MAX_CHARACTERS = 1500              # Hard limit per chunk
OVERLAP = 150                      # Character overlap for split continuity

# Chapter detection regex (Vietnamese + English)
CHAPTER_PATTERN = re.compile(
    r"(?i)^(chÆ°Æ¡ng|chapter|pháº§n|part)\s*(\d+)[:\s.\-â€”]*(.*)$"
)

# Image output directory (only used with hi_res strategy)
IMAGE_OUTPUT_DIR = os.path.join(settings.UPLOAD_DIR, "extracted_images")


class DocumentProcessor:
    """
    Processes uploaded PDF documents using the `unstructured` library.

    Pipeline: partition -> clean -> track hierarchy -> chunk -> format output.
    """

    def __init__(self, vector_store, db_session=None):
        self.vector_store = vector_store
        self.db_session = db_session

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Public API for the active document ingestion service
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    async def process_document(self, file_path: str, document_id: str) -> dict:
        """
        Full document processing pipeline.
        Returns metadata about the processed document.
        """
        logger.info(f"[PROCESSOR] Starting document processing: {file_path}")

        # Step 1: Partition the document into structured elements
        elements = self._partition(file_path)
        logger.info(f"[PROCESSOR] Step 1 â€” Partitioned into {len(elements)} elements")

        # Step 2: Clean â€” remove Header/Footer noise
        elements = self._clean(elements)
        logger.info(f"[PROCESSOR] Step 2 â€” After cleaning: {len(elements)} elements")

        # Step 3: Track chapter & section hierarchy
        elements, chapters = self._track_hierarchy(elements)
        logger.info(
            f"[PROCESSOR] Step 3 â€” Detected {len(chapters)} chapters"
        )

        # Step 4: Smart chunking with semantic boundaries
        chunks = self._smart_chunk(elements)
        logger.info(f"[PROCESSOR] Step 4 â€” Produced {len(chunks)} chunks")

        # Step 5: Format output and store
        formatted = self._format_output(chunks, file_path, document_id)
        sections = self._derive_sections(formatted, chapters, document_id)
        chunk_ids = await self._store_chunks(formatted, document_id)
        logger.info(f"[PROCESSOR] Step 5 â€” Stored {len(chunk_ids)} chunks")

        return {
            "document_id": document_id,
            "title": Path(file_path).stem,
            "total_pages": self._count_pages(elements),
            "total_chunks": len(formatted),
            "chapters": chapters,
            "sections": sections,
            "chunk_ids": chunk_ids,
        }

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Step 1: Advanced Partitioning
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _partition(self, file_path: str) -> list:
        """
        Partition the document into structured elements using `unstructured`.

        MVP currently only supports PDF documents.
        """
        ext = Path(file_path).suffix.lower()
        if ext != ".pdf":
            raise ValueError(f"Unsupported file type: {ext}")

        from unstructured.partition.pdf import partition_pdf

        kwargs = {
            "filename": file_path,
            "strategy": STRATEGY,
            "include_page_breaks": True,
        }

        if STRATEGY == "hi_res":
            os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)
            kwargs.update({
                "infer_table_structure": True,
                "extract_image_block_types": ["Image", "Table"],
                "extract_image_block_output_dir": IMAGE_OUTPUT_DIR,
            })

        return partition_pdf(**kwargs)

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Step 2: Cleaning (Noise Reduction)
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _clean(self, elements: list) -> list:
        """
        Remove Header/Footer elements â€” these are usually repeating
        page numbers or document titles that break semantic flow.
        Also remove PageBreak elements.
        """
        from unstructured.documents.elements import Header, Footer, PageBreak

        noise_types = (Header, Footer, PageBreak)
        cleaned = [el for el in elements if not isinstance(el, noise_types)]
        return cleaned

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Step 3: Chapter & Hierarchy Tracking (CRITICAL)
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _track_hierarchy(self, elements: list) -> tuple[list, list[dict]]:
        """
        Iterate through elements to:
        1. Detect chapters via regex (Vietnamese + English patterns).
        2. Track current section heading for parent context.
        3. Inject `chapter` and `parent_heading` into element metadata.

        Returns: (enriched_elements, detected_chapters)
        """
        from unstructured.documents.elements import Title

        current_chapter: Optional[str] = None
        current_chapter_num: Optional[int] = None
        current_heading: Optional[str] = None
        chapters: list[dict] = []
        seen_chapter_nums: set[int] = set()

        for element in elements:
            text = str(element).strip()

            # Check if this element is a chapter heading
            if isinstance(element, Title):
                chapter_match = CHAPTER_PATTERN.match(text)
                if chapter_match:
                    chapter_num = int(chapter_match.group(2))
                    chapter_title = chapter_match.group(3).strip() or f"Chapter {chapter_num}"
                    current_chapter = f"{chapter_match.group(1)} {chapter_num}: {chapter_title}"
                    current_chapter_num = chapter_num

                    if chapter_num not in seen_chapter_nums:
                        seen_chapter_nums.add(chapter_num)
                        page = element.metadata.page_number if hasattr(element.metadata, 'page_number') else None
                        chapters.append({
                            "chapter_number": chapter_num,
                            "title": chapter_title,
                            "start_page": page,
                        })
                else:
                    # Not a chapter title, but still a section heading
                    current_heading = text

            # Inject hierarchy metadata into the element
            if hasattr(element, 'metadata'):
                element.metadata.chapter = current_chapter
                element.metadata.chapter_number = current_chapter_num
                element.metadata.parent_heading = current_heading

        # Sort chapters and compute end_page
        chapters.sort(key=lambda c: c["chapter_number"])
        for i, ch in enumerate(chapters):
            if i + 1 < len(chapters):
                end_start = chapters[i + 1].get("start_page")
                ch["end_page"] = (end_start - 1) if end_start else None
            else:
                ch["end_page"] = None

        return elements, chapters

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Step 4: Smart Chunking
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _smart_chunk(self, elements: list) -> list:
        """
        Apply `chunk_by_title` â€” groups elements under their closest Title,
        respects semantic boundaries, and avoids cutting mid-sentence.

        Parameters:
        - combine_text_under_n_chars: group short paragraphs (< 500 chars)
        - max_characters: hard limit per chunk (1500 chars)
        - overlap: overlap chars when a block must be split (150 chars)
        """
        from unstructured.chunking.title import chunk_by_title

        chunks = chunk_by_title(
            elements,
            combine_text_under_n_chars=COMBINE_TEXT_UNDER_N_CHARS,
            max_characters=MAX_CHARACTERS,
            overlap=OVERLAP,
        )
        return chunks

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Step 5: Output Formatting
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _format_output(
        self, chunks: list, source_file: str, document_id: str
    ) -> list[dict]:
        """
        Convert unstructured chunks to clean dictionaries.
        Drops coordinate/bounding_box metadata to save Vector DB memory.

        Output format:
        {
            "chunk_text": str,
            "chunk_id": str (MD5 hash),
            "chunk_index": int,
            "metadata": {
                "source_file": str,
                "document_id": str,
                "page_number": int | None,
                "chapter": str | None,
                "chapter_number": int | None,
                "parent_heading": str | None,
            }
        }
        """
        formatted = []

        for idx, chunk in enumerate(chunks):
            text = str(chunk).strip()
            if not text:
                continue

            # Extract essential metadata (drop coordinates/bounding boxes)
            meta = chunk.metadata if hasattr(chunk, 'metadata') else None

            page_number = None
            chapter = None
            chapter_number = None
            parent_heading = None

            if meta:
                page_number = getattr(meta, 'page_number', None)
                chapter = getattr(meta, 'chapter', None)
                chapter_number = getattr(meta, 'chapter_number', None)
                parent_heading = getattr(meta, 'parent_heading', None)

            chunk_id = hashlib.md5(
                f"{document_id}:{idx}".encode()
            ).hexdigest()

            formatted.append({
                "chunk_text": text,
                "chunk_id": chunk_id,
                "chunk_index": idx,
                "metadata": {
                    "source_file": Path(source_file).name,
                    "document_id": document_id,
                    "textbook_id": document_id,
                    "page_number": page_number,
                    "chapter": chapter,
                    "chapter_number": chapter_number,
                    "parent_heading": parent_heading,
                },
            })

        return formatted

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Storage
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    async def _store_chunks(
        self, formatted_chunks: list[dict], document_id: str
    ) -> list[str]:
        """
        Store chunks in Pinecone (vectors) and PostgreSQL (raw text for BM25).
        """
        if not formatted_chunks:
            return []

        texts = [c["chunk_text"] for c in formatted_chunks]
        ids = [c["chunk_id"] for c in formatted_chunks]

        # Prepare Pinecone metadata (only essential fields, no large text blobs)
        pinecone_metadatas = [
            {
                "document_id": c["metadata"]["document_id"],
                "textbook_id": c["metadata"]["textbook_id"],
                "section_id": c["metadata"].get("section_id"),
                "page": c["metadata"]["page_number"],
                "chapter": c["metadata"]["chapter"] or "",
                "chapter_number": c["metadata"]["chapter_number"] or 0,
                "parent_heading": c["metadata"]["parent_heading"] or "",
                "chunk_id": c["chunk_id"],
                "chunk_index": c["chunk_index"],
            }
            for c in formatted_chunks
        ]

        # 1. Store embeddings in Pinecone
        await self.vector_store.aadd_texts(
            texts=texts,
            metadatas=pinecone_metadatas,
            ids=ids,
        )

        # 2. Store raw text + metadata in PostgreSQL for BM25 keyword search
        if self.db_session is not None:
            from app.models.textbook import TextbookChunk

            for chunk_data in formatted_chunks:
                db_chunk = TextbookChunk(
                    textbook_id=document_id,
                    section_id=chunk_data["metadata"].get("section_id"),
                    chunk_id=chunk_data["chunk_id"],
                    chunk_index=chunk_data["chunk_index"],
                    content=chunk_data["chunk_text"],
                    page=chunk_data["metadata"]["page_number"],
                    chapter=chunk_data["metadata"]["chapter"],
                    parent_heading=chunk_data["metadata"]["parent_heading"],
                    metadata_json=json.dumps(
                        chunk_data["metadata"], ensure_ascii=False
                    ),
                )
                self.db_session.add(db_chunk)

        return ids

    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
    # Helpers
    # â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

    def _count_pages(self, elements: list) -> int:
        """Count unique pages from element metadata."""
        pages = set()
        for el in elements:
            if hasattr(el, 'metadata') and hasattr(el.metadata, 'page_number'):
                if el.metadata.page_number is not None:
                    pages.add(el.metadata.page_number)
        return len(pages) or 1

    def _derive_sections(
        self,
        formatted_chunks: list[dict],
        chapters: list[dict],
        document_id: str,
    ) -> list[dict]:
        """Derive curriculum sections from chunk metadata with chapter/lesson/topic hierarchy."""
        chapter_nodes: dict[int, dict] = {}
        sections: list[dict] = []
        order_counter = 1

        for chapter in chapters:
            chapter_number = int(chapter.get("chapter_number") or 0)
            chapter_key = f"chapter:{chapter_number}" if chapter_number > 0 else "chapter:general"
            chapter_section_id = self._compose_section_id(document_id, chapter_key)
            section = {
                "section_key": chapter_section_id,
                "parent_key": None,
                "section_id": chapter_section_id,
                "parent_section_id": None,
                "section_title": chapter.get("title") or (f"Chapter {chapter_number}" if chapter_number > 0 else "General"),
                "section_type": "chapter",
                "section_order": order_counter,
                "page_from": chapter.get("start_page"),
                "page_to": chapter.get("end_page"),
                "scope_label": f"chapter:{chapter_number}" if chapter_number > 0 else "general",
                "summary": None,
                "metadata": {"chapter_number": chapter_number},
            }
            chapter_nodes[chapter_number] = section
            sections.append(section)
            order_counter += 1

        heading_lookup: dict[tuple[int, str], dict] = {}
        heading_summaries: dict[str, list[str]] = {}

        for chunk in formatted_chunks:
            metadata = chunk.get("metadata") or {}
            chapter_number = int(metadata.get("chapter_number") or 0)
            page_number = metadata.get("page_number")
            heading = (metadata.get("parent_heading") or "").strip()

            if chapter_number not in chapter_nodes:
                chapter_key = f"chapter:{chapter_number}" if chapter_number > 0 else "chapter:general"
                chapter_section_id = self._compose_section_id(document_id, chapter_key)
                section = {
                    "section_key": chapter_section_id,
                    "parent_key": None,
                    "section_id": chapter_section_id,
                    "parent_section_id": None,
                    "section_title": f"Chapter {chapter_number}" if chapter_number > 0 else "General",
                    "section_type": "chapter",
                    "section_order": order_counter,
                    "page_from": page_number,
                    "page_to": page_number,
                    "scope_label": f"chapter:{chapter_number}" if chapter_number > 0 else "general",
                    "summary": None,
                    "metadata": {"chapter_number": chapter_number},
                }
                chapter_nodes[chapter_number] = section
                sections.append(section)
                order_counter += 1

            chapter_section = chapter_nodes[chapter_number]
            target_section_id = chapter_section["section_key"]
            if page_number is not None:
                if chapter_section["page_from"] is None or page_number < chapter_section["page_from"]:
                    chapter_section["page_from"] = page_number
                if chapter_section["page_to"] is None or page_number > chapter_section["page_to"]:
                    chapter_section["page_to"] = page_number

            if not heading:
                # MVP Requirement: ensure deterministic section_id for every chunk
                # Even if no parent_heading, attach to chapter section
                metadata["section_id"] = target_section_id
                metadata["section_key"] = target_section_id
                continue

            parent_key = chapter_section["section_key"]
            heading_chain = self._infer_heading_chain(
                heading=heading,
                chapter_number=chapter_number,
                page_number=page_number,
                order_counter=order_counter,
            )

            for index, node in enumerate(heading_chain):
                node_key = (chapter_number, str(node["section_title"]).lower())
                if node_key not in heading_lookup:
                    raw_section_key = f"{node['section_type']}:{chapter_number}:{len(heading_lookup) + 1}"
                    section_id = self._compose_section_id(document_id, raw_section_key)
                    heading_lookup[node_key] = {
                        **node,
                        "section_key": section_id,
                        "parent_key": parent_key,
                        "section_id": section_id,
                        "parent_section_id": parent_key,
                    }
                    sections.append(heading_lookup[node_key])
                    order_counter += 1

                current = heading_lookup[node_key]
                if page_number is not None:
                    if current["page_from"] is None or page_number < current["page_from"]:
                        current["page_from"] = page_number
                    if current["page_to"] is None or page_number > current["page_to"]:
                        current["page_to"] = page_number

                parent_key = current["section_key"]
                target_section_id = current["section_key"]
                if index == len(heading_chain) - 1:
                    heading_summaries.setdefault(current["section_key"], []).append(chunk.get("chunk_text", ""))

            metadata["section_id"] = target_section_id
            metadata["section_key"] = target_section_id

        for section in sections:
            summary_chunks = heading_summaries.get(section["section_key"], [])
            if summary_chunks:
                section["summary"] = " ".join(summary_chunks)[:300]

        return sections

    def _infer_heading_chain(
        self,
        heading: str,
        chapter_number: int,
        page_number: int | None,
        order_counter: int,
    ) -> list[dict]:
        normalized = re.sub(r"\s+", " ", heading.strip())
        if not normalized:
            return []

        section_type = self._classify_heading(normalized)
        metadata = {
            "chapter_number": chapter_number,
            "parent_heading": normalized,
        }
        return [
            {
                "section_title": normalized,
                "section_type": section_type,
                "section_order": order_counter,
                "page_from": page_number,
                "page_to": page_number,
                "scope_label": normalized,
                "summary": None,
                "metadata": metadata,
            }
        ]

    def _classify_heading(self, heading: str) -> str:
        lowered = heading.lower()
        if re.search(r"^(bÃ i|lesson)\s+\d+", lowered):
            return "lesson"
        if re.search(r"^(má»¥c|topic)\s+\d+", lowered):
            return "topic"
        if re.search(r"^(tiá»ƒu má»¥c|subtopic)\s+\d+", lowered):
            return "subtopic"
        if re.search(r"^\d+\.\d+\.\d+", lowered):
            return "subtopic"
        if re.search(r"^\d+\.\d+", lowered):
            return "topic"
        if len(lowered.split()) <= 2:
            return "unknown"
        return "topic"

    def _compose_section_id(self, document_id: str, section_key: str) -> str:
        normalized_key = (section_key or "").strip()
        prefix = f"{document_id}:"
        if normalized_key.startswith(prefix):
            return normalized_key
        return f"{prefix}{normalized_key}"


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# __main__ â€” Test the pipeline on a sample PDF
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

if __name__ == "__main__":
    import sys
    import asyncio

    if len(sys.argv) < 2:
        print("Usage: python -m agents.document_processor <path-to-pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Processing: {pdf_path}")
    print(f"Strategy: {STRATEGY}")
    print("=" * 60)

    # Create a lightweight processor (no vector store / DB for testing)
    class FakeVectorStore:
        async def aadd_texts(self, **kwargs):
            pass

    processor = DocumentProcessor(vector_store=FakeVectorStore())

    # Run the pipeline (steps 1-4 only, skip storage)
    elements = processor._partition(pdf_path)
    print(f"\n[Step 1] Partitioned into {len(elements)} elements")

    # Show element type distribution
    from collections import Counter
    type_counts = Counter(type(el).__name__ for el in elements)
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    elements = processor._clean(elements)
    print(f"\n[Step 2] After cleaning: {len(elements)} elements")

    elements, chapters = processor._track_hierarchy(elements)
    print(f"\n[Step 3] Detected {len(chapters)} chapters:")
    for ch in chapters:
        print(f"  Chapter {ch['chapter_number']}: {ch['title']} (pages {ch.get('start_page')}â€“{ch.get('end_page')})")

    chunks = processor._smart_chunk(elements)
    print(f"\n[Step 4] Produced {len(chunks)} chunks")

    formatted = processor._format_output(chunks, pdf_path, "test-textbook-id")
    print(f"\n[Step 5] Formatted {len(formatted)} chunks")

    # Print first 3 chunks as JSON
    print("\n" + "=" * 60)
    print("FIRST 3 CHUNKS (JSON):")
    print("=" * 60)
    for chunk_data in formatted[:3]:
        print(json.dumps(chunk_data, indent=2, ensure_ascii=False))
        print("-" * 40)


DocumentProcessorAgent = DocumentProcessor

