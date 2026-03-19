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
from services.fallback_embeddings import DeterministicHashEmbeddings, NoOpVectorStore

logger = logging.getLogger(__name__)


class RAGService:
    """Manages Pinecone vector index and OpenAI embeddings."""

    _instance = None

    def __init__(self):
        self._pc = None
        self._index = None
        self._embeddings = None
        self._using_fallback_embeddings = False

    @classmethod
    def get_instance(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_embeddings(self):
        """Initialize embedding model based on configured provider."""
        if self._embeddings is None:
            if settings.EMBEDDING_PROVIDER == "huggingface":
                try:
                    from langchain_huggingface import HuggingFaceEmbeddings

                    self._embeddings = HuggingFaceEmbeddings(
                        model_name=settings.EMBEDDING_MODEL,
                        encode_kwargs={"normalize_embeddings": True},
                    )
                except Exception as exc:
                    if not settings.EMBEDDING_ALLOW_FALLBACK:
                        raise
                    logger.warning(
                        "Falling back to deterministic hash embeddings because "
                        "HuggingFace embeddings could not initialize: %s",
                        exc,
                    )
                    self._embeddings = DeterministicHashEmbeddings(
                        dimension=settings.EMBEDDING_DIMENSION,
                    )
                    self._using_fallback_embeddings = True
            else:
                from langchain_openai import OpenAIEmbeddings
                self._embeddings = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY,
                )
                self._using_fallback_embeddings = False
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

    def get_vector_store(self, namespace: str = None) -> PineconeVectorStore | NoOpVectorStore:
        """Get the active vector store scoped by document namespace."""
        embedding_backend = self._get_embeddings()
        if (
            self._using_fallback_embeddings
            and settings.EMBEDDING_DISABLE_VECTOR_INDEX_WHEN_FALLBACK
        ):
            logger.warning(
                "Using BM25/local retrieval only for namespace %s because fallback "
                "embeddings are active and vector indexing is disabled in degraded mode.",
                namespace or "<default>",
            )
            return NoOpVectorStore(namespace=namespace)

        index = self._get_index()
        return PineconeVectorStore(
            index=index,
            embedding=embedding_backend,
            namespace=namespace,
        )

    def get_index(self):
        """Get raw Pinecone index for direct operations."""
        return self._get_index()

    def delete_document_chunks(self, document_id: str):
        """Remove all vectors for a specific document namespace."""
        if (
            self._using_fallback_embeddings
            and settings.EMBEDDING_DISABLE_VECTOR_INDEX_WHEN_FALLBACK
        ):
            logger.info(
                "Skipping vector delete for document %s because degraded fallback mode "
                "never wrote Pinecone vectors.",
                document_id,
            )
            return
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=document_id)
            logger.info("Deleted Pinecone vectors for document: %s", document_id)
        except Exception as e:
            logger.warning("Failed to delete vectors for %s: %s", document_id, e)

    def delete_textbook_chunks(self, textbook_id: str):
        """Deprecated alias for legacy naming."""
        self.delete_document_chunks(textbook_id)
