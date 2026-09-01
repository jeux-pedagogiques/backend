"""Service for analyzing module sheets using AI APIs.

Provider chain (tried in order):
  1. Kimi K3 (Moonshot AI) — primary, OpenAI-compatible
  2. Gemini (Google) — fallback
"""

import asyncio
import json
import logging
import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Maximum number of retries per model for rate-limited (429) requests
MAX_RETRIES_PER_MODEL = 2
# Default wait in seconds when the server doesn't specify a retry delay
DEFAULT_RETRY_DELAY = 55.0

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"

BAI_BASE_URL = os.getenv("BAI_BASE_URL", "https://api.b.ai/v1")
BAI_DEFAULT_MODEL = os.getenv("BAI_MODEL", "glm-5.3-flash")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o"

KIMI_BASE_URL = "https://api.moonshot.ai/v1"
KIMI_MODEL = "kimi-k3"

# Verified working Gemini models for Google API
GEMINI_FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite"
]


# ── BAI helpers ────────────────────────────────────────────────


def _bai_headers() -> dict:
    api_key = os.getenv("BAI_API_KEY")
    if not api_key:
        return {}
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


def _gemini_to_bai_payload(payload: dict, target_model: str | None = None) -> dict:
    """Convert a Gemini-style payload to BAI (OpenAI-compatible) format."""
    contents = payload.get("contents", [])
    messages = []
    system_content = None

    for c in contents:
        role = c.get("role", "user")
        parts = c.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(text_parts)

        if role == "user" or not system_content:
            messages.append({"role": "user", "content": text})
        else:
            system_content = text

    generation_config = payload.get("generationConfig", {})
    requested_tokens = generation_config.get("maxOutputTokens", 8192)
    max_tokens = max(requested_tokens, 8192)
    temperature = generation_config.get("temperature", 0.3)
    model = target_model or os.getenv("BAI_MODEL", BAI_DEFAULT_MODEL)

    bai_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_content:
        bai_payload["messages"] = [
            {"role": "system", "content": system_content},
            *bai_payload["messages"],
        ]

    response_schema = generation_config.get("responseSchema")
    response_mime = generation_config.get("responseMimeType")
    if response_schema and response_mime == "application/json":
        bai_payload["response_format"] = {"type": "json_object"}
        schema_str = json.dumps(response_schema, ensure_ascii=False, indent=2)
        schema_instruction = f"\n\nIMPORTANT: Tu DOIS répondre strictement sous forme d'un objet JSON valide respectant ce schéma JSON :\n{schema_str}"
        if bai_payload["messages"]:
            bai_payload["messages"][-1]["content"] += schema_instruction

    return bai_payload


async def _try_bai(payload: dict, timeout: float, model: str | None = None) -> dict | None:
    """Try calling BAI API (https://api.b.ai/v1). Returns parsed JSON or None on failure."""
    headers = _bai_headers()
    if not headers:
        logger.info("BAI_API_KEY not configured, skipping BAI.")
        return None

    target_model = model or os.getenv("BAI_MODEL", BAI_DEFAULT_MODEL)
    bai_payload = _gemini_to_bai_payload(payload, target_model=target_model)
    url = f"{BAI_BASE_URL}/chat/completions"

    client_timeout = httpx.Timeout(timeout, connect=15.0)
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                response = await client.post(url, json=bai_payload, headers=headers)
        except Exception as e:
            logger.warning("BAI request failed (attempt %d/%d): %s", attempt, MAX_RETRIES_PER_MODEL, e)
            if attempt < MAX_RETRIES_PER_MODEL:
                await asyncio.sleep(1.0)
                continue
            return None

        if response.status_code in (400, 402, 403, 429):
            logger.warning("BAI status %d: %s. Skipping to fallback.", response.status_code, response.text[:150])
            return None
        elif response.status_code != 200:
            logger.warning("BAI returned %d: %s, falling back.", response.status_code, response.text[:200])
            return None

        try:
            data = response.json()
            choice = data["choices"][0]
            msg = choice.get("message", {})
            content = msg.get("content") or msg.get("reasoning_content") or ""
            return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("BAI unexpected response format: %s", e)
            return None

    return None


# ── Groq helpers ───────────────────────────────────────────────


