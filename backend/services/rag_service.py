"""
RAG Service

Manages the Pinecone vector index (free cloud tier), embedding model, and provides
a unified interface for the agents to interact with the retrieval system.

Architecture:
- Pinecone (cloud, free) — stores vector embeddings, supports similarity search
- PostgreSQL — stores raw chunk text (for BM25 keyword search)
"""
import logging

from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from config import settings

logger = logging.getLogger(__name__)


class RAGService:
    """Manages Pinecone vector index and OpenAI embeddings."""

    _instance = None

    def __init__(self):
        self._pc = None
        self._index = None
        self._embeddings = None

    @classmethod
    def get_instance(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_embeddings(self):
        """Initialize embedding model based on configured provider."""
        if self._embeddings is None:
            if settings.EMBEDDING_PROVIDER == "huggingface":
                from langchain_huggingface import HuggingFaceEmbeddings
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=settings.EMBEDDING_MODEL,
                    encode_kwargs={"normalize_embeddings": True},
                )
            else:
                from langchain_openai import OpenAIEmbeddings
                self._embeddings = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY,
                )
        return self._embeddings

    def _get_pinecone_client(self) -> Pinecone:
        """Initialize Pinecone client."""
        if self._pc is None:
            self._pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        return self._pc

    def _get_index(self):
        """Get or create the Pinecone serverless index."""
        if self._index is None:
            pc = self._get_pinecone_client()
            index_name = settings.PINECONE_INDEX_NAME

            existing = [idx.name for idx in pc.list_indexes()]
            if index_name not in existing:
                logger.info(f"Creating Pinecone index: {index_name}")
                pc.create_index(
                    name=index_name,
                    dimension=settings.EMBEDDING_DIMENSION,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud=settings.PINECONE_CLOUD,
                        region=settings.PINECONE_REGION,
                    ),
                )

            self._index = pc.Index(index_name)
        return self._index

    def get_vector_store(self, namespace: str = None) -> PineconeVectorStore:
        """Get a LangChain PineconeVectorStore scoped by document namespace."""
        index = self._get_index()
        return PineconeVectorStore(
            index=index,
            embedding=self._get_embeddings(),
            namespace=namespace,
        )

    def get_index(self):
        """Get raw Pinecone index for direct operations."""
        return self._get_index()

    def delete_document_chunks(self, document_id: str):
        """Remove all vectors for a specific document namespace."""
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=document_id)
            logger.info("Deleted Pinecone vectors for document: %s", document_id)
        except Exception as e:
            logger.warning("Failed to delete vectors for %s: %s", document_id, e)

    def delete_textbook_chunks(self, textbook_id: str):
        """Deprecated alias for legacy naming."""
        self.delete_document_chunks(textbook_id)
