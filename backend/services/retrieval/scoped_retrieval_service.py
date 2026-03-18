from __future__ import annotations

import json
import re

from agents.retrieval import RetrievalAgent
from agents.state import ExamBlueprint, RetrievedContext
from models.curriculum import Section
from models.textbook import TextbookChunk
from repositories.document_repository import DocumentRepository
from services.curriculum.scope_service import CurriculumScopeService


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
    ) -> tuple[list[RetrievedContext], dict[str, dict]]:
        chapter_numbers = sorted(
            {
                int(slot.target_chapter)
                for slot in blueprint.slots
                if isinstance(slot.target_chapter, int) and slot.target_chapter > 0
            }
        )
        raw_contexts = await self.retrieval_agent.retrieve_for_blueprint(
            blueprint=blueprint,
            textbook_id=document_id,
            chapters=chapter_numbers,
            constraints={
                "strict_scope": strict_scope,
                "max_concurrency": 1,
            },
        )

        chunk_metadata_index: dict[str, dict] = {}
        filtered_contexts: list[RetrievedContext] = []
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
                filtered_chunks = await self._fallback_for_section(
                    query=context.query,
                    document_id=document_id,
                    section=section,
                    chunk_metadata_index=chunk_metadata_index,
                )

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

        return filtered_contexts, chunk_metadata_index

    async def retrieve_for_single_question(
        self,
        query: str,
        document_id: str,
        scope_tags: list[str],
        strict_scope: bool = True,
    ) -> tuple[RetrievedContext, dict[str, dict]]:
        chapter_numbers = [
            int(tag.partition(":")[2])
            for tag in scope_tags
            if isinstance(tag, str)
            and tag.startswith("chapter:")
            and tag.partition(":")[2].isdigit()
        ]
        raw_context = await self.retrieval_agent.retrieve_for_single_question(
            query=query,
            textbook_id=document_id,
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
            filtered_chunks = await self._fallback_for_section(
                query=query,
                document_id=document_id,
                section=section,
                chunk_metadata_index=chunk_metadata_index,
            )

        final_context = RetrievedContext(
            slot_number=raw_context.slot_number,
            query=raw_context.query,
            scope_tags=list(scope_tags or []),
            chunks=filtered_chunks[:5],
            combined_text="\n\n---\n\n".join(item.get("text", "") for item in filtered_chunks[:5]),
        )
        return final_context, chunk_metadata_index

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
            if section is not None and strict_scope:
                if not self.scope_service.chunk_matches_section(metadata, section):
                    continue

            metadata["document_id"] = document_id
            if section is not None:
                metadata["section_id"] = section.id

            chunk_id = str(chunk.get("id") or metadata.get("chunk_id") or "")
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
    ) -> list[dict]:
        rows = await self.repository.get_document_chunks(document_id)
        matches: list[tuple[float, dict]] = []
        query_tokens = set(self._tokenize(query))
        for row in rows:
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
            matches.append(
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

        matches.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in matches[:5]]

    def _extract_section_id(self, scope_tags: list[str]) -> str | None:
        for tag in scope_tags or []:
            if not isinstance(tag, str) or not tag.startswith("section:"):
                continue
            _, _, section_id = tag.partition(":")
            if section_id:
                return section_id
        return None

    def _parse_chunk_metadata(self, row: TextbookChunk) -> dict:
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