def _groq_headers() -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {}
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


def _gemini_to_groq_payload(payload: dict, target_model: str | None = None) -> dict:
    """Convert a Gemini-style payload to Groq (OpenAI-compatible) format."""
    contents = payload.get("contents", [])
    messages = []
    system_content = None

    for c in contents:
        role = c.get("role", "user")
        parts = c.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(text_parts)

        if role == "user" or not system_content:
            messages.append({"role": "user", "content": text})
        else:
            system_content = text

    generation_config = payload.get("generationConfig", {})
    requested_tokens = generation_config.get("maxOutputTokens", 4000)
    max_tokens = min(requested_tokens, 4000)
    temperature = generation_config.get("temperature", 0.3)
    model = target_model or os.getenv("GROQ_MODEL", GROQ_DEFAULT_MODEL)

    groq_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_content:
        groq_payload["messages"] = [
            {"role": "system", "content": system_content},
            *groq_payload["messages"],
        ]

    response_schema = generation_config.get("responseSchema")
    response_mime = generation_config.get("responseMimeType")
    if response_schema and response_mime == "application/json":
        groq_payload["response_format"] = {"type": "json_object"}
        schema_str = json.dumps(response_schema, ensure_ascii=False, indent=2)
        schema_instruction = f"\n\nIMPORTANT: Tu DOIS répondre strictement sous forme d'un objet JSON valide respectant ce schéma JSON :\n{schema_str}"
        if groq_payload["messages"]:
            groq_payload["messages"][-1]["content"] += schema_instruction

    return groq_payload


async def _try_groq(payload: dict, timeout: float, model: str | None = None) -> dict | None:
    """Try calling Groq API. Returns parsed JSON or None on failure."""
    headers = _groq_headers()
    if not headers:
        logger.info("GROQ_API_KEY not configured, skipping Groq.")
        return None

    groq_payload = _gemini_to_groq_payload(payload, target_model=model)
    url = f"{GROQ_BASE_URL}/chat/completions"

    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=groq_payload, headers=headers)
        except Exception as e:
            logger.warning("Groq request failed (attempt %d/%d): %s", attempt, MAX_RETRIES_PER_MODEL, e)
            if attempt < MAX_RETRIES_PER_MODEL:
                await asyncio.sleep(1.0)
                continue
            return None

        if response.status_code in (400, 402, 429):
            logger.warning("Groq status %d: %s. Skipping to fallback.", response.status_code, response.text[:150])
            return None
        elif response.status_code != 200:
            logger.warning("Groq returned %d: %s, falling back.", response.status_code, response.text[:200])
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("Groq unexpected response format: %s", e)
            return None

    return None


# ── OpenRouter helpers ─────────────────────────────────────────


def _openrouter_headers() -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {}
    return {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://esprit-ai.local",
        "X-Title": "ESPRIT AI Platform",
        "Content-Type": "application/json"
    }


def _gemini_to_openrouter_payload(payload: dict, target_model: str | None = None) -> dict:
    """Convert a Gemini-style payload to OpenRouter (OpenAI-compatible) format."""
    contents = payload.get("contents", [])
    messages = []
    system_content = None

    for c in contents:
        role = c.get("role", "user")
        parts = c.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(text_parts)

        if role == "user" or not system_content:
            messages.append({"role": "user", "content": text})
        else:
            system_content = text

    generation_config = payload.get("generationConfig", {})
    requested_tokens = generation_config.get("maxOutputTokens", 4000)
    max_tokens = min(requested_tokens, 4000)
    temperature = generation_config.get("temperature", 0.3)
    model = target_model or os.getenv("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL)

    or_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_content:
        or_payload["messages"] = [
            {"role": "system", "content": system_content},
            *or_payload["messages"],
        ]

    response_schema = generation_config.get("responseSchema")
    response_mime = generation_config.get("responseMimeType")
    if response_schema and response_mime == "application/json":
        or_payload["response_format"] = {"type": "json_object"}
        schema_str = json.dumps(response_schema, ensure_ascii=False, indent=2)
        schema_instruction = f"\n\nIMPORTANT: Tu DOIS répondre strictement sous forme d'un objet JSON valide respectant ce schéma JSON :\n{schema_str}"
        if or_payload["messages"]:
            or_payload["messages"][-1]["content"] += schema_instruction

    return or_payload


async def _try_openrouter(payload: dict, timeout: float, model: str | None = None) -> dict | None:
    """Try calling OpenRouter. Returns parsed JSON or None on failure."""
    headers = _openrouter_headers()
    if not headers:
        logger.info("OPENROUTER_API_KEY not configured, skipping OpenRouter.")
        return None

    or_payload = _gemini_to_openrouter_payload(payload, target_model=model)
    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=or_payload, headers=headers)
        except Exception as e:
            logger.warning("OpenRouter request failed (attempt %d/%d): %s", attempt, MAX_RETRIES_PER_MODEL, e)
            if attempt < MAX_RETRIES_PER_MODEL:
                await asyncio.sleep(1.0)
                continue
            return None

        if response.status_code in (402, 429):
            logger.warning("OpenRouter status %d (credit/rate limit): %s. Skipping to fallback.", response.status_code, response.text[:150])
            return None
        elif response.status_code != 200:
            logger.warning("OpenRouter returned %d: %s, falling back.", response.status_code, response.text[:200])
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("OpenRouter unexpected response format: %s", e)
            return None

    return None


