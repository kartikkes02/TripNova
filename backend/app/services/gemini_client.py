from __future__ import annotations

import json
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import settings

GENERATION_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash-lite",
]

LIVE_SEARCH_SYNTHESIS_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

FALLBACK_MODELS = [
    "gemini-1.5-flash",
    "gemini-2.0-flash",
]


def _get_models(use_search: bool = False) -> list[str]:
    models = LIVE_SEARCH_SYNTHESIS_MODELS if use_search else GENERATION_MODELS
    final_models = []
    for m in models + FALLBACK_MODELS:
        if m not in final_models:
            final_models.append(m)
    return final_models


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


async def _generate_once(model: str, prompt: str) -> str:
    print(f"[GEMINI API] Generating with model: {model} | Prompt length: {len(prompt)}")
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in environment")

    clean_key = settings.GEMINI_API_KEY.strip().strip("'\"")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params: dict[str, str] = {}
    headers = {"Content-Type": "application/json"}

    if clean_key.startswith("AQ.") or clean_key.startswith("ya29."):
        # GCP / OAuth authorization bearer token
        headers["Authorization"] = f"Bearer {clean_key}"
    else:
        # Standard Google AI Studio API Key (AIzaSy...)
        params["key"] = clean_key
        headers["x-goog-api-key"] = clean_key

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.9,
            "maxOutputTokens": 4096,
        },
    }

    async with httpx.AsyncClient(timeout=35.0) as client:
        r = await client.post(url, headers=headers, params=params, json=payload)
        if r.status_code >= 400:
            err_text = r.text[:350]
            print(f"[GEMINI API] HTTP {r.status_code} on {model}: {err_text}")
            raise RuntimeError(f"Gemini {r.status_code} ({model}): {err_text}")
        data = r.json()

    return data["candidates"][0]["content"]["parts"][0]["text"]


async def generate_json(prompt: str) -> dict[str, Any]:
    # 1. Prefer Groq (fast, multi-model fallback, no 404s)
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
    for model in _get_models(use_search=False):
        try:
            text = await _generate_once(model, prompt)
            return _extract_json(text)
        except Exception as e:
            print(f"[GEMINI API] Model {model} failed: {type(e).__name__} - {str(e)}")
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
    for model in _get_models(use_search=use_search):
        try:
            text = await _generate_once(model, prompt)
            if not text:
                raise RuntimeError(f"Model {model} yielded no content.")
            return str(text).strip()
        except Exception as e:
            print(f"[GEMINI API] Model {model} failed: {type(e).__name__} - {str(e)}")
            last_err = e
            continue

    err_msg = "AI generation failed."
    if groq_error:
        err_msg += f" Groq error: {groq_error}."
    if last_err:
        err_msg += f" Gemini error: {last_err}."
    raise RuntimeError(err_msg)


async def _stream_generate_once(model: str, prompt: str):
    print(f"[GEMINI STREAM] Generating with model: {model} | Prompt length: {len(prompt)}")
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in environment")

    clean_key = settings.GEMINI_API_KEY.strip().strip("'\"")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    params: dict[str, str] = {}
    headers = {"Content-Type": "application/json"}

    if clean_key.startswith("AQ.") or clean_key.startswith("ya29."):
        headers["Authorization"] = f"Bearer {clean_key}"
    else:
        params["key"] = clean_key
        headers["x-goog-api-key"] = clean_key

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
                async with client.stream("POST", url, headers=headers, params=params, json=payload) as r:
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
    for model in _get_models(use_search=use_search):
        try:
            yielded_any = False
            async for chunk in _stream_generate_once(model, prompt):
                yielded_any = True
                yield chunk
            if not yielded_any:
                raise RuntimeError(f"Model {model} yielded no content.")
            return
        except Exception as e:
            print(f"[GEMINI STREAM] Model {model} failed: {type(e).__name__} - {str(e)}")
            last_err = e
            continue
    raise last_err or RuntimeError("Gemini streaming failed for all models")
