"""Test the generate exam endpoint end-to-end."""
import requests, json, io

BASE = "http://localhost:8000/api/v1"

# Register a new user
reg = requests.post(f"{BASE}/auth/register", json={
    "email": "gen_test_03@test.com",
    "password": "GenTestPass123!",
    "full_name": "Generation Test User"
}, timeout=10)
print("Register status:", reg.status_code, reg.text[:200])

# Login
login_r = requests.post(f"{BASE}/auth/login", json={
    "email": "gen_test_03@test.com",
    "password": "GenTestPass123!"
}, timeout=10)
print("Login status:", login_r.status_code)
if login_r.status_code != 200:
    print("Login failed:", login_r.text[:300])
    exit(1)

resp_json = login_r.json()
print("Login response keys:", list(resp_json.keys()))
token = resp_json["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Upload a minimal PDF
pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n217\n%%EOF"
files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
ur = requests.post(
    f"{BASE}/documents/upload",
    files=files,
    data={"title": "Test Document", "language": "vi"},
    headers={"Authorization": f"Bearer {token}"},
    timeout=30
)
print("Upload status:", ur.status_code, ur.text[:400])

# Test generate - use dummy doc_id
payload = {
    "document_id": "00000000-0000-0000-0000-000000000000",
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
