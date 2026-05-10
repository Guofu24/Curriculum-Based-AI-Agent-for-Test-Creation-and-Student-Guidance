"""Document parser: Gemini (priority 1, parallel + threading), Marker (priority 2), PyMuPDF (fallback)."""

import asyncio
import time
import io
import logging
import os
import re
import threading
import random
import datetime
from typing import Callable

import fitz

_log = logging.getLogger("document.parser")

# ─── JobCoordinator — Giống hệt test_api.py ────────────────────────────────

class ParserTaskStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    FAILED_LLM = "FAILED_LLM"
    FALLBACK_MARKER = "FALLBACK_MARKER"
    FALLBACK_PYMUPDF = "FALLBACK_PYMUPDF"
    SUCCESS = "SUCCESS"


# Giống y hệt test_api.py
MAX_LLM_RETRIES = 3
CHUNK_SIZE = 10

def _get_gemini_model() -> str:
    """Get Gemini model name from settings (configurable via GEMINI_MODEL env var)."""
    from app.core.config import get_settings
    return get_settings().GEMINI_MODEL


class ParserChunkTask:
    """Đại diện cho một Chunk độc lập, có 'sinh mệnh' riêng."""
    def __init__(self, index: int, page_start: int, page_end: int, chunk_path: str):
        self.index = index
        self.page_start = page_start
        self.page_end = page_end
        self.chunk_path = chunk_path
        self.status = ParserTaskStatus.PENDING
        self.llm_retries = 0
        self.content: str | None = None
        self.error: str | None = None


class ParserJobCoordinator:
    """Quản đốc phân phối công việc và theo dõi State toàn cục — giống JobCoordinator trong test_api.py."""
    def __init__(self, tasks: list):
        self.tasks = tasks
        self.pending_queue = tasks.copy()
        self.retry_queue: list = []
        self.lock = threading.Lock()
        self.completed_count = 0
        self.total_tasks = len(tasks)

    def is_done(self) -> bool:
        with self.lock:
            return self.completed_count >= self.total_tasks

    def get_task(self, is_fallback_key: bool) -> ParserChunkTask | None:
        with self.lock:
            if len(self.retry_queue) > 0:
                task = self.retry_queue.pop(0)
                task.status = ParserTaskStatus.PROCESSING
                return task

            if not is_fallback_key and len(self.pending_queue) > 0:
                task = self.pending_queue.pop(0)
                task.status = ParserTaskStatus.PROCESSING
                return task

            return None

    def report_success(self, task: ParserChunkTask, content: str, elapsed_time: float):
        with self.lock:
            task.status = ParserTaskStatus.SUCCESS
            task.content = content
            self.completed_count += 1
            _log.info(
                "  [COORD] ✅ Chunk %d (trang %d-%d) XONG trong %.1fs! (Tổng: %d/%d)",
                task.index, task.page_start + 1, task.page_end,
                elapsed_time, self.completed_count, self.total_tasks,
            )

    def report_fail(self, task: ParserChunkTask) -> bool:
        with self.lock:
            task.llm_retries += 1
            if task.llm_retries < MAX_LLM_RETRIES:
                task.status = ParserTaskStatus.FAILED_LLM
                self.retry_queue.append(task)
                _log.warning(
                    "  [COORD] ⚠️ Chunk %d fail lần %d — đẩy về queue cứu hộ",
                    task.index, task.llm_retries,
                )
                return True
            else:
                _log.error(
                    "  [COORD] 🚑 Chunk %d HẾT HP — đưa vào Marker/PyMuPDF fallback",
                    task.index,
                )
                self._execute_deep_fallback(task)
                return False

    def _execute_deep_fallback(self, task: ParserChunkTask):
        task.status = ParserTaskStatus.FALLBACK_MARKER
        _log.info("    -> Fallback Marker cho Chunk %d (%d-%d)...",
                  task.index, task.page_start + 1, task.page_end)

        import httpx
        try:
            from app.core.config import get_settings
            marker_url = get_settings().QWEN_VISION_BASE_URL
        except Exception:
            marker_url = None

        marker_success = False
        if marker_url:
            try:
                with httpx.Client(timeout=120.0) as client:
                    with open(task.chunk_path, "rb") as f:
                        resp = client.post(
                            f"{marker_url}/parse-pdf",
                            files={"file": f},
                        )
                if resp.status_code == 200:
                    data = resp.json()
                    task.content = data.get("markdown", "")
                    task.status = ParserTaskStatus.SUCCESS
                    with self.lock:
                        self.completed_count += 1
                    _log.info("    -> Marker thành công cho Chunk %d", task.index)
                    return
            except Exception as e:
                _log.warning("    -> Marker fail cho Chunk %d: %s", task.index, e)

        task.status = ParserTaskStatus.FALLBACK_PYMUPDF
        _log.info("    -> PyMuPDF fallback cho Chunk %d (%d-%d)...",
                  task.index, task.page_start + 1, task.page_end)
        try:
            doc = fitz.open(task.chunk_path)
            task.content = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception as e:
            task.content = f"PyMuPDF error: {e}"
            task.error = str(e)

        task.status = ParserTaskStatus.SUCCESS
        with self.lock:
            self.completed_count += 1


