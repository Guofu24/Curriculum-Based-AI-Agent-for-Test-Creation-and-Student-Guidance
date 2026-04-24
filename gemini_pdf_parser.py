"""
Standalone Gemini PDF Parser
============================
Script độc lập để test trên Kaggle.

Chức năng:
  1. Nhận file PDF (upload lên Kaggle hoặc từ URL)
  2. Chia PDF thành các chunk N trang
  3. Gọi Gemini 2.5 Flash để parse mỗi chunk → Markdown
  4. Nối tất cả chunk lại → trả markdown cuối cùng
  5. Lưu file .md ra output

Cách dùng trên Kaggle:
  1. Upload file .py này lên Kaggle
  2. Điền API key Gemini vào ô "Add-ons > Secrets"
     - Name: GEMINI_API_KEY
     - Value: AIza...
  3. Upload file PDF cần parse vào input (Data)
  4. Chạy notebook, điều chỉnh biến FILE_PATH bên dưới

Ưu điểm:
  - Đa key: nếu có nhiều API key, script sẽ luân chuyển
  - Retry thông minh: đọc retryDelay từ API, chờ đúng thời gian
  - Fallback: chunk fail → PyMuPDF bù trừ
  - Progress: in ra log từng chunk để theo dõi
"""

# ─────────────────────────────────────────────────────────────
# CẤU HÌNH — Sửa các giá trị bên dưới trước khi chạy
# ─────────────────────────────────────────────────────────────

# Đường dẫn file PDF cần parse (đặt trong Kaggle Input)
FILE_PATH = "/kaggle/input/your-pdf-file/document.pdf"   # ← Sửa đường dẫn file

# API Keys — thêm nhiều key phân cách bằng dấu phẩy để tăng rate limit
# Trên Kaggle: Add-ons > Secrets > GEMINI_API_KEY hoặc GEMINI_API_KEYS
# Hoặc sửa trực tiếp biến này
API_KEYS = ""   # ví dụ: "key1,key2,key3"  (bỏ trống → đọc từ env/secrets)

# Model Gemini dùng để parse
MODEL_NAME = "gemini-2.5-flash"

# Số trang mỗi chunk — giảm nếu PDF nặng/trang dài
CHUNK_SIZE = 10

# Số lần retry tối đa cho mỗi key trên mỗi chunk
RETRY_MAX = 3

# Số cycle retry tối đa (mỗi cycle = thử lần lượt tất cả key)
MAX_CYCLES = 3

# Thư mục lưu file markdown kết quả
OUTPUT_DIR = "/kaggle/working"

# ─────────────────────────────────────────────────────────────
# THƯ VIỆN — Cài nếu chưa có
# pip install google-genai pymupdf tqdm
# ─────────────────────────────────────────────────────────────

import os
import re
import io
import time
import traceback
from pathlib import Path

# Gemini SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Chưa cài google-genai. Đang cài đặt...")
    os.system("pip install google-genai -q")
    from google import genai
    from google.genai import types

# PyMuPDF — dùng để chia chunk PDF & fallback
try:
    import fitz
except ImportError:
    print("Chưa cài PyMuPDF. Đang cài đặt...")
    os.system("pip install pymupdf -q")
    import fitz

# Progress bar
try:
    from tqdm import tqdm
except ImportError:
    os.system("pip install tqdm -q")
    from tqdm import tqdm


# ─────────────────────────────────────────────────────────────
# CẤU HÌNH API KEYS
# ─────────────────────────────────────────────────────────────

def _load_api_keys() -> list[str]:
    """Ưu tiên: env var → secrets → biến API_KEYS trong code."""
    raw = API_KEYS
    if not raw:
        raw = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
    if not raw:
        raise ValueError(
            "Chưa có API key!\n"
            "  1. Tạo secret 'GEMINI_API_KEY' trong Kaggle: Add-ons > Secrets\n"
            "  2. Hoặc điền trực tiếp vào biến API_KEYS ở đầu script"
        )
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    print(f"Tìm thấy {len(keys)} API key(s)")
    return keys


# ─────────────────────────────────────────────────────────────
# TRÍCH XUẤT RETRY DELAY TỪ EXCEPTION
# ─────────────────────────────────────────────────────────────

