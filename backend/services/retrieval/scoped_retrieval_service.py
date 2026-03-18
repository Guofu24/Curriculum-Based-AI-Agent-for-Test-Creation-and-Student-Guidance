from __future__ import annotations

import json
import logging
import re

from agents.retrieval import RetrievalAgent
from agents.state import ExamBlueprint, RetrievedContext
from models.curriculum import Section
from models.document import DocumentChunkRecord
from repositories.document_repository import DocumentRepository
from services.curriculum.scope_service import CurriculumScopeService

logger = logging.getLogger(__name__)


class ScopedRetrievalService:
    def __init__(
        self,
        retrieval_agent: RetrievalAgent,
        repository: DocumentRepository,
        scope_service: CurriculumScopeService,
        section_by_id: dict[str, Section],
    ):
        self.retrieval_agent = retrieval_agent
        self.repository = repository
        self.scope_service = scope_service
        self.section_by_id = section_by_id

    async def retrieve_for_blueprint(
        self,
        blueprint: ExamBlueprint,
        document_id: str,
        strict_scope: bool,
    ) -> tuple[list[RetrievedContext], dict[str, dict], dict]:
        strict_scope = True
        chapter_numbers = sorted(
            {
                int(slot.target_chapter)
                for slot in blueprint.slots
                if isinstance(slot.target_chapter, int) and slot.target_chapter > 0
            }
        )
        raw_contexts = await self.retrieval_agent.retrieve_for_blueprint(
            blueprint=blueprint,
            document_id=document_id,
            chapters=chapter_numbers,
            constraints={
                "strict_scope": strict_scope,
                "max_concurrency": 1,
            },
        )

        chunk_metadata_index: dict[str, dict] = {}
        filtered_contexts: list[RetrievedContext] = []
        retrieval_stats = {
            "slots_requested": len(raw_contexts),
            "slots_with_chunks": 0,
            "slots_without_chunks": 0,
            "deterministic_fallback_hits": 0,
            "legacy_fallback_hits": 0,
        }
        for slot, context in zip(blueprint.slots, raw_contexts):
            section_id = self._extract_section_id(slot.scope_tags)
            section = self.section_by_id.get(section_id) if section_id else None
            filtered_chunks = self._filter_context_chunks(
                context=context,
                document_id=document_id,
                section=section,
                strict_scope=strict_scope,
                chunk_metadata_index=chunk_metadata_index,
            )

            if not filtered_chunks and section is not None:
                filtered_chunks, fallback_mode = await self._fallback_for_section(
                    query=context.query,
                    document_id=document_id,
                    section=section,
                    chunk_metadata_index=chunk_metadata_index,
                )
                if fallback_mode == "deterministic":
                    retrieval_stats["deterministic_fallback_hits"] += 1
                elif fallback_mode == "legacy":
                    retrieval_stats["legacy_fallback_hits"] += 1

            if filtered_chunks:
                retrieval_stats["slots_with_chunks"] += 1
            else:
                retrieval_stats["slots_without_chunks"] += 1

            filtered_contexts.append(
                RetrievedContext(
                    slot_number=context.slot_number,
                    query=context.query,
                    scope_tags=list(context.scope_tags or []),
                    chunks=filtered_chunks[:5],
                    combined_text="\n\n---\n\n".join(
                        item.get("text", "") for item in filtered_chunks[:5]
                    ),
                )
            )

        return filtered_contexts, chunk_metadata_index, retrieval_stats

    async def retrieve_for_single_question(
        self,
        query: str,
        document_id: str,
        scope_tags: list[str],
        strict_scope: bool = True,
    ) -> tuple[RetrievedContext, dict[str, dict], dict]:
        strict_scope = True
        chapter_numbers = [
            int(tag.partition(":")[2])
            for tag in scope_tags
            if isinstance(tag, str)
            and tag.startswith("chapter:")
            and tag.partition(":")[2].isdigit()
        ]
        raw_context = await self.retrieval_agent.retrieve_for_single_question(
            query=query,
            document_id=document_id,
            chapters=chapter_numbers,
            scope_tags=scope_tags,
        )

        chunk_metadata_index: dict[str, dict] = {}
        section_id = self._extract_section_id(scope_tags)
        section = self.section_by_id.get(section_id) if section_id else None
        filtered_chunks = self._filter_context_chunks(
            context=raw_context,
            document_id=document_id,
            section=section,
            strict_scope=strict_scope,
            chunk_metadata_index=chunk_metadata_index,
        )

        if not filtered_chunks and section is not None:
            filtered_chunks, fallback_mode = await self._fallback_for_section(
                query=query,
                document_id=document_id,
                section=section,
                chunk_metadata_index=chunk_metadata_index,
            )
        else:
            fallback_mode = None

        final_context = RetrievedContext(
            slot_number=raw_context.slot_number,
            query=raw_context.query,
            scope_tags=list(scope_tags or []),
            chunks=filtered_chunks[:5],
            combined_text="\n\n---\n\n".join(item.get("text", "") for item in filtered_chunks[:5]),
        )
        return final_context, chunk_metadata_index, {
            "slots_requested": 1,
            "slots_with_chunks": 1 if filtered_chunks else 0,
            "slots_without_chunks": 0 if filtered_chunks else 1,
            "deterministic_fallback_hits": 1 if fallback_mode == "deterministic" else 0,
            "legacy_fallback_hits": 1 if fallback_mode == "legacy" else 0,
        }

    def _filter_context_chunks(
        self,
        context: RetrievedContext,
        document_id: str,
        section: Section | None,
        strict_scope: bool,
        chunk_metadata_index: dict[str, dict],
    ) -> list[dict]:
        filtered_chunks = []
        for chunk in context.chunks:
            metadata = dict(chunk.get("metadata") or {})
            chunk_id = str(chunk.get("id") or metadata.get("chunk_id") or "")
            if section is not None and strict_scope:
                metadata_section_id = str(metadata.get("section_id") or "").strip()
                if metadata_section_id:
                    if metadata_section_id != section.id:
                        continue
                else:
                    logger.debug(
                        "Chunk %s has no section_id metadata; using legacy heuristic match for section %s",
                        chunk_id or "<unknown>",
                        section.id,
                    )
                    if not self.scope_service.chunk_matches_section(metadata, section):
                        continue

            metadata["document_id"] = document_id
            if section is not None and not metadata.get("section_id"):
                metadata["section_id"] = section.id

            if chunk_id:
                chunk_metadata_index[chunk_id] = metadata

            filtered_chunks.append(
                {
                    "id": chunk_id,
                    "text": chunk.get("text", ""),
                    "metadata": metadata,
                    "score": chunk.get("score", 0.0),
                }
            )
        return filtered_chunks

    async def _fallback_for_section(
        self,
        query: str,
        document_id: str,
        section: Section,
        chunk_metadata_index: dict[str, dict],
    ) -> tuple[list[dict], str | None]:
        query_tokens = set(self._tokenize(query))
        deterministic_rows = await self.repository.get_document_chunks_for_sections(
            document_id=document_id,
            section_ids=[section.id],
        )
        deterministic_matches: list[tuple[float, dict]] = []
        for row in deterministic_rows:
            metadata = self._parse_chunk_metadata(row)
            text = row.content or ""
            text_tokens = set(self._tokenize(text))
            score = 0.0
            if query_tokens and text_tokens:
                score = len(query_tokens & text_tokens) / max(len(query_tokens), 1)

            metadata["document_id"] = document_id
            metadata["section_id"] = section.id
            chunk_metadata_index[row.chunk_id] = metadata
            deterministic_matches.append(
                (
                    score,
                    {
                        "id": row.chunk_id,
                        "text": text,
                        "metadata": metadata,
                        "score": round(score, 4),
                    },
                )
            )

        deterministic_matches.sort(key=lambda item: item[0], reverse=True)
        if deterministic_matches:
            logger.info(
                "Scoped retrieval fallback resolved %s deterministic chunk(s) for section %s",
                len(deterministic_matches),
                section.id,
            )
            return [item[1] for item in deterministic_matches[:5]], "deterministic"

        legacy_rows = await self.repository.get_document_chunks_without_section_id(document_id)
        legacy_matches: list[tuple[float, dict]] = []
        for row in legacy_rows:
            metadata = self._parse_chunk_metadata(row)
            if not self.scope_service.chunk_matches_section(metadata, section):
                continue

            text = row.content or ""
            text_tokens = set(self._tokenize(text))
            score = 0.0
            if query_tokens and text_tokens:
                score = len(query_tokens & text_tokens) / max(len(query_tokens), 1)

            metadata["document_id"] = document_id
            metadata["section_id"] = section.id
            chunk_metadata_index[row.chunk_id] = metadata
            legacy_matches.append(
                (
                    score,
                    {
                        "id": row.chunk_id,
                        "text": text,
                        "metadata": metadata,
                        "score": round(score, 4),
                    },
                )
            )

        legacy_matches.sort(key=lambda item: item[0], reverse=True)
        if legacy_matches:
            logger.warning(
                "Scoped retrieval used legacy heuristic fallback for section %s because no deterministic section_id rows were available",
                section.id,
            )
            return [item[1] for item in legacy_matches[:5]], "legacy"
        return [], None

    def _extract_section_id(self, scope_tags: list[str]) -> str | None:
        for tag in scope_tags or []:
            if not isinstance(tag, str) or not tag.startswith("section:"):
                continue
            _, _, section_id = tag.partition(":")
            if section_id:
                return section_id
        return None

    def _parse_chunk_metadata(self, row: DocumentChunkRecord) -> dict:
        metadata: dict = {}
        try:
            if row.metadata_json:
                metadata = json.loads(row.metadata_json)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        metadata = dict(metadata or {})
        metadata.setdefault("chapter_number", self._extract_chapter_number(row.chapter))
        metadata.setdefault("parent_heading", row.parent_heading)
        metadata.setdefault("page", row.page)
        metadata.setdefault("chunk_id", row.chunk_id)
        metadata.setdefault("section_id", row.section_id)
        return metadata

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", (text or "").lower())

    def _extract_chapter_number(self, value) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            match = re.search(r"(\d+)", value)
            if match:
                return int(match.group(1))
        return 0