# ── Kimi (Moonshot) helpers ────────────────────────────────────


def _kimi_headers() -> dict:
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _gemini_to_kimi_payload(payload: dict) -> dict:
    """Convert a Gemini-style payload to Kimi (OpenAI-compatible) format."""
    # Extract the system message and user message from Gemini contents
    contents = payload.get("contents", [])
    messages = []
    system_content = None

    for c in contents:
        role = c.get("role", "user")
        parts = c.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(text_parts)

        if role == "user" or not system_content:
            messages.append({"role": "user", "content": text})
        else:
            # Treat first non-user as system
            system_content = text

    generation_config = payload.get("generationConfig", {})
    max_tokens = generation_config.get("maxOutputTokens", 16384)
    temperature = generation_config.get("temperature", 0.3)

    kimi_payload = {
        "model": KIMI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_content:
        kimi_payload["messages"] = [
            {"role": "system", "content": system_content},
            *kimi_payload["messages"],
        ]

    response_schema = generation_config.get("responseSchema")
    response_mime = generation_config.get("responseMimeType")
    if response_schema and response_mime == "application/json":
        kimi_payload["response_format"] = {"type": "json_object"}

    return kimi_payload


async def _try_kimi(payload: dict, timeout: float) -> dict | None:
    """Try calling Kimi K3. Returns parsed JSON or None on failure."""
    headers = _kimi_headers()
    if not headers:
        logger.info("MOONSHOT_API_KEY not configured, skipping Kimi.")
        return None

    kimi_payload = _gemini_to_kimi_payload(payload)
    url = f"{KIMI_BASE_URL}/chat/completions"

    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=kimi_payload, headers=headers)
        except Exception as e:
            logger.warning("Kimi request failed (attempt %d/%d): %s", attempt, MAX_RETRIES_PER_MODEL, e)
            if attempt < MAX_RETRIES_PER_MODEL:
                await asyncio.sleep(DEFAULT_RETRY_DELAY)
                continue
            return None

        if response.status_code == 429:
            if attempt < MAX_RETRIES_PER_MODEL:
                logger.warning("Kimi rate limited (429), retrying in %.1fs...", DEFAULT_RETRY_DELAY)
                await asyncio.sleep(DEFAULT_RETRY_DELAY)
                continue
            return None
        elif response.status_code in (404, 500, 502, 503):
            logger.warning("Kimi returned %d, falling back.", response.status_code)
            return None
        elif response.status_code != 200:
            logger.warning("Kimi returned %d: %s, falling back.", response.status_code, response.text[:200])
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("Kimi unexpected response format: %s", e)
            return None

    return None


# ── Gemini helpers ─────────────────────────────────────────────


