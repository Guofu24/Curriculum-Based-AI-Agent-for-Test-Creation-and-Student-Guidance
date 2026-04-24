"""Pytest configuration and fixtures for graph tests."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def base_state():
    """Minimal valid initial state for the graph."""
    return {
        "exam_id": "exam-test-001",
        "user_id": "user-test-001",
        "document_id": "doc-test-001",
        "exam_config": {
            "scope": ["Chương 1", "Chương 2"],
            "mcq_count": 10,
            "essay_count": 2,
            "bloom_distribution": {
                "nhan_biet": 20,
                "thong_hieu": 30,
                "van_dung": 30,
                "van_dung_cao": 20,
            },
            "user_prompt": "Tạo đề kiểm tra Vật lý lớp 10",
            "extra_instructions": "Ưu tiên câu hỏi thực tế",
        },
        "user_prompt": "Tạo đề kiểm tra Vật lý lớp 10",
        "extra_instructions": "Ưu tiên câu hỏi thực tế",
    }


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=None)
    redis.client = AsyncMock()
    redis.client.incr = AsyncMock(return_value=1)
    redis.publish = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=AsyncMock())
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_stream_callback():
    """Mock WebSocket stream callback."""
    events = []

    async def callback(event: dict):
        events.append(event)

    callback.events = events
    return callback


@pytest.fixture
def sample_blueprint():
    """Sample blueprint from OutlineAgent."""
    return [
        {"question_id": "MCQ_001", "type": "mcq", "bloom_level": "nhan_biet", "chapter": "Chương 1"},
        {"question_id": "MCQ_002", "type": "mcq", "bloom_level": "van_dung", "chapter": "Chương 1"},
        {"question_id": "MCQ_003", "type": "mcq", "bloom_level": "thong_hieu", "chapter": "Chương 2"},
        {"question_id": "ESSAY_001", "type": "essay", "bloom_level": "van_dung_cao", "chapter": "Chương 2"},
    ]


@pytest.fixture
def sample_questions():
    """Sample questions from BuilderAgent."""
    return [
        {
            "question_id": "MCQ_001",
            "type": "mcq",
            "stem": "Định luật Newton thứ 2 được phát biểu là:",
            "options": {"A": "F = ma", "B": "F = mv", "C": "F = m/a", "D": "F = m+v"},
            "correct_answer": "A",
            "bloom_level": "nhan_biet",
            "chapter": "Chương 1",
        },
        {
            "question_id": "MCQ_002",
            "type": "mcq",
            "stem": "Một vật có khối lượng 2kg chịu gia tốc 3 m/s². Tính lực.",
            "options": {"A": "6N", "B": "5N", "C": "3N", "D": "1.5N"},
            "correct_answer": "A",
            "bloom_level": "van_dung",
            "chapter": "Chương 1",
        },
        {
            "question_id": "ESSAY_001",
            "type": "essay",
            "stem": "Phân tích và giải thích định luật bảo toàn năng lượng trong rơi tự do.",
            "rubric": [{"score": 10, "description": "Hoàn toàn chính xác"}],
            "bloom_level": "van_dung_cao",
            "chapter": "Chương 2",
        },
    ]
