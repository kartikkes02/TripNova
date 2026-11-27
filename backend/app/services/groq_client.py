from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator

import httpx

from ..core.config import settings

FALLBACK_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
]


def _get_clean_key() -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured in environment")
    return settings.GROQ_API_KEY.strip().strip("'\"")


async def _get_groq_models(clean_key: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {clean_key}"},
            )
            if r.status_code == 200:
                data = r.json()
                excluded = ["whisper", "guard", "orpheus", "tts", "audio", "voice"]
                active = [
                    m["id"]
                    for m in data.get("data", [])
                    if not any(ex in m.get("id", "").lower() for ex in excluded)
                ]
                preferred_order = [
                    "qwen/qwen3.8-27b",
                    "allam-2-7b",
                    "openai/gpt-oss-120b",
                    "openai/gpt-oss-20b",
                    "llama-3.3-70b-versatile",
                ]
                sorted_models = [m for m in preferred_order if m in active] + [
                    m for m in active if m not in preferred_order
                ]
                if sorted_models:
                    print(f"[GROQ API] Discovered & prioritized active text models: {sorted_models}")
                    return sorted_models
    except Exception as e:
        print(f"[GROQ API] Dynamic model discovery failed: {e}")

    return FALLBACK_GROQ_MODELS


def _extract_json(text: str) -> dict[str, Any]:
    # Strip Qwen/DeepSeek <think>...</think> blocks before parsing JSON
    stripped = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
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
        "max_tokens": 8192 if json_mode else 4096,
        "top_p": 0.9,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)

        # If max_tokens=8192 or strict json_object rejected with 400, retry with safer settings
        if r.status_code == 400:
            err_lower = r.text.lower()
            retried = False
            if "max_tokens" in err_lower or "max_completion_tokens" in err_lower:
                payload["max_tokens"] = 4096
                retried = True
            if json_mode:
                print(f"[GROQ API] Retrying {model} without response_format due to 400: {r.text[:200]}")
                payload.pop("response_format", None)
                retried = True
            if retried:
                r = await client.post(url, headers=headers, json=payload)

        if r.status_code >= 400:
            err_body = r.text[:350]
            print(f"[GROQ API] HTTP {r.status_code} on {model}: {err_body}")
            raise RuntimeError(f"Groq {r.status_code} ({model}): {err_body}")

        data = r.json()

    return data["choices"][0]["message"]["content"]


async def generate_json(prompt: str) -> dict[str, Any]:
    clean_key = _get_clean_key()
    models = await _get_groq_models(clean_key)
    errors = []

    for model in models:
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
    clean_key = _get_clean_key()
    models = await _get_groq_models(clean_key)
    errors = []

    for model in models:
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
    clean_key = _get_clean_key()
    models = await _get_groq_models(clean_key)
    errors = []

    for model in models:
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