def _gemini_api_url_for_model(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _adapt_thinking_config(generation_config: dict, model: str) -> dict:
    config = {k: v for k, v in generation_config.items() if k != "thinkingConfig"}
    model_lower = model.lower()
    if "3.5" in model_lower:
        config["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    elif "2.5" in model_lower:
        config["thinkingConfig"] = {"thinkingBudget": 0}
    return config


def _parse_retry_delay(response) -> float:
    try:
        err_body = response.json()
        details = err_body.get("error", {}).get("details", [])
        for detail in details:
            if detail.get("@type", "").endswith("RetryInfo"):
                delay_str = detail.get("retryDelay", "")
                match = re.search(r"([\d.]+)", delay_str)
                if match:
                    return float(match.group(1))
    except Exception:
        pass
    return DEFAULT_RETRY_DELAY


async def _try_gemini_model(api_key: str, model: str, payload: dict, timeout: float) -> dict | None:
    """Try calling a specific Gemini model with retry logic."""
    url = f"{_gemini_api_url_for_model(model)}?key={api_key}"

    adapted_payload = dict(payload)
    if "generationConfig" in adapted_payload:
        adapted_payload["generationConfig"] = _adapt_thinking_config(
            adapted_payload["generationConfig"], model
        )

    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=adapted_payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code == 429:
            retry_delay = _parse_retry_delay(response)
            if attempt < MAX_RETRIES_PER_MODEL:
                logger.warning(
                    "Gemini API rate limit hit (429) for model '%s'. "
                    "Attempt %d/%d. Retrying in %.1f seconds...",
                    model, attempt, MAX_RETRIES_PER_MODEL, retry_delay
                )
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.warning(
                    "Gemini API quota exhausted for model '%s' after %d attempts.",
                    model, MAX_RETRIES_PER_MODEL
                )
                return None
        elif response.status_code in (404, 500, 503):
            logger.warning(
                "Gemini model '%s' returned status %d. Skipping to next model.",
                model, response.status_code
            )
            return None
        elif response.status_code != 200:
            error_detail = response.text
            raise RuntimeError(f"Gemini API error ({response.status_code}): {error_detail}")
        else:
            return response.json()

    return None


async def _call_gemini_impl(payload: dict, timeout: float = 120.0) -> dict:
    """Call Gemini with model fallback (internal)."""
    api_key, primary_model, _ = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    models_to_try = [primary_model]
    for fb in GEMINI_FALLBACK_MODELS:
        if fb.lower() != primary_model.lower() and fb not in models_to_try:
            models_to_try.append(fb)

    for model in models_to_try:
        if model != primary_model:
            logger.info("Falling back to alternative Gemini model: %s", model)

        result = await _try_gemini_model(api_key, model, payload, timeout)
        if result is not None:
            if model != primary_model:
                logger.info("Successfully used fallback Gemini model: %s", model)
            return result

    raise RuntimeError(
        f"Quota Gemini API épuisée pour tous les modèles disponibles "
        f"({', '.join(models_to_try)}). "
        f"Limite du plan gratuit atteinte (20 requêtes/jour par modèle). "
        f"Veuillez réessayer plus tard ou passer à un plan payant."
    )


# ── Public entry point: Kimi → Gemini fallback ────────────────


GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
GITHUB_MODELS_DEFAULT_MODEL = "Llama-3.3-70B-Instruct"

def _github_models_headers() -> dict:
    api_key = os.getenv("GITHUB_MODELS_API_KEY")
    if not api_key:
        return {}
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

async def _try_github_models(payload: dict, timeout: float, model: str | None = None) -> dict | None:
    """Try calling GitHub Models API (Azure AI). Returns parsed JSON or None on failure."""
    headers = _github_models_headers()
    if not headers:
        logger.info("GITHUB_MODELS_API_KEY not configured, skipping GitHub Models.")
        return None

    target_model = model or GITHUB_MODELS_DEFAULT_MODEL
    gh_payload = _gemini_to_openrouter_payload(payload, target_model=target_model)
    url = f"{GITHUB_MODELS_BASE_URL}/chat/completions"

    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=gh_payload, headers=headers)
        except Exception as e:
            logger.warning("GitHub Models request failed (attempt %d/%d): %s", attempt, MAX_RETRIES_PER_MODEL, e)
            if attempt < MAX_RETRIES_PER_MODEL:
                await asyncio.sleep(1.0)
                continue
            return None

        if response.status_code in (400, 402, 429):
            logger.warning("GitHub Models status %d: %s. Skipping.", response.status_code, response.text[:150])
            return None
        elif response.status_code != 200:
            logger.warning("GitHub Models returned %d: %s.", response.status_code, response.text[:200])
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("GitHub Models unexpected response format: %s", e)
            return None

    return None


async def _call_gemini_api(payload: dict, timeout: float = 120.0, requested_model: str | None = None) -> dict:
    """Send a request directly to requested AI model or Google Gemini API with fallback models."""
    if requested_model and requested_model != "auto":
        req_clean = requested_model.strip()
        logger.info("User requested explicit AI model: %s", req_clean)

        if req_clean.startswith("bai/"):
            model_name = req_clean.split("bai/", 1)[1]
            res = await _try_bai(payload, timeout, model=model_name)
            if res is not None:
                logger.info("Successfully used explicit BAI model: %s", model_name)
                return res
        elif req_clean in ("glm-5.3-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "qwen3.8-flash", "mimo-v2.5", "hy3"):
            res = await _try_bai(payload, timeout, model=req_clean)
            if res is not None:
                logger.info("Successfully used explicit BAI model: %s", req_clean)
                return res
        elif req_clean.startswith("groq/"):
            model_name = req_clean.split("groq/", 1)[1]
            res = await _try_groq(payload, timeout, model=model_name)
            if res is not None:
                logger.info("Successfully used explicit Groq model: %s", model_name)
                return res
        elif req_clean.startswith("github/"):
            model_name = req_clean.split("github/", 1)[1]
            res = await _try_github_models(payload, timeout, model=model_name)
            if res is not None:
                logger.info("Successfully used explicit GitHub model: %s", model_name)
                return res
        elif req_clean.startswith("openrouter/"):
            model_name = req_clean.split("openrouter/", 1)[1]
            res = await _try_openrouter(payload, timeout, model=model_name)
            if res is not None:
                logger.info("Successfully used explicit OpenRouter model: %s", model_name)
                return res
        elif req_clean.startswith("gemini/"):
            model_id = req_clean.split("gemini/", 1)[1]
            api_key, _, _ = get_gemini_config()
            if api_key:
                res = await _try_gemini_model(api_key, model_id, payload, timeout)
                if res is not None:
                    logger.info("Successfully used explicit Gemini model: %s", model_id)
                    return res
        else:
            api_key, _, _ = get_gemini_config()
            if api_key:
                res = await _try_gemini_model(api_key, req_clean, payload, timeout)
                if res is not None:
                    logger.info("Successfully used requested Gemini model: %s", req_clean)
                    return res

    # 1. Primary AI Provider: Google Gemini
    logger.info("Executing AI request via Google Gemini API...")
    try:
        return await _call_gemini_impl(payload, timeout)
    except Exception as gem_err:
        logger.warning("Gemini API call failed (%s). Checking secondary fallbacks...", gem_err)

    # 2. Fallbacks if Gemini API is unreachable
    result = await _try_bai(payload, timeout)
    if result is not None:
        logger.info("Successfully used BAI fallback")
        return result

    result = await _try_groq(payload, timeout)
    if result is not None:
        logger.info("Successfully used Groq fallback")
        return result

    result = await _try_github_models(payload, timeout)
    if result is not None:
        logger.info("Successfully used GitHub Models fallback")
        return result

    result = await _try_openrouter(payload, timeout)
    if result is not None:
        logger.info("Successfully used OpenRouter fallback")
        return result

    raise RuntimeError("Toutes les requêtes d'IA (Google Gemini, BAI, Groq, OpenRouter) ont échoué.")

ANALYSIS_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "module_title": {"type": "STRING"},
        "learning_outcomes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "description": {"type": "STRING"},
                    "bloom_level": {"type": "STRING"},
                    "bloom_justification": {"type": "STRING"}
                },
                "required": ["id", "description", "bloom_level", "bloom_justification"]
            }
        },
        "key_concepts": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "keywords": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "central_notions": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "estimated_duration": {"type": "STRING"},
        "target_audience": {"type": "STRING"},
        "module_summary": {"type": "STRING"}
    },
    "required": ["module_title", "learning_outcomes", "key_concepts", "keywords", "central_notions", "module_summary"]
}

