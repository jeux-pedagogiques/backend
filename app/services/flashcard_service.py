"""Service for generating flashcards using Gemini AI."""

import json
import logging
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

FLASHCARD_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre": {"type": "STRING"},
        "cartes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "recto": {"type": "STRING"},
                    "verso": {"type": "STRING"},
                    "aa_source": {"type": "STRING"},
                    "niveau_bloom": {"type": "STRING"}
                },
                "required": ["id", "recto", "verso", "aa_source", "niveau_bloom"]
            }
        }
    },
    "required": ["titre", "cartes"]
}

FLASHCARD_PROMPT = """Tu es un expert en ingénierie pédagogique et en révision espacée. Génère un jeu de flashcards pédagogiques à partir des acquis d'apprentissage suivants.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre de cartes : {nb_cartes}

**CONSIGNES :**
1. Chaque carte a un recto (terme, concept ou question) et un verso (définition, explication ou réponse)
2. Chaque carte doit être liée à un AA précis et à son niveau Bloom
3. Répartis les cartes de manière équilibrée entre tous les AA fournis
4. Le recto doit être court et ciblé (un concept, un terme, une question)
5. Le verso doit être une explication claire et complète mais concise
6. Varie les formats : certaines cartes sont terme→définition, d'autres question→réponse
7. N'utilise QUE les concepts et termes explicitement présents dans les acquis d'apprentissage et le contenu fourni. Ne complète jamais avec des notions qui n'apparaissent pas dans le texte source
8. Le titre doit être descriptif du contenu pédagogique (ex: "Flashcards - Sécurité Réseau")

Retourne les flashcards sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""


async def generate_flashcards(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_cartes: int = 20,
    model: str | None = None,
) -> dict:
    """Generate flashcards using specified or default AI model."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += (
            f"- AA{lo.get('id', '')}: {lo.get('description', '')} "
            f"(Niveau Bloom: {lo.get('bloom_level', '')})\n"
        )

    prompt = FLASHCARD_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_cartes=nb_cartes,
    )

    generation_config = {
        "temperature": 0.3,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": FLASHCARD_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini flashcard response format: {e}")

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        flashcard_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini flashcard response as JSON: {e}\nRaw response: {text}")

    return flashcard_data