def _extract_retry_delay(error: Exception) -> float | None:
    """
    Parse retryDelay từ exception của Gemini API (429 / 503).
    Hỗ trợ 3 format:
      1. Dict/string trong details list
      2. Proto RetryInfo
      3. String "retry in Xs" trong error message
    """
    try:
        details = getattr(error, "details", None)
        if details:
            for detail in details:
                retry_str = None
                if isinstance(detail, dict):
                    retry_str = str(detail.get("retryDelay", ""))
                elif hasattr(detail, "retry_delay"):
                    val = getattr(detail, "retry_delay")
                    retry_str = str(val) if val is not None else ""
                if retry_str:
                    m = re.match(r"^(\d+\.?\d*)s?$", retry_str)
                    if m:
                        return float(m.group(1))

        if details:
            for detail in details:
                if not hasattr(detail, "type_url") or not hasattr(detail, "value"):
                    continue
                if "RetryInfo" not in str(detail.type_url):
                    continue
                try:
                    from google.protobuf.json_format import Parse
                    from google.rpc.error_details_pb2 import RetryInfo
                    proto = Parse(detail.value, RetryInfo())
                    rd = getattr(proto, "retry_delay", None)
                    if rd:
                        return float(rd.seconds) + rd.nanos / 1e9
                except Exception:
                    pass

        msg = str(getattr(error, "message", ""))
        m = re.search(r"(?:retry in|retry after)\s*(\d+\.?\d*)\s*s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# PARSE MỘT CHUNK BẰNG GEMINI
# ─────────────────────────────────────────────────────────────

PROMPT = (
    "Trích xuất toàn bộ nội dung file này thành format Markdown chuẩn. "
    "Giữ nguyên các heading (# ## ###), công thức toán ($$), bảng. "
    "Nếu có hình ảnh/sơ đồ/bức vẽ trong file, hãy mô tả chi tiết nội dung của chúng trong ngoặc vuông "
    "ví dụ: ![Mô tả chi tiết nội dung hình vẽ: các điểm, nhãn, đường kẻ, ký hiệu]. "
    "KHÔNG dùng placeholder như 'image-1.png' hay 'Image 1' — phải mô tả nội dung thực. "
    "Output PURE MARKDOWN, không thêm giải thích."
)


def parse_chunk_gemini(
    doc: "fitz.Document",
    start: int,
    end: int,
    keys: list[str],
) -> str | None:
    """
    Parse một chunk trang (start..end) bằng Gemini.
    Thử lần lượt key[0]→key[1]→...→key[N], mỗi key retry RETRY_MAX lần.
    Sau MAX_CYCLES cycles mà vẫn fail → trả về None.
    """
    chunk_pages = f"{start + 1}-{end}"
    chunk_path = f"/tmp/gemini_chunk_{start}_{end}.pdf"

    print(f"  📄 Chunk {chunk_pages}: đang tạo sub-PDF...")

    # Tạo sub-PDF cho chunk này
    try:
        sub_doc = fitz.open()
        sub_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        sub_doc.save(chunk_path, deflate=True, garbage=4)
        sub_doc.close()
    except Exception as e:
        print(f"  ❌ Chunk {chunk_pages}: không tạo được sub-PDF: {e}")
        return None

    for cycle in range(1, MAX_CYCLES + 1):
        cycle_errors = []

        for key_idx, api_key in enumerate(keys):
            for attempt in range(RETRY_MAX):
                try:
                    client = genai.Client(api_key=api_key)
                    attempt_label = f"cycle{cycle}_key{key_idx + 1}_a{attempt + 1}"

                    # Upload chunk lên Gemini Files API
                    pdf_file = client.files.upload(file=chunk_path)
                    while pdf_file.state.name == "PROCESSING":
                        time.sleep(3)
                        pdf_file = client.files.get(name=pdf_file.name)

                    # Gọi Gemini generate_content
                    response = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=[
                            types.Part.from_uri(
                                file_uri=pdf_file.uri,
                                mime_type=pdf_file.mime_type or "application/pdf",
                            ),
                            PROMPT,
                        ],
                    )

                    # Dọn file tạm
                    try:
                        client.files.delete(name=pdf_file.name)
                    except Exception:
                        pass

                    text = response.text or ""
                    print(f"  ✅ Chunk {chunk_pages}: thành công ở {attempt_label} ({len(text)} chars)")
                    return text

                except Exception as e:
                    cycle_errors.append(e)
                    print(f"  ⚠️  Chunk {chunk_pages} {attempt_label} fail: {str(e)[:80]}")

                    if attempt < RETRY_MAX - 1:
                        delay = _extract_retry_delay(e)
                        if delay is not None:
                            wait = min(delay, 120)
                        else:
                            wait = min(2 ** attempt * 5, 120)
                        print(f"     Chờ {wait:.0f}s trước khi retry...")
                        time.sleep(wait)

        # Hết tất cả key trong cycle → chờ rồi thử lại
        if cycle < MAX_CYCLES:
            delay: float | None = None
            for err in reversed(cycle_errors):
                delay = _extract_retry_delay(err)
                if delay is not None:
                    break
            wait = min(delay * 1.5, 300) if delay else min(2 ** cycle * 10, 300)
            print(f"  🔁 Chunk {chunk_pages}: cycle {cycle}/{MAX_CYCLES} fail. Chờ {wait:.0f}s...")
            time.sleep(wait)

    print(f"  ❌ Chunk {chunk_pages}: FAILED sau {MAX_CYCLES} cycles × {len(keys)} keys × {RETRY_MAX} retries")
    return None