def get_gemini_config():
    """Retrieve the latest API key, model and url from environment."""
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    return api_key, model, url

def has_any_ai_key() -> bool:
    """Check if at least one AI provider API key is configured in environment."""
    load_dotenv(override=True)
    return bool(
        os.getenv("GEMINI_API_KEY") or
        os.getenv("BAI_API_KEY") or
        os.getenv("OPENROUTER_API_KEY") or
        os.getenv("GROQ_API_KEY") or
        os.getenv("GITHUB_MODELS_API_KEY")
    )

ANALYSIS_PROMPT = """Tu es un expert en ingénierie pédagogique. Analyse la fiche module suivante et extrais les informations demandées au format JSON strict.

**FICHE MODULE :**
---
{content}
---

**INSTRUCTIONS :**
Analyse le contenu ci-dessus et retourne un objet JSON avec EXACTEMENT cette structure (pas de texte avant ou après le JSON) :

{{
  "module_title": "Titre du module détecté dans la fiche",
  "learning_outcomes": [
    {{
      "id": 1,
      "description": "Description de l'acquis d'apprentissage",
      "bloom_level": "Un parmi: memoriser, comprendre, appliquer, analyser, evaluer, creer",
      "bloom_justification": "Courte justification du niveau Bloom choisi"
    }}
  ],
  "key_concepts": ["concept1", "concept2", "concept3"],
  "keywords": ["mot-clé1", "mot-clé2", "mot-clé3"],
  "central_notions": ["notion1", "notion2"],
  "estimated_duration": "Durée estimée si mentionnée dans le document, sinon null",
  "target_audience": "Public cible si mentionné dans le document, sinon null",
  "module_summary": "Un résumé concis du module en 2-3 phrases"
}}

**RÈGLES IMPORTANTES :**
1. Les niveaux Bloom possibles sont UNIQUEMENT : memoriser, comprendre, appliquer, analyser, evaluer, creer
2. Si aucun acquis d'apprentissage n'est explicitement formulé, déduis-les du contenu du module
3. Extrais au minimum 3 acquis d'apprentissage et au minimum 5 concepts clés
4. Pour la durée et le public cible, retourne null si l'information n'est pas présente
5. Retourne UNIQUEMENT le JSON, sans aucun texte, markdown ou backticks autour
"""


