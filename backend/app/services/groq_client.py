from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator

import httpx

from ..core.config import settings

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "deepseek-r1-distill-llama-70b",
    "gemma2-9b-it",
]


def _get_clean_key() -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured in environment")
    return settings.GROQ_API_KEY.strip().strip("'\"")


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, flags=re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(stripped[first_brace : last_brace + 1])
        except Exception:
            pass

    return json.loads(stripped)


async def _generate_once(model: str, prompt: str, json_mode: bool = False) -> str:
    clean_key = _get_clean_key()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3 if json_mode else 0.7,
        "max_tokens": 4096,
        "top_p": 0.9,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, headers=headers, json=payload)

        # If strict json_object rejected with 400, retry once without response_format
        if r.status_code == 400 and json_mode:
            print(f"[GROQ API] Retrying {model} without response_format due to 400: {r.text[:200]}")
            payload.pop("response_format", None)
            r = await client.post(url, headers=headers, json=payload)

        if r.status_code >= 400:
            err_body = r.text[:350]
            print(f"[GROQ API] HTTP {r.status_code} on {model}: {err_body}")
            raise RuntimeError(f"Groq {r.status_code} ({model}): {err_body}")

        data = r.json()

    return data["choices"][0]["message"]["content"]


async def generate_json(prompt: str) -> dict[str, Any]:
    errors = []
    for model in GROQ_MODELS:
        try:
            print(f"[GROQ] Generating JSON with model: {model}...")
            text = await _generate_once(model, prompt, json_mode=True)
            parsed = _extract_json(text)
            if parsed and isinstance(parsed, dict):
                print(f"[GROQ] Successfully generated JSON with {model}")
                return parsed
        except Exception as e:
            print(f"[GROQ] Model {model} failed: {e}")
            errors.append(f"{model}: {e}")
            continue

    raise RuntimeError(f"All Groq models failed for JSON: {'; '.join(errors)}")


async def generate_text(prompt: str) -> str:
    errors = []
    for model in GROQ_MODELS:
        try:
            print(f"[GROQ] Generating text with model: {model}...")
            text = await _generate_once(model, prompt, json_mode=False)
            if text:
                return str(text).strip()
        except Exception as e:
            print(f"[GROQ] Model {model} failed: {e}")
            errors.append(f"{model}: {e}")
            continue

    raise RuntimeError(f"All Groq models failed for text: {'; '.join(errors)}")


async def _stream_generate_once(model: str, prompt: str) -> AsyncGenerator[str, None]:
    clean_key = _get_clean_key()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.9,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code >= 400:
                err_body = (await r.aread()).decode(errors="ignore")[:350]
                raise RuntimeError(f"Groq stream {r.status_code} ({model}): {err_body}")

            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except Exception:
                        pass


async def async_stream_text(prompt: str) -> AsyncGenerator[str, None]:
    errors = []
    for model in GROQ_MODELS:
        try:
            yielded_any = False
            async for chunk in _stream_generate_once(model, prompt):
                yielded_any = True
                yield chunk
            if yielded_any:
                return
        except Exception as e:
            print(f"[GROQ STREAM] Model {model} failed: {e}")
            errors.append(f"{model}: {e}")
            continue

    raise RuntimeError(f"All Groq streaming models failed: {'; '.join(errors)}")
