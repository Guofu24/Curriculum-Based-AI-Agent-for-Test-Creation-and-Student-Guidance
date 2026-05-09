"""Probe OpenAI-compatible chat output limits for the configured gateway.

Usage from repo root:
    python backend/scripts/check_wokushop_output_limit.py --role builder
    python backend/scripts/check_wokushop_output_limit.py --role outline --tokens 100,1000,4000
    python backend/scripts/check_wokushop_output_limit.py --role builder --include-max-completion-tokens

The script reads backend/.env by default and prints finish_reason, content length,
usage, plus a short prefix/suffix for each response. It never prints API keys.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


DEFAULT_PROMPT = """Return ONLY a valid JSON array with exactly 30 objects.
Each object must have these fields:
- "id": integer
- "question": one sentence
- "answer": one sentence
- "explanation": at least 45 words

Use plain English. Do not use markdown. Do not wrap the JSON in code fences.
The response should be long enough to clearly test output truncation."""


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def env_get(env_file_values: dict[str, str], key: str, default: str = "") -> str:
    return os.getenv(key) or env_file_values.get(key) or default


def parse_tokens(raw: str) -> list[int]:
    tokens: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            tokens.append(int(part))
    if not tokens:
        raise ValueError("At least one token value is required")
    return tokens


def build_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def resolve_model(env_file_values: dict[str, str], role: str, explicit_model: str | None) -> str:
    if explicit_model:
        return explicit_model

    role_key = f"{role.upper()}_MODEL"
    return (
        env_get(env_file_values, role_key)
        or env_get(env_file_values, "BUILDER_MODEL")
        or env_get(env_file_values, "OUTLINE_MODEL")
        or env_get(env_file_values, "GEMINI_MODEL")
    )


def resolve_api_key(env_file_values: dict[str, str], role: str, explicit_key: str | None) -> str:
    if explicit_key is not None:
        return explicit_key

    role_key = f"{role.upper()}_API_KEY"
    return env_get(env_file_values, role_key) or env_get(env_file_values, "OPENAI_API_KEY")


def make_payload(model: str, token_param: str, token_value: int, prompt: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a strict JSON generator. Return only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "stream": False,
        token_param: token_value,
    }


def summarize_response(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""

    return {
        "finish_reason": choice.get("finish_reason"),
        "content_len": len(content),
        "usage": data.get("usage"),
        "prefix": content[:240],
        "suffix": content[-240:],
    }


def call_once(
    client: httpx.Client,
    endpoint: str,
    api_key: str,
    model: str,
    token_param: str,
    token_value: int,
    prompt: str,
) -> None:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = make_payload(model, token_param, token_value, prompt)

    print("=" * 88)
    print(f"request | model={model} {token_param}={token_value}")

    response = client.post(endpoint, headers=headers, json=payload)
    print(f"http_status={response.status_code}")

    try:
        data = response.json()
    except json.JSONDecodeError:
        print("non_json_response:")
        print(response.text[:1200])
        return

    if response.status_code >= 400:
        print("error_response:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        return

    summary = summarize_response(data)
    print(f"finish_reason={summary['finish_reason']}")
    print(f"content_len={summary['content_len']}")
    print(f"usage={json.dumps(summary['usage'], ensure_ascii=False)}")
    print(f"prefix={summary['prefix']!r}")
    print(f"suffix={summary['suffix']!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--role", default="builder")
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--tokens", default="100,1000,4000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--include-max-completion-tokens",
        action="store_true",
        help="Also test max_completion_tokens in addition to max_tokens.",
    )
    args = parser.parse_args()

    env_file_values = load_env_file(Path(args.env_file))
    base_url = args.base_url or env_get(env_file_values, "BASE_URL", "https://llm.wokushop.com/v1")
    endpoint = build_endpoint(base_url)
    model = resolve_model(env_file_values, args.role, args.model)
    api_key = resolve_api_key(env_file_values, args.role, args.api_key)
    tokens = parse_tokens(args.tokens)

    if not model:
        raise SystemExit("No model resolved. Pass --model or set BUILDER_MODEL/OUTLINE_MODEL in .env.")

    print(f"endpoint={endpoint}")
    print(f"role={args.role}")
    print(f"model={model}")
    print(f"api_key_present={bool(api_key)}")
    print(f"tokens={tokens}")

    token_params = ["max_tokens"]
    if args.include_max_completion_tokens:
        token_params.append("max_completion_tokens")

    with httpx.Client(timeout=args.timeout) as client:
        for token_param in token_params:
            for token_value in tokens:
                call_once(
                    client=client,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    token_param=token_param,
                    token_value=token_value,
                    prompt=args.prompt,
                )


if __name__ == "__main__":
    main()