async def analyze_module_content(content: str, model: str | None = None) -> dict:
    """Send module content to Gemini API for AI analysis.

    Returns a structured dict with learning outcomes, Bloom levels,
    key concepts, duration and target audience.
    """
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    prompt = ANALYSIS_PROMPT.format(content=content)

    generation_config = {
        "temperature": 0.2,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": ANALYSIS_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": generation_config
    }

    result = await _call_gemini_api(payload, requested_model=model)

    # Extract the text content from Gemini response
    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response format: {e}")

    # Clean the response: remove markdown code fences if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Parse JSON
    try:
        analysis = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini response as JSON: {e}\nRaw response: {text}")

    # Validate required fields
    required_fields = ["learning_outcomes", "key_concepts", "keywords"]
    for field in required_fields:
        if field not in analysis:
            raise RuntimeError(f"Missing required field '{field}' in AI analysis response.")

    return analysis


VERIFICATION_PROMPT = """Tu es un expert en ingénierie pédagogique et en taxonomie de Bloom. Tu dois vérifier et valider de manière critique une analyse de fiche module qui a été générée.

**CONTENU ORIGINAL DE LA FICHE MODULE :**
---
{original_content}
---

**ANALYSE À VÉRIFIER :**
---
{gemini_analysis}
---

**TA MISSION :**
Vérifie minutieusement l'analyse ci-dessus en la comparant au contenu original. Évalue chaque élément et retourne un verdict structuré.

Retourne un objet JSON avec EXACTEMENT cette structure (pas de texte avant ou après le JSON) :

{{
  "verification_status": "approved" | "revised" | "rejected",
  "confidence_score": 85,
  "overall_comment": "Commentaire général sur la qualité de l'analyse",
  "learning_outcomes_review": [
    {{
      "original_id": 1,
      "is_valid": true,
      "bloom_level_correct": true,
      "suggested_bloom_level": null,
      "comment": "Commentaire sur cet acquis d'apprentissage"
    }}
  ],
  "key_concepts_review": {{
    "missing_concepts": ["concept manquant 1"],
    "irrelevant_concepts": ["concept non pertinent"],
    "comment": "Commentaire sur les concepts clés"
  }},
  "keywords_review": {{
    "missing_keywords": [],
    "irrelevant_keywords": [],
    "comment": "Commentaire sur les mots-clés"
  }},
  "summary_review": {{
    "is_accurate": true,
    "suggested_improvement": null,
    "comment": "Commentaire sur le résumé"
  }},
  "corrections": [
    {{
      "field": "nom du champ corrigé",
      "original_value": "valeur originale",
      "corrected_value": "valeur corrigée",
      "reason": "raison de la correction"
    }}
  ]
}}

**RÈGLES IMPORTANTES :**
1. "verification_status" doit être :
   - "approved" si l'analyse est globalement correcte (≥ 80% de confiance)
   - "revised" si des corrections mineures sont nécessaires (50-79% de confiance)
   - "rejected" si l'analyse contient des erreurs majeures (< 50% de confiance)
2. "confidence_score" est un pourcentage de 0 à 100 indiquant ta confiance dans l'analyse
3. Vérifie chaque niveau de Bloom avec rigueur — c'est le point le plus critique. Les niveaux Bloom possibles sont : memoriser, comprendre, appliquer, analyser, evaluer, creer
4. Si un concept ou mot-clé important est manquant, ajoute-le dans "missing_concepts" ou "missing_keywords"
5. Retourne UNIQUEMENT le JSON, sans aucun texte, markdown ou backticks autour
"""


