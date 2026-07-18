"""Service for analyzing module sheets using the Gemini AI API."""

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

# Fallback models to try when the primary model's quota is exhausted or unavailable.
# Free-tier quota is PER-MODEL (20 req/day each), so switching models
# gives us access to a fresh quota bucket.
FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.0-flash"]


def _get_api_url_for_model(model: str) -> str:
    """Build the Gemini API URL for a specific model."""
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _adapt_thinking_config(generation_config: dict, model: str) -> dict:
    """Adjust thinkingConfig for the target model since different model
    families use different thinking parameters."""
    config = {k: v for k, v in generation_config.items() if k != "thinkingConfig"}
    model_lower = model.lower()
    if "3.5" in model_lower:
        config["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    elif "2.5" in model_lower:
        config["thinkingConfig"] = {"thinkingBudget": 0}
    # gemini-2.0 and earlier don't support thinkingConfig at all
    return config


def _parse_retry_delay(response) -> float:
    """Extract the server-suggested retry delay from a 429 response."""
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


async def _try_model(api_key: str, model: str, payload: dict, timeout: float) -> dict:
    """Try calling a specific Gemini model with retry logic.

    Returns the parsed JSON response on success.
    Raises RuntimeError on other fatal errors.
    Returns None if the model is rate-limited, deprecated, or experiencing high demand
    to allow the caller to try a fallback model.
    """
    url = f"{_get_api_url_for_model(model)}?key={api_key}"

    # Adapt the thinkingConfig in the payload for this model
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
                # All retries exhausted for this model
                logger.warning(
                    "Gemini API quota exhausted for model '%s' after %d attempts.",
                    model, MAX_RETRIES_PER_MODEL
                )
                return None
        elif response.status_code in (404, 500, 503):
            # Model not found/deprecated (404) or server error/overloaded (500/503)
            # Skip and try next fallback
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


async def _call_gemini_api(payload: dict, timeout: float = 120.0) -> dict:
    """Send a request to the Gemini API with automatic retry and model fallback.

    When the primary model's free-tier quota (20 req/day) is exhausted,
    automatically falls back to alternative models that have their own
    separate quota buckets.
    """
    api_key, primary_model, _ = get_gemini_config()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

    # Build list of models to try: primary first, then fallbacks
    models_to_try = [primary_model]
    for fb in FALLBACK_MODELS:
        if fb.lower() != primary_model.lower() and fb not in models_to_try:
            models_to_try.append(fb)

    for model in models_to_try:
        if model != primary_model:
            logger.info("Falling back to alternative model: %s", model)

        result = await _try_model(api_key, model, payload, timeout)
        if result is not None:
            if model != primary_model:
                logger.info("Successfully used fallback model: %s", model)
            return result

    # All models exhausted
    raise RuntimeError(
        f"Quota Gemini API épuisée pour tous les modèles disponibles "
        f"({', '.join(models_to_try)}). "
        f"Limite du plan gratuit atteinte (20 requêtes/jour par modèle). "
        f"Veuillez réessayer plus tard ou passer à un plan payant."
    )

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


async def analyze_module_content(content: str) -> dict:
    """Send module content to Gemini API for AI analysis.

    Returns a structured dict with learning outcomes, Bloom levels,
    key concepts, duration and target audience.
    """
    api_key, model, api_url = get_gemini_config()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

    prompt = ANALYSIS_PROMPT.format(content=content)

    generation_config = {
        "temperature": 0.2,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": ANALYSIS_RESPONSE_SCHEMA,
    }

    # Configure thinking budget/level for models that support/require it
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
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

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


async def analyze_and_correct_module(content: str) -> dict:
    """Analyze module content using Gemini. 
    
    Optimized to use a single API call to conserve free-tier quota.
    """
    return await analyze_module_content(content)


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
    question_types: list[str]
) -> dict:
    """Generate a timed quiz using Gemini from a list of learning outcomes and settings."""
    api_key, model, api_url = get_gemini_config()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

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

    # Configure thinking budget
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

    result = await _call_gemini_api(payload, timeout=180.0)

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



