from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..core.config import settings

GENERATION_MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
]


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


async def _call_interactions_api(clean_key: str, model: str, prompt: str) -> str:
    url = "https://generativelanguage.googleapis.com/v1beta/interactions"
    headers = {
        "x-goog-api-key": clean_key,
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": prompt,
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            err_text = r.text[:350]
            raise RuntimeError(f"Interactions API {r.status_code} ({model}): {err_text}")
        data = r.json()

    # Extract text from steps (model_output)
    for step in data.get("steps", []):
        if step.get("type") == "model_output":
            for part in step.get("content", []):
                if part.get("type") == "text" and part.get("text"):
                    return part["text"]

    # Extract text from outputs array if present
    for out in data.get("outputs", []):
        if isinstance(out, dict) and out.get("text"):
            return out["text"]
        elif isinstance(out, str) and out:
            return out

    raise RuntimeError(f"Interactions API returned no text output for {model}")


async def _call_generate_content_api(clean_key: str, model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": clean_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.9,
            "maxOutputTokens": 4096,
        },
    }

    async with httpx.AsyncClient(timeout=35.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            err_text = r.text[:350]
            raise RuntimeError(f"generateContent API {r.status_code} ({model}): {err_text}")
        data = r.json()

    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _generate_once(model: str, prompt: str) -> str:
    print(f"[GEMINI API] Generating with model: {model} | Prompt length: {len(prompt)}")
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in environment")

    clean_key = settings.GEMINI_API_KEY.strip().strip("'\"")

    # 1. Try Google's recommended Interactions API first
    try:
        print(f"[GEMINI API] Trying Interactions API for {model}...")
        return await _call_interactions_api(clean_key, model, prompt)
    except Exception as ie:
        print(f"[GEMINI API] Interactions API attempt failed: {ie}. Trying generateContent API...")

    # 2. Fallback to generateContent API
    return await _call_generate_content_api(clean_key, model, prompt)


async def generate_json(prompt: str) -> dict[str, Any]:
    # 1. Prefer Groq if available
    groq_error: str | None = None
    if settings.GROQ_API_KEY:
        try:
            from . import groq_client
            print("[AI ENGINE] Attempting itinerary generation via Groq...")
            return await groq_client.generate_json(prompt)
        except Exception as ge:
            groq_error = str(ge)
            print(f"[AI ENGINE] Groq failed: {groq_error}. Falling back to Gemini...")

    # 2. Fallback to Gemini
    gemini_errors = []
    for model in GENERATION_MODELS:
        try:
            text = await _generate_once(model, prompt)
            parsed = _extract_json(text)
            if parsed and isinstance(parsed, dict):
                print(f"[GEMINI API] Successfully generated plan with model {model}")
                return parsed
        except Exception as e:
            print(f"[GEMINI API] Model {model} failed: {e}")
            gemini_errors.append(f"{model}: {e}")
            continue

    err_msg = "AI generation failed."
    if groq_error:
        err_msg += f" Groq error: {groq_error}."
    if gemini_errors:
        err_msg += f" Gemini error: {'; '.join(gemini_errors)}."
    raise RuntimeError(err_msg)


async def generate_text(prompt: str, use_search: bool = False) -> str:
    # 1. Prefer Groq if available
    groq_error: str | None = None
    if settings.GROQ_API_KEY:
        try:
            from . import groq_client
            print("[AI ENGINE] Attempting text generation via Groq...")
            return await groq_client.generate_text(prompt)
        except Exception as ge:
            groq_error = str(ge)
            print(f"[AI ENGINE] Groq failed: {ge}. Falling back to Gemini...")

    # 2. Fallback to Gemini
    last_err: Exception | None = None
    for model in GENERATION_MODELS:
        try:
            text = await _generate_once(model, prompt)
            if text:
                return str(text).strip()
        except Exception as e:
            print(f"[GEMINI API] Model {model} failed: {e}")
            last_err = e
            continue

    err_msg = "AI generation failed."
    if groq_error:
        err_msg += f" Groq error: {groq_error}."
    if last_err:
        err_msg += f" Gemini error: {last_err}."
    raise RuntimeError(err_msg)


async def _stream_generate_once(model: str, prompt: str):
    clean_key = settings.GEMINI_API_KEY.strip().strip("'\"")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    headers = {
        "x-goog-api-key": clean_key,
        "Content-Type": "application/json",
    }

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.9,
            "maxOutputTokens": 2048,
        },
    }

    import asyncio
    max_retries = 2
    base_delay = 2

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(max_retries):
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as r:
                    if r.status_code >= 400:
                        err_text = (await r.aread()).decode(errors="ignore")[:300]
                        if r.status_code == 429 and attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            print(f"Gemini API 429 Rate limit - Retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        raise RuntimeError(f"Gemini stream {r.status_code} ({model}): {err_text}")

                    async for line in r.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                continue
                            try:
                                data = json.loads(data_str)
                                if "candidates" in data and len(data["candidates"]) > 0:
                                    content = data["candidates"][0].get("content", {})
                                    parts = content.get("parts", [])
                                    if parts:
                                        yield parts[0].get("text", "")
                            except Exception as e:
                                print(f"Error parsing SSE chunk: {e}")

                    return
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise


async def async_stream_text(prompt: str, use_search: bool = False):
    last_err: Exception | None = None
    for model in GENERATION_MODELS:
        try:
            yielded_any = False
            async for chunk in _stream_generate_once(model, prompt):
                yielded_any = True
                yield chunk
            if not yielded_any:
                raise RuntimeError(f"Model {model} yielded no content.")
            return
        except Exception as e:
            print(f"[GEMINI STREAM] Model {model} failed: {e}")
            last_err = e
            continue
    raise last_err or RuntimeError("Gemini streaming failed for all models")