async def verify_analysis_with_gemini(original_content: str, gemini_analysis: dict) -> dict:
    """Send Gemini's own analysis back to Gemini for self-verification and validation.

    Returns a structured verification report.
    """
    api_key, model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    prompt = VERIFICATION_PROMPT.format(
        original_content=original_content,
        gemini_analysis=json.dumps(gemini_analysis, ensure_ascii=False, indent=2)
    )

    generation_config = {
        "temperature": 0.1,  # Lower temperature for strict validation
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
    }

    # Configure thinking budget/level
    model_lower = model.lower()
    if "3.5" in model_lower:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": "MINIMAL"
        }
    elif "2.5" in model_lower:
        generation_config["thinkingConfig"] = {
            "thinkingBudget": 0
        }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": generation_config
    }

    result = await _call_gemini_api(payload)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini verification response format: {e}")

    # Clean the response
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        verification = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini verification response as JSON: {e}\nRaw response: {text}")

    required_fields = ["verification_status", "confidence_score"]
    for field in required_fields:
        if field not in verification:
            raise RuntimeError(f"Missing required field '{field}' in Gemini verification response.")

    return verification


SELF_CORRECTION_PROMPT = """Tu es un expert en ingénierie pédagogique et en taxonomie de Bloom. Ta tâche est de réviser, corriger et optimiser de manière critique une analyse préliminaire de fiche module en te basant sur le contenu original du document.

**CONTENU ORIGINAL DE LA FICHE MODULE :**
---
{original_content}
---

**ANALYSE PRÉLIMINAIRE À CORRIGER :**
---
{preliminary_analysis}
---

**TA MISSION :**
1. Analyse de manière critique les acquis d'apprentissage (AA). Vérifie la justesse de chaque niveau de la taxonomie de Bloom choisi et sa justification. Corrige tout niveau de Bloom incorrect.
2. Identifie s'il y a des concepts clés, notions centrales ou mots-clés importants manquants dans l'analyse préliminaire, et ajoute-les. Supprime ceux qui ne sont pas pertinents ou hors sujet.
3. Ajuste le titre, le résumé, le public cible et la durée s'ils peuvent être rendus plus fidèles au document d'origine.

Retourne l'analyse finale optimisée sous la forme d'un objet JSON strict avec EXACTEMENT la structure suivante :

{{
  "module_title": "Titre du module",
  "learning_outcomes": [
    {{
      "id": 1,
      "description": "Description de l'acquis d'apprentissage",
      "bloom_level": "memoriser | comprendre | appliquer | analyser | evaluer | creer",
      "bloom_justification": "Justification de la correction ou de la validation"
    }}
  ],
  "key_concepts": ["concept1", "concept2"],
  "keywords": ["mot-clé1", "mot-clé2"],
  "central_notions": ["notion1", "notion2"],
  "estimated_duration": "Durée ou null",
  "target_audience": "Public cible ou null",
  "module_summary": "Résumé final concis du module"
}}

**RÈGLES IMPORTANTES :**
1. Les niveaux Bloom possibles sont uniquement : memoriser, comprendre, appliquer, analyser, evaluer, creer
2. Extrais au minimum 3 acquis d'apprentissage et 5 concepts clés.
3. Retourne UNIQUEMENT le JSON, sans aucun texte explicatif avant ou après.
"""


