"""Test the generate exam endpoint."""
import requests, json

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "agent@test.com", "password": "AgentTest123"}, timeout=10)
print("Login status:", r.status_code)
if r.status_code != 200:
    print("Login failed:", r.text[:200])
    exit(1)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# List documents
dr = requests.get(f"{BASE}/documents", headers=headers, timeout=10)
print("Docs status:", dr.status_code)
docs = dr.json()
print("Docs response type:", type(docs))
if isinstance(docs, dict):
    doc_list = docs.get("documents", [])
else:
    doc_list = docs
print("Docs count:", len(doc_list))

if not doc_list:
    print("No documents found!")
    exit(1)

doc = doc_list[0]
doc_id = doc["id"]
print("First doc:", doc_id, doc.get("original_filename"))

# Test generate
payload = {
    "document_id": doc_id,
    "chapters": [],
    "scope": [
        {
            "scope_id": "ch1",
            "section_type": "chapter",
            "title": "Chuong 1: Dao dong",
            "chapter_number": 1,
            "tags": ["tag1"],
        }
    ],
    "prompt": "Tao de kiem tra vat ly",
    "instructions": "",
    "total_questions": 10,
    "question_type": "mcq_single_answer",
    "exam_type": "mcq",
    "num_variants": 1,
    "gradually_increasing": False,
    "constraints": {
        "strict_grounding": True,
        "allow_applied_questions": False,
        "creativity_level": 0,
        "bloom_levels": ["remember", "understand", "apply", "analyze"],
    },
    "time_limit_minutes": 45,
    "output_language": "vi",
    "formatting_preferences": {"subject": "physics", "language": "vi"},
}

gr = requests.post(f"{BASE}/generate/exam", json=payload, headers=headers, timeout=30)
print("Generate status:", gr.status_code)
print("Generate body:", gr.text[:2000])
