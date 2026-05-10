"""Check Gemini API model token limits and max_tokens acceptance.

Reads backend/.gemini_keys and backend/.env, never prints API keys.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_key() -> str:
    key_file = ROOT / ".gemini_keys"
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8-sig").splitlines():
            key = line.strip()
            if key:
                return key
    env = load_env(ROOT / ".env")
    raw = env.get("GEMINI_API_KEYS") or env.get("GEMINI_API_KEY") or ""
    return next((part.strip() for part in raw.split(",") if part.strip()), "")


def request_json(url: str, payload: dict | None = None) -> tuple[int, dict | str]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text[:1000]


def get_model(api_key: str, model: str) -> None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}?key={api_key}"
    status, data = request_json(url)
    print("=" * 88)
    print(f"metadata | model={model} status={status}")
    if isinstance(data, dict) and status < 400:
        keep = {
            "name": data.get("name"),
            "displayName": data.get("displayName"),
            "version": data.get("version"),
            "inputTokenLimit": data.get("inputTokenLimit"),
            "outputTokenLimit": data.get("outputTokenLimit"),
            "supportedGenerationMethods": data.get("supportedGenerationMethods"),
        }
        print(json.dumps(keep, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1600] if isinstance(data, dict) else data)


def generate_probe(api_key: str, model: str, output_tokens: int) -> None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Return exactly this text and nothing else: OK"}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": output_tokens,
        },
    }
    status, data = request_json(url, payload)
    print("=" * 88)
    print(f"generate | model={model} maxOutputTokens={output_tokens} status={status}")
    if isinstance(data, dict) and status < 400:
        usage = data.get("usageMetadata")
        finish = None
        text = ""
        try:
            cand = (data.get("candidates") or [{}])[0]
            finish = cand.get("finishReason")
            parts = cand.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
        except Exception:
            pass
        print(f"finishReason={finish}")
        print(f"text_len={len(text)}")
        print(f"usage={json.dumps(usage, ensure_ascii=False)}")
        print(f"text_prefix={text[:120]!r}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1800] if isinstance(data, dict) else data)


def openai_compat_probe(api_key: str, model: str, output_tokens: int) -> None:
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return exactly this text and nothing else: OK"}],
        "temperature": 0,
        "max_tokens": output_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text[:1000]

    print("=" * 88)
    print(f"openai_compat | model={model} max_tokens={output_tokens} status={status}")
    if isinstance(body, dict) and status < 400:
        choice = (body.get("choices") or [{}])[0]
        content = ((choice.get("message") or {}).get("content") or "")
        print(f"finish_reason={choice.get('finish_reason')}")
        print(f"content_len={len(content)}")
        print(f"usage={json.dumps(body.get('usage'), ensure_ascii=False)}")
        print(f"content_prefix={content[:160]!r}")
    else:
        print(json.dumps(body, ensure_ascii=False, indent=2)[:1800] if isinstance(body, dict) else body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="")
    parser.add_argument("--probe", default="5000,8000,16000")
    parser.add_argument("--openai-compat", action="store_true")
    args = parser.parse_args()

    api_key = load_key()
    if not api_key:
        raise SystemExit("No Gemini key found in backend/.gemini_keys or backend/.env")

    env = load_env(ROOT / ".env")
    raw_models = args.models or ",".join(
        m for m in [
            env.get("GEMINI_MODEL", ""),
            env.get("GEMINI_ALIGNMENT_MODEL", ""),
            env.get("LLM_MODEL_GEMINI", ""),
        ]
        if m
    )
    models = []
    for item in raw_models.split(","):
        model = item.strip()
        if model and model not in models:
            models.append(model)

    probes = [int(x.strip()) for x in args.probe.split(",") if x.strip()]
    print(f"api_key_present={bool(api_key)}")
    print(f"models={models}")
    print(f"probes={probes}")
    for model in models:
        get_model(api_key, model)
        for token_value in probes:
            if args.openai_compat:
                openai_compat_probe(api_key, model, token_value)
            else:
                generate_probe(api_key, model, token_value)


if __name__ == "__main__":
    main()