async def analyze_and_correct_module(content: str, model: str | None = None) -> dict:
    """Analyze module content using specified or default AI model."""
    return await analyze_module_content(content, model=model)


QUIZ_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre_quiz": {"type": "STRING"},
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "aa_source": {"type": "STRING"},
                    "niveau_bloom": {"type": "INTEGER"},
                    "type": {"type": "STRING"},  # "qcm" | "vrai_faux" | "question_ouverte" | "association"
                    "enonce": {"type": "STRING"},
                    "options": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "bonne_reponse": {"type": "STRING"},
                    "explication": {"type": "STRING"},
                    "duree_secondes": {"type": "INTEGER"}
                },
                "required": ["id", "aa_source", "niveau_bloom", "type", "enonce", "bonne_reponse", "explication", "duree_secondes"]
            }
        },
        "fiche_animateur": {"type": "STRING"},
        "fiche_participant": {"type": "STRING"},
        "grille_debriefing": {
            "type": "OBJECT",
            "properties": {
                "criteres": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            },
            "required": ["criteres"]
        }
    },
    "required": ["titre_quiz", "questions", "fiche_animateur", "fiche_participant", "grille_debriefing"]
}

QUIZ_PROMPT_TEMPLATE = """Tu es un expert en ingénierie pédagogique et en ludification. Génère un quiz chronométré de haute qualité à partir des acquis d'apprentissage suivants :

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES DU QUIZ :**
- Nombre de questions : {nb_questions}
- Durée par question par défaut : {duree_par_question} secondes
- Mode de jeu : {mode} (ex: compétitif, collaboratif, formatif)
- Types de questions autorisés : {question_types}

**CONSIGNES STRICTES :**
1. Chaque question doit cibler un AA précis et respecter fidèlement son niveau Bloom (ex: ne pas générer de question de création/synthèse pour un AA limité à de la mémorisation).
2. Répartis les questions de manière équilibrée et proportionnelle entre tous les AA fournis.
3. Pour chaque question :
   - Le type de question doit faire partie de la liste autorisée.
   - Les options de réponse ne doivent être fournies que pour le type "qcm" et éventuellement "association". Pour "vrai_faux" ou "question_ouverte", retourne un tableau d'options vide [] ou null.
   - La bonne réponse doit être claire et précise.
   - Fournis une explication courte pour le débriefing immédiat après la question.
4. Fiche Animateur : Rédige des instructions de déroulement claires, des conseils pour l'animateur (comment débriefer, les points d'attention).
5. Fiche Participant : Rédige des règles simplifiées et engageantes pour les participants (comment gagner des points, comportement attendu).
6. Grille de Débriefing : Liste au moins 3 critères d'évaluation pour débriefer le groupe à la fin du quiz.

Retourne le quiz final sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""

async def generate_quiz_from_outcomes(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_questions: int,
    duree_par_question: int,
    mode: str,
    question_types: list[str],
    model: str | None = None
) -> dict:
    """Generate a timed quiz using Gemini from a list of learning outcomes and settings."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    # Format the outcomes nicely for the prompt
    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += f"- AA{lo.get('id', '')}: {lo.get('description', '')} (Niveau Bloom: {lo.get('bloom_level', '')})\n"

    # Build prompt
    prompt = QUIZ_PROMPT_TEMPLATE.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_questions=nb_questions,
        duree_par_question=duree_par_question,
        mode=mode,
        question_types=", ".join(question_types)
    )

    generation_config = {
        "temperature": 0.3,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": QUIZ_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": generation_config
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini quiz response format: {e}")

    # Clean response
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        quiz_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini quiz response as JSON: {e}\nRaw response: {text}")

    return quiz_data



