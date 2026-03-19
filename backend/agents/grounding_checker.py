"""
Grounding Checker — Hybrid Heuristic Source Verification (Phase 2)

Validates that generated questions are properly grounded in source material
using multiple heuristic methods (no LLM calls, no heavy dependencies):

1. **Per-chunk source traceability** — which source chunk supports the
   question stem, correct answer, and each distractor individually.
2. **Lexical overlap** — keyword Jaccard with Vietnamese+English stopword removal.
3. **Phrase overlap** — longest common subsequence (LCS) ratio to catch
   paraphrased content that word-level overlap misses.
4. **N-gram overlap** — character trigram Jaccard (lightweight).
5. **Correct answer support** — scored 0-1 (not just boolean) combining
   token overlap + phrase match against source.
6. **Per-distractor analysis** — individual score for each MCQ option:
   a distractor should have *some* plausibility (moderate overlap) but
   NOT be more supported than the correct answer.
7. **Verbatim detection** — flags questions that copy source text too
   closely (ratio > threshold), indicating poor synthesis.
"""
import re
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)

# ── Stopwords (Vietnamese + English, minimal) ───────────────────

_STOPWORDS = frozenset({
    # Vietnamese
    "và", "của", "là", "có", "được", "cho", "với", "này", "đó", "một",
    "các", "những", "trong", "từ", "ra", "khi", "đến", "để", "theo",
    "về", "cũng", "như", "hay", "hoặc", "nhưng", "mà", "nếu", "thì",
    "sẽ", "đã", "đang", "rất", "hơn", "nhất", "nên", "vì", "bởi",
    "tại", "do", "không", "còn", "lại", "đây", "nào", "bị", "vào",
    "qua", "trên", "dưới", "sau", "trước",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must", "need", "this",
    "that", "these", "those", "and", "but", "or", "not", "no", "nor",
    "for", "with", "from", "into", "onto", "upon", "at", "by", "to",
    "in", "on", "of", "it", "its", "if", "so", "as", "than", "then",
    "very", "just", "also", "more", "most", "such", "each", "which",
    "what", "who", "how", "when", "where", "why", "all", "any", "some",
})


# ── Data structures ─────────────────────────────────────────────

@dataclass
class ChunkTrace:
    """Source traceability for a single chunk."""
    chunk_index: int
    chunk_id: str
    stem_overlap: float = 0.0       # question stem vs this chunk
    answer_overlap: float = 0.0     # correct answer vs this chunk
    phrase_match: float = 0.0       # LCS-ratio against question
    is_best_for_stem: bool = False
    is_best_for_answer: bool = False


@dataclass
class DistractorDetail:
    """Grounding detail for a single MCQ distractor."""
    label: str
    text: str
    source_overlap: float = 0.0     # keyword overlap with source
    phrase_match: float = 0.0       # LCS ratio with source
    exceeds_correct: bool = False   # True = bad: more supported than correct


@dataclass
class GroundingReport:
    """Detailed grounding analysis for a single question."""
    slot_number: int
    # ── Aggregate scores ────────────────────────────────────────
    lexical_overlap: float = 0.0
    ngram_overlap: float = 0.0
    phrase_overlap: float = 0.0     # LCS-ratio (question vs best source chunk)
    answer_support_score: float = 0.0   # 0.0-1.0 (continuous, not boolean)
    answer_supported: bool = False      # kept for backward compat (threshold)
    distractors_valid: bool = True
    verbatim_ratio: float = 0.0    # how much is copied verbatim from source
    overall_score: float = 0.0
    grounding_pass: bool = False
    # ── Detailed breakdowns ─────────────────────────────────────
    source_traceability: list[ChunkTrace] = field(default_factory=list)
    distractor_details: list[DistractorDetail] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


# ── Grounding thresholds ────────────────────────────────────────

GROUNDING_PASS_THRESHOLD = 0.35
VERBATIM_WARNING_THRESHOLD = 0.70
ANSWER_SUPPORT_THRESHOLD = 0.30


