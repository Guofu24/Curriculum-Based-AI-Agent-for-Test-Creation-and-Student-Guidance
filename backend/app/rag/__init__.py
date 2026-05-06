"""RAG pipeline package."""

from app.rag.parser import parse_document
from app.rag.structure import detect_heading_tree, detect_heading_tree_llm, detect_heading_tree_gemini_pdf, flatten_heading_tree, post_process_heading_tree
from app.rag.extractor import extract_formulas, extract_image_description
from app.rag.chunker import semantic_chunk
from app.rag.embedder import embed_chunks, EmbeddingService
from app.rag.vector_store import get_vector_store, VectorStore

__all__ = [
    "parse_document",
    "detect_heading_tree",
    "detect_heading_tree_llm",
    "detect_heading_tree_gemini_pdf",
    "flatten_heading_tree",
    "post_process_heading_tree",
    "extract_formulas",
    "extract_image_description",
    "semantic_chunk",
    "embed_chunks",
    "EmbeddingService",
    "get_vector_store",
    "VectorStore",
]