# ─── Gemini API Call — Dùng genai SDK giống test_api.py ────────────────────

class KeyUnavailable(Exception):
    """Key bị dead (400/403) — không retry bằng key này."""
    pass


class QuotaExceeded(Exception):
    """Key bị quota tạm thời (429) — retry được sau."""
    def __init__(self, delay: float | None):
        self.delay = delay
        super().__init__(f"Quota exceeded, retry after {delay}s" if delay else "Quota exceeded")


def _build_prompt() -> str:
    return (
        "Bạn là một chuyên gia số hóa tài liệu (Document Digitization Expert) với nhiệm vụ chuyển đổi PDF thành PURE MARKDOWN. "
        "Bạn phải tái tạo lại tài liệu một cách hoàn hảo, thông minh và sạch sẽ nhất theo các quy tắc sau:\n\n"

        "1. LỌC RÁC (NOISE REDUCTION - TỐI QUAN TRỌNG): "
        "Tuyệt đối KHÔNG trích xuất các thông tin không mang giá trị nội dung như: Số trang, Tiêu đề đầu trang (Header), "
        "Chân trang (Footer), Watermark, hoặc các ghi chú in ấn lặp lại ở mép giấy.\n\n"

        "2. TÁI TẠO CẤU TRÚC (STRUCTURE & TREE): "
        "Nhận diện chính xác các cấp độ Tiêu đề (Heading) dựa trên kích thước chữ, độ đậm và ngữ cảnh. "
        "Sử dụng chuẩn Markdown (# cho H1, ## cho H2, ### cho H3...). "
        "Đảm bảo phân cấp logic của tài liệu (Document Tree) được giữ nguyên vẹn. "
        "Nếu gặp Mục lục (Table of Contents), hãy format nó thành list có thụt lề chuẩn xác.\n\n"

        "3. VĂN BẢN & CẤU TRÚC: Trích xuất 100% văn bản, không tóm tắt, không giải thích, không bỏ sót trang nào. "
        "Giữ nguyên ngôn ngữ gốc. Giữ đúng phân cấp tiêu đề Markdown (#, ##, ###).\n"

        "4. NỐI VĂN BẢN ĐỨT GÃY: "
        "Nếu một câu bị ngắt dòng, ngắt đoạn do xuống dòng hoặc sang trang mới, hãy thông minh tự động NỐI CHÚNG LẠI "
        "thành một câu liền mạch, tránh việc xuống dòng vô nghĩa giữa một câu.\n\n"

        "5. TOÁN HỌC & BẢNG BIỂU: "
        "Mọi công thức toán học phải dùng format LaTeX (dùng $$...$$ cho công thức độc lập, $...$ cho công thức trong dòng). "
        "Bảng biểu (Table) phải được format đúng chuẩn Markdown, tuyệt đối không làm mất cột hay xô lệch dữ liệu.\n\n"

        "6. XỬ LÝ HÌNH ẢNH & BIỂU ĐỒ (TỐI QUAN TRỌNG): Tuyệt đối KHÔNG dùng các từ giữ chỗ như [Hình ảnh] hay ![image.png]. "
        "Mọi hình ảnh/sơ đồ phải được chuyển thành một đoạn văn mô tả cực kỳ chi tiết đặt trong cú pháp ![Mô tả: ...]. Cụ thể:\n"
        "   - Nếu là BIỂU ĐỒ (Chart/Graph): Nêu rõ loại biểu đồ, trục X/Y biểu diễn gì, xu hướng chính, và trích xuất các con số/điểm dữ liệu quan trọng nhất trên đó.\n"
        "   - Nếu là SƠ ĐỒ (Diagram): Mô tả các khối (blocks), mũi tên luồng đi (từ đâu sang đâu), và text ghi chú trên từng khối.\n"
        "   - Nếu là ẢNH MINH HỌA: Tả rõ chủ thể, bối cảnh và ý nghĩa của bức ảnh.\n\n"

        "7. RÀNG BUỘC ĐẦU RA: Trả về CHỈ VÀ DUY NHẤT mã Markdown. KHÔNG có câu chào hỏi (VD: 'Đây là kết quả...'), "
        "KHÔNG có Markdown code block (```markdown) bao quanh toàn bộ bài. Bắt đầu ngay bằng nội dung tài liệu."
    )