# ─────────────────────────────────────────────────────────────
# PARSE TOÀN BỘ PDF BẰNG GEMINI
# ─────────────────────────────────────────────────────────────

def parse_pdf_gemini(file_bytes: bytes) -> dict | None:
    """
    Priority 1: Gemini 2.5 Flash.
    Split PDF thành chunk CHUNK_SIZE trang, mỗi chunk gọi Gemini độc lập.
    Trả dict: {"content": markdown_str, "chunks": [...], "failed_ranges": [...]}
    """
    keys = _load_api_keys()

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        print(f"\n📖 Tổng cộng: {total_pages} trang | Chunk size: {CHUNK_SIZE} trang")
        print(f"🎯 Số chunk: {(total_pages + CHUNK_SIZE - 1) // CHUNK_SIZE}\n")

        chunks_data = []

        for start in range(0, total_pages, CHUNK_SIZE):
            end = min(start + CHUNK_SIZE, total_pages)
            chunk_pages = f"{start + 1}-{end}"
            chunk_idx = start // CHUNK_SIZE

            print(f"\n[{chunk_idx + 1}/{(total_pages + CHUNK_SIZE - 1) // CHUNK_SIZE}] Chunk {chunk_pages}")
            result = parse_chunk_gemini(doc, start, end, keys)

            chunks_data.append({
                "page_start": start,
                "page_end": end,
                "content": result,
            })

        doc.close()

        # Dọn file tạm
        for start in range(0, total_pages, CHUNK_SIZE):
            end = min(start + CHUNK_SIZE, total_pages)
            chunk_path = f"/tmp/gemini_chunk_{start}_{end}.pdf"
            try:
                os.remove(chunk_path)
            except Exception:
                pass

        successful = [c for c in chunks_data if c["content"]]
        failed = [c for c in chunks_data if not c["content"]]

        print(f"\n✅ Gemini: {len(successful)}/{len(chunks_data)} chunks thành công")
        if failed:
            print(f"❌ Failed: {len(failed)} chunks ({', '.join(f'{c['page_start']+1}-{c['page_end']}' for c in failed)})")

        if not successful:
            return None

        full_content = "\n\n---\n\n".join(c["content"] for c in successful)

        return {
            "content": full_content,
            "page_count": total_pages,
            "chunks": chunks_data,
            "failed_ranges": [(c["page_start"], c["page_end"]) for c in failed],
        }

    except Exception as e:
        print(f"❌ Lỗi toàn cục khi parse Gemini: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────
# FALLBACK: PyMuPDF cho các chunk fail
# ─────────────────────────────────────────────────────────────

def parse_chunk_pymupdf(doc: "fitz.Document", start: int, end: int) -> str:
    """
    Parse một chunk trang bằng PyMuPDF (CPU).
    Dùng làm fallback khi Gemini fail.
    """
    lines: list[str] = []
    for page_num in range(start, end):
        page = doc[page_num]
        text = page.get_text("text")
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        lines.append(f"\n<!-- Page {page_num + 1} -->\n")
    return "\n".join(lines)


def fill_failed_chunks_pymupdf(file_bytes: bytes, failed_ranges: list[tuple[int, int]]) -> str:
    """
    Xử lý các chunk fail bằng PyMuPDF.
    """
    print(f"\n🔧 Fallback PyMuPDF: xử lý {len(failed_ranges)} chunk fail...")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_lines: list[str] = []

    for start, end in sorted(failed_ranges):
        print(f"  📄 Trang {start + 1}-{end}: đang parse PyMuPDF...")
        chunk_text = parse_chunk_pymupdf(doc, start, end)
        all_lines.append(chunk_text)
        print(f"  ✅ Done: {len(chunk_text)} chars")

    doc.close()
    return "\n\n---\n\n".join(all_lines)


# ─────────────────────────────────────────────────────────────
# MERGE KẾT QUẢ (Gemini + PyMuPDF fallback)
# ─────────────────────────────────────────────────────────────

def merge_content(chunks: list[dict], fallback_content: str, failed_ranges: list[tuple[int, int]]) -> str:
    """
    Merge kết quả Gemini (thành công) với PyMuPDF (bù trừ fail).
    """
    failed_set = {(s, e) for s, e in failed_ranges}
    parts: list[str] = []

    for chunk in chunks:
        if (chunk["page_start"], chunk["page_end"]) in failed_set:
            parts.append(fallback_content)
        else:
            parts.append(chunk["content"])

    return "\n\n---\n\n".join(parts)


# ─────────────────────────────────────────────────────────────
# HÀM CHÍNH — Parse file PDF
# ─────────────────────────────────────────────────────────────

def parse_document(file_path: str) -> str:
    """
    Parse file PDF và trả về markdown.
    Luồng: Gemini → PyMuPDF (nếu Gemini fail hoàn toàn)
    """
    print(f"\n{'='*60}")
    print(f"🚀 BẮT ĐẦU PARSE: {file_path}")
    print(f"{'='*60}\n")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File không tìm thấy: {file_path}")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    print(f"📦 Kích thước file: {len(file_bytes) / 1024 / 1024:.1f} MB")

    # Bước 1: Gemini
    print("\n" + "="*60)
    print("📌 BƯỚC 1: Parse bằng Gemini 2.5 Flash")
    print("="*60)
    result = parse_pdf_gemini(file_bytes)

    if result:
        failed_ranges = result.get("failed_ranges", [])
        if failed_ranges:
            # Bước 2: PyMuPDF bù trừ chunk fail
            print("\n" + "="*60)
            print(f"📌 BƯỚC 2: Fallback PyMuPDF cho {len(failed_ranges)} chunk fail")
            print("="*60)
            fallback_content = fill_failed_chunks_pymupdf(file_bytes, failed_ranges)
            final_content = merge_content(result["chunks"], fallback_content, failed_ranges)
        else:
            final_content = result["content"]

        total_chars = len(final_content)
        print(f"\n{'='*60}")
        print(f"✅ HOÀN THÀNH")
        print(f"   Trang: {result['page_count']}")
        print(f"   Tổng ký tự Markdown: {total_chars:,}")
        print(f"   Chunk thành công: {len([c for c in result['chunks'] if c['content']])}/{len(result['chunks'])}")
        print(f"{'='*60}\n")
        return final_content

    else:
        # Gemini fail hoàn toàn → PyMuPDF toàn bộ
        print("\n" + "="*60)
        print("📌 Gemini fail hoàn toàn → Fallback PyMuPDF toàn bộ file")
        print("="*60)
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        print(f"📖 {total_pages} trang")

        all_lines: list[str] = []
        for page_num in tqdm(range(total_pages), desc="Parsing PyMuPDF"):
            page = doc[page_num]
            text = page.get_text("text")
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped:
                    all_lines.append(stripped)
            all_lines.append(f"\n<!-- Page {page_num + 1} -->\n")

        doc.close()
        final_content = "\n".join(all_lines)

        print(f"\n{'='*60}")
        print(f"✅ HOÀN THÀNH (PyMuPDF)")
        print(f"   Trang: {total_pages}")
        print(f"   Tổng ký tự Markdown: {len(final_content):,}")
        print(f"{'='*60}\n")
        return final_content


# ─────────────────────────────────────────────────────────────
# CHẠY
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Parse
    markdown = parse_document(FILE_PATH)

    # Lưu file markdown
    base_name = Path(FILE_PATH).stem
    output_path = os.path.join(OUTPUT_DIR, f"{base_name}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"\n💾 Đã lưu: {output_path}")
    print(f"📊 Kích thước: {os.path.getsize(output_path) / 1024:.1f} KB")

    # In thử đầu file
    print("\n" + "="*60)
    print("📝 PREVIEW (300 ký tự đầu):")
    print("="*60)
    print(markdown[:300])
    print("...")
