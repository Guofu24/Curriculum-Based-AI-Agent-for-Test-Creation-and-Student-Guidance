"""Test the generate exam endpoint with real document."""
import requests, json

BASE = "http://localhost:8000/api/v1"

# Login with user that has documents (same as frontend)
login_r = requests.post(f"{BASE}/auth/login", json={
    "email": "gen_test_03@test.com",
    "password": "GenTestPass123!"
}, timeout=10)
print("Login status:", login_r.status_code)
token = login_r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Get documents
dr = requests.get(f"{BASE}/documents", headers=headers, timeout=10)
docs_data = dr.json()
doc_list = docs_data.get("documents", []) if isinstance(docs_data, dict) else docs_data
print("Documents found:", len(doc_list))
for d in doc_list:
    print(f"  - {d['id']}: {d.get('original_filename')} status={d.get('processing_status')}")

if not doc_list:
    print("No documents - uploading one")
    import io
    pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n217\n%%EOF"
    files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
    ur = requests.post(f"{BASE}/documents/upload", files=files, data={"title": "Test", "language": "vi"}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    print("Upload:", ur.status_code, ur.text[:200])
    doc_list = []
    dr = requests.get(f"{BASE}/documents", headers=headers, timeout=10)
    docs_data = dr.json()
    doc_list = docs_data.get("documents", []) if isinstance(docs_data, dict) else docs_data

if doc_list:
    doc_id = doc_list[0]["id"]
    print(f"\nTesting with doc: {doc_id}")

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
    print(f"Generate status: {gr.status_code}")
    print(f"Generate body: {gr.text[:2000]}")
else:
    print("ERROR: No documents")