def _call_gemini_sync(
    api_key: str,
    chunk_path: str,
    model_name: str,
    chunk_pages: str,
) -> str:
    """
    Gọi Gemini bằng genai SDK — GIỐNG HỆT test_api.py.
    SDK tự động: upload → poll → generate → cleanup.
    Tự retry transient errors (429, 500, 503).
    - Key die (400/403) → raise KeyUnavailable
    - Quota (429) → raise QuotaExceeded
    - Polling stuck > 60s → raise Exception (để retry)
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    poll_start = time.time()
    uploaded_file_name: str | None = None

    try:
        # 1. Upload file (SDK tự retry transient errors)
        pdf_file = client.files.upload(file=chunk_path)
        uploaded_file_name = pdf_file.name

        # 2. Poll cho đến khi file ready (max 60s)
        while pdf_file.state.name == "PROCESSING":
            if time.time() - poll_start > 60:
                raise Exception("File polling timed out after 60s (still PROCESSING)")
            time.sleep(3)
            pdf_file = client.files.get(name=pdf_file.name)

        # 3. Generate content (SDK tự retry transient errors)
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_uri(
                    file_uri=pdf_file.uri,
                    mime_type="application/pdf",
                ),
                _build_prompt(),
            ]
        )

        # 4. Cleanup file trên server
        try:
            client.files.delete(name=pdf_file.name)
        except Exception:
            pass

        return response.text or ""

    except Exception as e:
        err_msg = str(e)
        err_lower = err_msg.lower()

        # Cleanup file đã upload nếu có
        if uploaded_file_name:
            try:
                client.files.delete(name=uploaded_file_name)
            except Exception:
                pass

        # Phân loại lỗi
        if "429" in err_msg or "quota" in err_lower or "rate limit" in err_lower:
            raise QuotaExceeded(None) from e
        if "403" in err_msg or "denied" in err_lower or "permission" in err_lower:
            raise KeyUnavailable(err_msg) from e
        if "400" in err_msg or "invalid" in err_lower or "expired" in err_lower:
            raise KeyUnavailable(err_msg) from e

        # Polling timeout hoặc 500/503 → raise thường để worker retry bằng key khác
        if "timed out" in err_lower or "503" in err_msg or "500" in err_msg or "internal" in err_lower:
            raise Exception(err_msg) from e


# ─── Thread Worker — mỗi thread = 1 API key cố định ─────────────────────────


def _thread_worker(
    worker_id: str,
    api_key: str,
    is_fallback: bool,
    coordinator: ParserJobCoordinator,
    model_name: str,
    progress_callback: Callable | None = None,
):
    """
    Mỗi Worker ôm 1 API Key, liên tục hỏi Coordinator xem có việc không.
    Giống hệt worker_thread trong test_api.py.
    Sau mỗi chunk thành công → gọi callback để broadcast live % đến frontend.
    """
    role = "FALLBACK" if is_fallback else "PRIMARY"
    time.sleep(random.uniform(0.5, 5.0))  # Stagger startup

    def _mark_used() -> None:
        try:
            from app.rag.gemini_key_pool import mark_gemini_key_used_sync
            mark_gemini_key_used_sync(api_key)
        except Exception:
            pass

    def _mark_error(error: BaseException | str) -> None:
        try:
            from app.rag.gemini_key_pool import mark_gemini_key_error_sync
            mark_gemini_key_error_sync(api_key, error)
        except Exception:
            pass

    while not coordinator.is_done():
        task = coordinator.get_task(is_fallback_key=is_fallback)

        if task is None:
            time.sleep(2)
            continue

        chunk_pages = f"{task.page_start + 1}-{task.page_end}"
        _log.info("[%s KEY %s] Nhận Chunk %d (Trang %s)", role, worker_id, task.index, chunk_pages)

        process_start = time.time()
        try:
            content = _call_gemini_sync(api_key, task.chunk_path, model_name, chunk_pages)
            process_end = time.time()
            elapsed_time = process_end - process_start
            coordinator.report_success(task, content, elapsed_time)
            _mark_used()

            # Broadcast live progress % sau mỗi chunk thành công
            if progress_callback:
                completed = coordinator.completed_count
                total = coordinator.total_tasks
                percent = min(19, int(19.0 * completed / total))
                progress_callback("parse", f"Xong chunk {completed}/{total}", percent)

        except KeyUnavailable as e:
            _log.warning("[%s KEY %s] ❌ Chunk %d: DEAD key — %s",
                         role, worker_id, task.index, str(e)[:80])
            _mark_error(e)
            coordinator.report_fail(task)
            time.sleep(15)

        except QuotaExceeded as e:
            cooldown_time = 45 + (task.llm_retries * 15)
            _log.warning("[%s KEY %s] ❌ Chunk %d: Quota — nghỉ %.0fs",
                         role, worker_id, task.index, cooldown_time)
            _mark_error(e)
            coordinator.report_fail(task)
            time.sleep(cooldown_time)

        except Exception as e:
            err_msg = str(e)[:80]
            _log.warning("[%s KEY %s] ❌ Chunk %d lỗi: %s",
                         role, worker_id, task.index, err_msg)
            _mark_error(e)
            coordinator.report_fail(task)

            if "429" in err_msg or "quota" in err_msg.lower():
                cooldown_time = 45 + (task.llm_retries * 15)
            elif "400" in err_msg:
                cooldown_time = 10
            else:
                cooldown_time = 15

            time.sleep(cooldown_time)


# ─── Gemini Parallel Executor (THREADING — giống test_api.py) ────────────────

def _parse_pdf_gemini(
    file_bytes: bytes,
    progress_callback: Callable | None = None,
) -> dict | None:
    """
    Parallel executor bằng threading — giống hệt test_api.py:
    - Mỗi key = 1 thread riêng, gọi API song song thực sự (genai SDK)
    - JobCoordinator quản lý 2 queue (retry + pending)
    - Adaptive cooldown khi bị rate limit
    - Marker / PyMuPDF fallback cho chunk fail hoàn toàn
    - Sau mỗi chunk → callback để broadcast live % đến frontend
    """
    from app.core.config import get_settings
    settings = get_settings()
    keys = settings.GEMINI_KEYS

    if not keys:
        _log.info("Gemini parse: no API key, skipping")
        return None

    # ── Chia tỉ lệ Key (60% Primary, 40% Fallback) ───────────────────────────
    num_primary = max(1, int(len(keys) * 0.60))
    primary_keys = keys[:num_primary]
    fallback_keys = keys[num_primary:]

    _log.info(
        "🔑 Tổng Keys: %d | 🚜 Primary: %d | 🚑 Fallback: %d",
        len(keys), len(primary_keys), len(fallback_keys),
    )

    # ── Cắt PDF tạo Tasks ───────────────────────────────────────────────────
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_pages = len(doc)

    tasks: list[ParserChunkTask] = []
    chunk_defs: list[tuple[int, int]] = []

    for chunk_idx, start in enumerate(range(0, total_pages, CHUNK_SIZE)):
        end = min(start + CHUNK_SIZE, total_pages)
        import tempfile
        chunk_path = tempfile.NamedTemporaryFile(
            suffix=".pdf", prefix="gemini_chunk_doc_", delete=False
        ).name

        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end - 1)
        sub.save(chunk_path, deflate=True, garbage=4)
        sub.close()

        tasks.append(ParserChunkTask(
            index=chunk_idx,
            page_start=start,
            page_end=end,
            chunk_path=chunk_path,
        ))
        chunk_defs.append((start, end))

    doc.close()
    _log.info("🎯 Đã tạo %d chunks (%d trang).", len(tasks), total_pages)

    # ── Khởi tạo Coordinator và Threads ───────────────────────────────────
    coordinator = ParserJobCoordinator(tasks)
    threads: list[threading.Thread] = []

    global_start_time = time.time()
    _log.info("🚀 KÍCH HOẠT HỆ THỐNG PHÂN TÁN threading...")

    # Primary Workers
    gemini_model = _get_gemini_model()
    for i, key in enumerate(primary_keys):
        t = threading.Thread(
            target=_thread_worker,
            args=(f"P{i+1}", key, False, coordinator, gemini_model, progress_callback),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Fallback Workers
    for i, key in enumerate(fallback_keys):
        t = threading.Thread(
            target=_thread_worker,
            args=(f"F{i+1}", key, True, coordinator, gemini_model, progress_callback),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Đợi cho đến khi Coordinator báo xong tất cả
    while not coordinator.is_done():
        time.sleep(1)

    global_end_time = time.time()
    total_elapsed = global_end_time - global_start_time

    # ── Gộp kết quả ───────────────────────────────────────────────────────
    _log.info("🧲 Đang gộp kết quả...")
    tasks.sort(key=lambda x: x.index)

    successful = [t for t in tasks if t.status == ParserTaskStatus.SUCCESS and t.content]
    failed = [t for t in tasks if t.status not in (ParserTaskStatus.SUCCESS,)]

    # Dọn dẹp file rác
    for t in tasks:
        try:
            os.remove(t.chunk_path)
        except Exception:
            pass

    # Update progress
    if progress_callback and successful:
        progress_callback("parse", f"Xong {len(successful)}/{len(tasks)} chunks", 95)

    if not successful:
        return None

    chunks_data = [
        {
            "page_start": t.page_start,
            "page_end": t.page_end,
            "content": t.content or "",
        }
        for t in sorted(tasks, key=lambda x: x.index)
        if t.status == ParserTaskStatus.SUCCESS and t.content
    ]

    total_time_formatted = str(datetime.timedelta(seconds=int(total_elapsed)))
    _log.info(
        "🎉 XONG TOÀN BỘ! %d/%d chunks thành công. "
        "Thời gian: %s (%.1fs), %.2fs/chunk",
        len(successful), len(tasks),
        total_time_formatted, total_elapsed,
        total_elapsed / len(tasks) if tasks else 0,
    )

    return {
        "content": "\n\n---\n\n".join(c["content"] for c in chunks_data),
        "page_count": total_pages,
        "chunks": chunks_data,
        "failed_ranges": [
            (t.page_start, t.page_end)
            for t in sorted(failed, key=lambda x: x.index)
        ],
    }


# ─── Marker Remote Server Parser (Priority 2) ────────────────────────────────

async def _parse_pdf_marker_server(
    file_bytes: bytes,
    filename: str = "document.pdf",
) -> dict | None:
    """Priority 2: Parse PDF via remote Marker server."""
    from app.core.config import get_settings
    settings = get_settings()
    marker_url = settings.QWEN_VISION_BASE_URL

    if not marker_url:
        _log.info("Marker server: no URL configured, skipping")
        return None

    try:
        import httpx

        marker_url = marker_url.rstrip("/")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{marker_url}/health")
            if resp.status_code != 200:
                raise Exception(f"Health check failed: {resp.status_code}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{marker_url}/parse-pdf",
                files={"file": (filename, file_bytes, "application/pdf")},
            )

        if resp.status_code != 200:
            raise Exception(f"Server returned {resp.status_code}")

        data = resp.json()
        _log.info("Marker server parsed %d pages", data.get("page_count", 0))
        return {
            "content": data.get("markdown", ""),
            "page_count": data.get("page_count", 0),
        }

    except httpx.ConnectError:
        _log.warning("Marker server unreachable — falling back to PyMuPDF")
        return None
    except Exception as e:
        _log.warning("Marker server call failed (%s) — falling back to PyMuPDF", e)
        return None


# ─── PyMuPDF Parser (Priority 3 — Fallback) ─────────────────────────────────

async def _parse_pdf_pymupdf(file_bytes: bytes) -> dict:
    """Priority 3: local PyMuPDF (CPU-only)."""
    if not file_bytes:
        raise DocumentParseError("PDF bytes are empty — cannot parse")

    try:
        doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
    except Exception as e:
        raise DocumentParseError(f"PyMuPDF could not open PDF stream: {e}")

    lines: list[str] = []
    heading_sizes: dict[float, int] = {}
    page_count = len(doc)

    for page_num in range(min(3, page_count)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
        for block in blocks:
            if "lines" not in block:
                continue
            for bline in block["lines"]:
                text = "".join(s["text"] for s in bline.get("spans", [])).strip()
                if not text or len(text) > 200:
                    continue
                for span in bline.get("spans", []):
                    size = span.get("size", 0)
                    if size >= 10:
                        heading_sizes[size] = heading_sizes.get(size, 0) + 1

    sorted_sizes = sorted(heading_sizes.items(), key=lambda x: -x[0])
    h1_size = sorted_sizes[0][0] if sorted_sizes else 0
    h2_size = sorted_sizes[1][0] if len(sorted_sizes) > 1 else 0
    h3_size = sorted_sizes[2][0] if len(sorted_sizes) > 2 else 0

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text")
        page_lines = text.split("\n")

        span_info: dict[str, list[tuple[float, bool]]] = {}
        try:
            block_dict = page.get_text("dict").get("blocks", [])
            for block in block_dict:
                if "lines" not in block:
                    continue
                for bline in block["lines"]:
                    line_text = "".join(
                        s["text"] for s in bline.get("spans", [])
                    ).strip()
                    if not line_text:
                        continue
                    for span in bline.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            info_list = span_info.setdefault(line_text, [])
                            is_b = _is_bold(span)
                            size = span.get("size", 0)
                            if (size, is_b) not in info_list:
                                info_list.append((size, is_b))
        except Exception:
            pass

        for line in page_lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            font_size: float | None = None
            is_bold = False
            for lt, infos in span_info.items():
                if line_stripped in lt or lt in line_stripped:
                    for s, b in infos:
                        if s > 0:
                            font_size = s
                            is_bold = is_bold or b

            h1 = max(h1_size, 20)
            h2 = max(h2_size, 16)
            h3 = max(h3_size, 14)

            level = 0
            if font_size:
                if font_size >= h1:
                    level = 1
                elif font_size >= h2:
                    level = 2
                elif font_size >= h3:
                    level = 3
                elif is_bold and font_size >= 12:
                    level = 3

            if level > 0:
                heading_mark = "#" * min(level, 6)
                lines.append(f"{heading_mark} {line_stripped}")
            else:
                lines.append(line_stripped)

        lines.append(f"\n<!-- Page {page_num + 1} -->\n")

    doc.close()
    _log.info(
        "PyMuPDF parsed %d pages, content length=%d",
        page_count, len("\n".join(lines)),
    )
    return {"content": "\n".join(lines), "page_count": page_count}


# ─── Public API ────────────────────────────────────────────────────────────────

class DocumentParseError(Exception):
    """Raised when document parsing fails."""
    pass


async def parse_document(
    file_bytes: bytes,
    file_type: str,
    progress_callback: Callable[[str, str, int], None] | None = None,
) -> dict:
    """Parse document: PDF uses 3-level fallback (Gemini → Marker → PyMuPDF)."""
    if file_type == "pdf":
        return await _parse_pdf(file_bytes, progress_callback=progress_callback)
    elif file_type == "docx":
        return _parse_docx(file_bytes)
    elif file_type == "pptx":
        return _parse_pptx(file_bytes)
    else:
        raise DocumentParseError(f"Unsupported file type: {file_type}")


async def _parse_pdf(
    file_bytes: bytes,
    filename: str = "document.pdf",
    progress_callback: Callable[[str, str, int], None] | None = None,
) -> dict:
    """3-level fallback: Gemini (threading + genai SDK) → Marker → PyMuPDF."""
    if not file_bytes:
        _log.error("PDF bytes are empty or None — cannot parse")
        raise DocumentParseError("PDF file bytes are empty")

    _log.info("Parsing PDF: Gemini(threading+SDK) → Marker → PyMuPDF")

    # Gemini: threading executor (chạy sync trong thread pool)
    result = await asyncio.to_thread(_parse_pdf_gemini, file_bytes, progress_callback)

    if result:
        chunks = result.get("chunks", [])
        failed_ranges = result.get("failed_ranges", [])

        if not failed_ranges:
            result.pop("chunks", None)
            result.pop("failed_ranges", None)
            return result

        _log.info(
            "Gemini: %d/%d chunks failed, filling via Marker/PyMuPDF",
            len(failed_ranges), len(chunks),
        )

        fallback_content = await _fill_failed_chunks(
            file_bytes, failed_ranges, filename,
        )
        if fallback_content:
            merged = _merge_markdown(chunks, fallback_content, failed_ranges)
            result["content"] = merged
            result.pop("chunks", None)
            result.pop("failed_ranges", None)
            return result

    # Priority 2: Marker
    result = await _parse_pdf_marker_server(file_bytes, filename)
    if result:
        return result

    # Priority 3: PyMuPDF
    _log.info("Both Gemini and Marker failed — using PyMuPDF fallback")
    return await _parse_pdf_pymupdf(bytes(file_bytes))


async def _fill_failed_chunks(
    file_bytes: bytes,
    failed_ranges: list[tuple[int, int]],
    filename: str,
) -> str | None:
    """Xử lý các chunk fail bằng Marker hoặc PyMuPDF."""
    import fitz

    marker_result = await _parse_pdf_marker_server(file_bytes, filename)
    if marker_result and marker_result.get("content"):
        return _extract_pages_from_markdown(
            marker_result["content"],
            [p for start, end in failed_ranges for p in range(start, end)],
        )

    _log.info(
        "Marker failed for failed-chunks, using PyMuPDF for %d pages",
        sum(e - s for s, e in failed_ranges),
    )
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        lines: list[str] = []

        for start, end in sorted(failed_ranges):
            for page_num in range(start, end):
                page = doc[page_num]
                text = page.get_text("text")
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
                lines.append(f"\n<!-- Page {page_num + 1} -->\n")

        doc.close()
        return "\n".join(lines)
    except Exception as e:
        _log.warning("PyMuPDF fallback for failed chunks failed: %s", e)
        return None


def _extract_pages_from_markdown(markdown: str, page_indices: list[int]) -> str:
    """Trích markdown cho các page indices cụ thể từ output của Marker."""
    if not page_indices:
        return ""

    lines = markdown.split("\n")
    result_lines: list[str] = []
    current_page = -1

    for line in lines:
        m = re.match(r"<!-- Page (\d+) -->", line)
        if m:
            current_page = int(m.group(1))
        elif current_page in page_indices:
            result_lines.append(line)

    return "\n".join(result_lines)


def _merge_markdown(
    chunks: list[dict],
    fallback_content: str,
    failed_ranges: list[tuple[int, int]],
) -> str:
    """Merge gemini chunks (đã sắp xếp theo page_start) với fallback content."""
    failed_set = {(s, e) for s, e in failed_ranges}
    merged_parts: list[str] = []

    for chunk in chunks:
        if (chunk["page_start"], chunk["page_end"]) in failed_set:
            fallback_for_chunk = _extract_pages_from_markdown(
                fallback_content,
                list(range(chunk["page_start"], chunk["page_end"])),
            )
            if fallback_for_chunk:
                merged_parts.append(fallback_for_chunk)
            else:
                _log.warning(
                    "No fallback content for failed chunk pages %d-%d",
                    chunk["page_start"], chunk["page_end"],
                )
        else:
            merged_parts.append(chunk["content"])

    return "\n\n---\n\n".join(merged_parts)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_bold(span: dict) -> bool:
    """Check if a span has bold font."""
    try:
        font_name = span.get("font", "").lower()
        return "bold" in font_name or "black" in font_name or span.get("flags", 0) & 1
    except Exception:
        return False


# ─── DOCX / PPTX ─────────────────────────────────────────────────────────────

def _parse_docx(file_bytes: bytes) -> dict:
    """Parse DOCX using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue

        style_name = para.style.name.lower() if para.style else ""

        if "heading 1" in style_name or "title" in style_name:
            lines.append(f"# {text}")
        elif "heading 2" in style_name:
            lines.append(f"## {text}")
        elif "heading 3" in style_name:
            lines.append(f"### {text}")
        elif "heading 4" in style_name:
            lines.append(f"#### {text}")
        else:
            lines.append(text)

    for table in doc.tables:
        lines.append("\n| " + " | ".join("Column" for _ in table.columns) + " |")
        lines.append("|" + "|".join("---" for _ in table.columns) + "|")
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    return {"content": "\n".join(lines), "page_count": len(doc.sections)}


def _parse_pptx(file_bytes: bytes) -> dict:
    """Parse PPTX using python-pptx."""
    from pptx import Presentation

    prs = Presentation(io.BytesIO(file_bytes))
    lines: list[str] = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        title = _get_slide_title(slide)
        if title:
            lines.append(f"## Slide {slide_num}: {title}")
        else:
            lines.append(f"## Slide {slide_num}")

        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                if shape == _get_slide_title_shape(slide):
                    continue
                lines.append(shape.text.strip())

        lines.append("")

    return {"content": "\n".join(lines), "page_count": len(prs.slides)}


def _get_slide_title(slide) -> str | None:
    """Extract slide title."""
    for shape in slide.shapes:
        if shape.has_text_frame:
            if hasattr(shape, "is_placeholder") and shape.is_placeholder:
                pp = shape.placeholder_format
                if pp.type == 1:
                    return shape.text.strip()
    return None


def _get_slide_title_shape(slide):
    """Get the title shape for exclusion."""
    for shape in slide.shapes:
        if hasattr(shape, "is_placeholder") and shape.is_placeholder:
            pp = shape.placeholder_format
            if pp.type == 1:
                return shape
    return None
