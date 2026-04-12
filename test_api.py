"""Test marker API từ máy local."""
import requests

BASE_URL = "https://0776-34-172-86-160.ngrok-free.app"

# 1. Health check
r = requests.get(f"{BASE_URL}/health", timeout=10)
print("Health:", r.json())

# 2. Parse PDF
pdf_path = "test.pdf"  # ← Đổi thành file PDF thật của bạn
with open(pdf_path, "rb") as f:
    files = {"file": ("test.pdf", f, "application/pdf")}
    r = requests.post(f"{BASE_URL}/parse-pdf?chunk=true", files=files, timeout=120)

resp = r.json()
print(f"\nSuccess: {resp.get('success')}")
print(f"Pages: {resp.get('page_count')}")
print(f"Chars: {resp.get('char_count')}")
print(f"Images: {len(resp.get('images', []))}")
print(f"Tables: {len(resp.get('tables', []))}")
print(f"Chunks: {len(resp.get('chunks', []))}")
print(f"\nFirst chunk:\n{resp['chunks'][0]['text'][:300]}..." if resp.get('chunks') else "No chunks")
