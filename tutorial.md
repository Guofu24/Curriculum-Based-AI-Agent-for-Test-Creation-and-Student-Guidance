# Hướng dẫn Tìm hiểu Dự án: ExamAI

Chào mừng bạn đến với **ExamAI** — hệ thống AI tiên tiến tự động sinh đề thi chuyên nghiệp từ giáo trình. Tài liệu này sẽ giải thích chi tiết các tính năng chính của hệ thống cũng như luồng hoạt động thông minh của Multi-Agent AI (được xây dựng dựa trên LangGraph).

---

## 1. Các Tính năng Chính của ExamAI

ExamAI là một nền tảng toàn diện tích hợp cả Backend (FastAPI) và thuật toán AI sinh văn bản, giúp giảng viên tạo bài kiểm tra nhanh chóng với độ chính xác cao.

### 📚 Quản lý Giáo trình (Textbooks)
- **Tải lên & Xử lý**: Hỗ trợ tải lên các tệp giáo trình định dạng PDF, DOCX, PPTX.
- **Trích xuất Thông minh**: Hệ thống tự động đọc, chia nhỏ (chunking) văn bản và xử lý dữ liệu.
- **Vector Database**: Mỗi đoạn văn bản được nhúng (embedding) và lưu trữ vào **Pinecone** cũng như cơ sở dữ liệu PostgreSQL để phục vụ quá trình tìm kiếm ngữ nghĩa cực kỳ chính xác.

### 📝 Sinh Đề thi Tự động
- **Tùy chỉnh Đa dạng**: Cho phép cấu hình loại đề (trắc nghiệm - MCQ, tự luận - Essay), độ khó, số lượng câu hỏi, và chọn cụ thể các chương sẽ được đưa vào bài thi.
- **Kiểm soát Chất lượng**: Tích hợp các ràng buộc nâng cao để loại bỏ hoàn toàn tình trạng AI bịa đặt (hallucination), đảm bảo 100% câu hỏi bám sát tài liệu gốc (Strict Grounding).
- **Phân bổ theo Bloom's Taxonomy**: Sinh câu hỏi cân bằng theo các mức độ nhận thức (Nhớ, Hiểu, Vận dụng, Phân tích, Đánh giá, Sáng tạo).

### 🔄 Chỉnh sửa Đề thi Phân đoạn (Partial Regeneration)
- Không ưng ý một vài câu hỏi? Người dùng không cần phải tạo lại toàn bộ đề. Hệ thống cho phép chọn cụ thể các câu hỏi cần sửa, nhập yêu cầu thay đổi (Ví dụ: "Làm câu này khó hơn"), và hệ thống sẽ tái tạo riêng những câu hỏi đó.

### 🔒 Bảo mật & Quản lý Tài khoản (Auth System)
- Đăng ký, đăng nhập an toàn với JWT access/refresh token.
- Mã hóa mật khẩu an toàn (Bcrypt).
- Quản lý xác thực email và phiên đăng nhập.

---

## 2. Luồng hoạt động của Multi-Agent (AI Pipeline)

ExamAI sở hữu một kiến trúc **Multi-Agent Pipeline** được thiết kế bằng **LangGraph**. Quy trình sinh câu hỏi không diễn ra một bước mà là sự phối hợp của nhiều Agents (tác tử) khác nhau, hoạt động giống như một hội đồng ra đề chuyên nghiệp.

### Các Agents trong Hệ thống:

1. **DocumentProcessorAgent (Người Xử lý Dữ liệu)**
   - Đọc, chia nhỏ văn bản từ các file tải lên. Đóng gói chúng vào Pinecone và DB.

2. **BlueprintAgent (Người Lập Kế hoạch)**
   - Nhận yêu cầu từ người dùng (loại đề, độ khó, phân bố câu hỏi).
   - Suy luận và lên **"Bản thiết kế" (ExamBlueprint)**, quyết định rõ từng câu hỏi sẽ thuộc mức độ nào, nằm ở chương nào trong sách.

3. **RetrievalAgent (Người Tìm kiếm Dữ liệu)**
   - Với mỗi suất câu hỏi (slot) trong bản thiết kế, agent này sử dụng **Hybrid Search** (kết hợp Pinecone Vector Search và BM25 Keyword Search).
   - Truy xuất ra 5 đoạn văn bản liên quan nhất từ giáo trình để làm nguồn thông tin căn cứ.

4. **QuestionGeneratorAgent (Người Viết Câu hỏi)**
   - Nhận dữ liệu trích xuất từ RetrievalAgent và vai trò thiết kế từ BlueprintAgent.
   - Bắt đầu dùng LLM để viết câu hỏi (MCQ hoặc Tự luận) bám sát 100% nguồn dữ liệu được cung cấp. Cung cấp cả giải thích và chỉ ra dữ liệu nguồn ở đâu.

5. **ValidatorAgent (Người Kiểm duyệt)**
   - Đóng vai trò như một người chấm thi độc lập (LLM-as-judge).
   - Chấm điểm từng câu hỏi trên 4 tiêu chí: Có bám sát ngữ cảnh không? Đáp án có chính xác không? Độ khó có phù hợp không? Có yếu tố bịa đặt nào không?
   - Tính toán điểm Chất lượng Tổng thể (Overall Quality).

### Cách thức Phối hợp (State Graph Flow)

Luồng hoạt động sẽ diễn ra trình tự qua từng tác tử:

1. **Chuẩn bị (parse_textbook_node)**: Load thông tin sách.
2. **Lên Kế hoạch (create_blueprint_node)**: `BlueprintAgent` lên khung đề thi.
3. **Truy xuất (retrieve_context_node)**: `RetrievalAgent` tìm dữ liệu tham khảo cho từng câu.
4. **Sinh Câu hỏi (generate_questions_node)**: `QuestionGeneratorAgent` viết nội dung.
5. **Kiểm duyệt (validate_questions_node)**: `ValidatorAgent` đánh giá chất lượng.
   - 🔄 **Retry Loop**: Nếu tỉ lệ câu hỏi đạt (pass) **dưới 60%**, hệ thống sẽ kích hoạt một vòng lặp (`mark_retry`) bắt `QuestionGeneratorAgent` sinh lại các câu bị lỗi (thực hiện tối đa 1 lần để tối ưu thời gian).
6. **Hoàn tất (finalize_node)**: Lưu toàn bộ cấu trúc xuống Database và trả đề thi hoàn chỉnh cho người dùng.

Với thiết kế chia nhỏ thành nhiều Agent, ExamAI không chỉ làm tăng chất lượng đầu ra mà còn đảm bảo dữ liệu luôn rõ ràng, có căn cứ giải thích mạnh mẽ.