class GroundingChecker:
    """Validates question grounding against source material using heuristics."""

    # Weights for overall score
    W_LEXICAL = 0.20
    W_NGRAM = 0.10
    W_PHRASE = 0.20
    W_ANSWER = 0.30
    W_DISTRACTOR = 0.10
    W_VERBATIM_PENALTY = 0.10  # penalizes over-copying

    def check(self, question: GeneratedQuestion) -> GroundingReport:
        """
        Run all grounding checks on a single question.

        This is the main entry point — backward compatible with Phase 1.
        """
        report = GroundingReport(slot_number=question.slot_number)

        source_texts = question.source_texts or []
        source_chunks = question.source_chunks or []
        combined_source = " ".join(source_texts).strip()

        if not combined_source:
            report.details.append("No source text available for grounding check")
            return report

        # ── 1. Per-chunk source traceability ────────────────────────
        report.source_traceability = self._trace_sources(
            question, source_texts, source_chunks,
        )

        # ── 2. Lexical overlap (keyword Jaccard) ────────────────────
        report.lexical_overlap = self._lexical_overlap(
            question.content, combined_source,
        )

        # ── 3. N-gram overlap (char trigrams) ───────────────────────
        report.ngram_overlap = self._ngram_overlap(
            question.content, combined_source, n=3,
        )

        # ── 4. Phrase overlap (LCS ratio vs best chunk) ─────────────
        report.phrase_overlap = self._phrase_overlap_best_chunk(
            question.content, source_texts,
        )

        # ── 5. Correct answer support (scored 0-1) ──────────────────
        report.answer_support_score = self._score_answer_support(
            question, combined_source,
        )
        report.answer_supported = (
            report.answer_support_score >= ANSWER_SUPPORT_THRESHOLD
        )

        # ── 6. Per-distractor analysis (MCQ) ────────────────────────
        if question.question_type == "mcq" and question.options:
            report.distractor_details, report.distractors_valid = (
                self._analyze_distractors(question, combined_source)
            )

        # ── 7. Verbatim detection ───────────────────────────────────
        report.verbatim_ratio = self._check_verbatim(
            question.content, source_texts,
        )
        if report.verbatim_ratio >= VERBATIM_WARNING_THRESHOLD:
            report.details.append(
                f"Question may be too close to source text "
                f"(verbatim≈{report.verbatim_ratio:.0%})"
            )

        # ── Overall score ───────────────────────────────────────────
        verbatim_penalty = (
            max(0.0, report.verbatim_ratio - VERBATIM_WARNING_THRESHOLD)
        )
        distractor_score = 1.0 if report.distractors_valid else 0.3

        report.overall_score = max(0.0, (
            self.W_LEXICAL * report.lexical_overlap
            + self.W_NGRAM * report.ngram_overlap
            + self.W_PHRASE * report.phrase_overlap
            + self.W_ANSWER * report.answer_support_score
            + self.W_DISTRACTOR * distractor_score
            - self.W_VERBATIM_PENALTY * verbatim_penalty
        ))

        report.grounding_pass = report.overall_score >= GROUNDING_PASS_THRESHOLD

        # ── Append human-readable details ───────────────────────────
        if report.lexical_overlap < 0.1:
            report.details.append(
                f"Very low lexical overlap ({report.lexical_overlap:.0%})"
            )
        if report.phrase_overlap < 0.1:
            report.details.append(
                f"Very low phrase overlap ({report.phrase_overlap:.0%})"
            )
        if not report.answer_supported:
            report.details.append(
                f"Correct answer weakly supported "
                f"(score={report.answer_support_score:.2f})"
            )
        if not report.distractors_valid:
            bad = [d.label for d in report.distractor_details if d.exceeds_correct]
            report.details.append(
                f"Distractor(s) {bad} may be more supported than correct answer"
            )

        return report

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Tokenization
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tokenize(self, text: str) -> set[str]:
        """Tokenize, remove stopwords, keep words > 2 chars."""
        words = re.findall(r"\w+", text.lower())
        return {w for w in words if len(w) > 2 and w not in _STOPWORDS}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. Per-chunk source traceability
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _trace_sources(
        self,
        question: GeneratedQuestion,
        source_texts: list[str],
        source_chunk_ids: list[str],
    ) -> list[ChunkTrace]:
        """Compute per-chunk overlap for question stem and correct answer."""
        traces: list[ChunkTrace] = []

        correct_text = self._extract_correct_text(question)
        best_stem_score = -1.0
        best_answer_score = -1.0
        best_stem_idx = -1
        best_answer_idx = -1

        for i, chunk_text in enumerate(source_texts):
            chunk_id = source_chunk_ids[i] if i < len(source_chunk_ids) else f"chunk_{i}"

            stem_ov = self._lexical_overlap(question.content, chunk_text)
            answer_ov = (
                self._lexical_overlap(correct_text, chunk_text)
                if correct_text else 0.0
            )
            phrase = self._phrase_similarity(question.content, chunk_text)

            trace = ChunkTrace(
                chunk_index=i,
                chunk_id=chunk_id,
                stem_overlap=round(stem_ov, 3),
                answer_overlap=round(answer_ov, 3),
                phrase_match=round(phrase, 3),
            )
            traces.append(trace)

            if stem_ov > best_stem_score:
                best_stem_score = stem_ov
                best_stem_idx = i
            if answer_ov > best_answer_score:
                best_answer_score = answer_ov
                best_answer_idx = i

        if traces and best_stem_idx >= 0:
            traces[best_stem_idx].is_best_for_stem = True
        if traces and best_answer_idx >= 0:
            traces[best_answer_idx].is_best_for_answer = True

        return traces

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. Lexical overlap (keyword Jaccard — directional)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _lexical_overlap(self, query_text: str, source_text: str) -> float:
        """Fraction of query keywords found in source."""
        q_tokens = self._tokenize(query_text)
        s_tokens = self._tokenize(source_text)
        if not q_tokens:
            return 0.0
        return len(q_tokens & s_tokens) / len(q_tokens)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. Character n-gram overlap (Jaccard)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ngram_overlap(self, text1: str, text2: str, n: int = 3) -> float:
        """Character n-gram Jaccard similarity."""
        def _ngrams(text: str) -> set[str]:
            t = re.sub(r"\s+", " ", text.lower().strip())
            return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else set()

        ng1, ng2 = _ngrams(text1), _ngrams(text2)
        if not ng1 or not ng2:
            return 0.0
        intersection = ng1 & ng2
        union = ng1 | ng2
        return len(intersection) / len(union) if union else 0.0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. Phrase overlap (LCS ratio)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _phrase_similarity(self, text1: str, text2: str) -> float:
        """
        SequenceMatcher ratio on normalized text (capped at 500 chars each).
        This catches phrase-level paraphrasing that word Jaccard misses.
        """
        if not text1 or not text2:
            return 0.0
        t1 = re.sub(r"\s+", " ", text1.lower().strip())[:500]
        t2 = re.sub(r"\s+", " ", text2.lower().strip())[:500]
        return SequenceMatcher(None, t1, t2).ratio()

    def _phrase_overlap_best_chunk(
        self, question_text: str, source_texts: list[str]
    ) -> float:
        """Return the best phrase-overlap ratio across all source chunks."""
        if not source_texts:
            return 0.0
        return max(
            self._phrase_similarity(question_text, st) for st in source_texts
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. Correct answer support (scored 0-1)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _score_answer_support(
        self, question: GeneratedQuestion, source_text: str
    ) -> float:
        """
        How well the correct answer is supported by the source.
        Returns 0.0 - 1.0 combining lexical + phrase evidence.
        """
        correct_text = self._extract_correct_text(question)
        if not correct_text:
            return 0.0

        lex = self._lexical_overlap(correct_text, source_text)
        phrase = self._phrase_similarity(correct_text, source_text)

        # Weighted: lexical + phrase, cap at 1.0
        return min(1.0, 0.6 * lex + 0.4 * phrase)

    def _extract_correct_text(self, question: GeneratedQuestion) -> str:
        """Get the text of the correct answer (option text for MCQ)."""
        if not question.correct_answer:
            return ""
        if question.question_type == "mcq" and question.options:
            for opt in question.options:
                if not isinstance(opt, dict):
                    continue
                if opt.get("label") == question.correct_answer.strip():
                    return opt.get("text", "")
        return question.correct_answer

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. Per-distractor analysis
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _analyze_distractors(
        self, question: GeneratedQuestion, source_text: str
    ) -> tuple[list[DistractorDetail], bool]:
        """
        Analyze each MCQ option individually.

        A distractor is *problematic* if its source support exceeds
        the correct answer's support by a margin.

        Returns (details_list, all_valid_bool).
        """
        if not question.options or not question.correct_answer:
            return [], True

        correct_label = question.correct_answer.strip()
        correct_text = self._extract_correct_text(question)
        correct_lex = self._lexical_overlap(correct_text, source_text) if correct_text else 0.0
        correct_phrase = self._phrase_similarity(correct_text, source_text) if correct_text else 0.0
        correct_combined = 0.6 * correct_lex + 0.4 * correct_phrase

        details: list[DistractorDetail] = []
        all_valid = True

        for opt in question.options:
            if not isinstance(opt, dict):
                all_valid = False
                continue
            label = opt.get("label", "")
            if label == correct_label:
                continue

            opt_text = opt.get("text", "")
            if not opt_text:
                details.append(DistractorDetail(label=label, text=""))
                continue

            lex = self._lexical_overlap(opt_text, source_text)
            phrase = self._phrase_similarity(opt_text, source_text)
            combined = 0.6 * lex + 0.4 * phrase

            exceeds = combined > correct_combined + 0.15 and combined > 0.4

            details.append(DistractorDetail(
                label=label,
                text=opt_text[:100],  # truncate for report
                source_overlap=round(lex, 3),
                phrase_match=round(phrase, 3),
                exceeds_correct=exceeds,
            ))

            if exceeds:
                all_valid = False

        return details, all_valid

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. Verbatim detection
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _check_verbatim(
        self, question_text: str, source_texts: list[str]
    ) -> float:
        """
        Detect how much the question is a verbatim copy of any source chunk.
        Returns 0.0-1.0 ratio (SequenceMatcher on best matching chunk).
        """
        if not source_texts:
            return 0.0
        q = re.sub(r"\s+", " ", question_text.lower().strip())[:400]
        best = 0.0
        for st in source_texts:
            s = re.sub(r"\s+", " ", st.lower().strip())[:400]
            ratio = SequenceMatcher(None, q, s).ratio()
            if ratio > best:
                best = ratio
        return best
