"""Service for generating Collaborative Mind Maps using Gemini AI."""

import json
import logging
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

MINDMAP_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "concept_central": {"type": "STRING"},
        "description_generale": {"type": "STRING"},
        "branches_suggerees": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "titre": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "questions_guidantes": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["titre", "description", "questions_guidantes"]
            }
        }
    },
    "required": ["concept_central", "branches_suggerees"]
}


async def generate_mindmap(
    module_title: str,
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_branches: int = 4,
    model: str | None = None,
) -> dict:
    """Generate starting structure for a collaborative Mind Map with AI using specified model."""
    prompt = f"""Tu es un expert en cartographie mentale (Mind Mapping) et en pédagogie active.
Génère une structure de Carte Mentale (Mind Map) collaborative basée sur le cours suivant :

- Titre du module : {module_title}
- Acquis d'apprentissage : {json.dumps(learning_outcomes, ensure_ascii=False)}
- Concepts clés : {json.dumps(key_concepts, ensure_ascii=False)}
- Mots-clés : {json.dumps(keywords, ensure_ascii=False)}

Règles de génération :
1. "concept_central": Identifie le concept pilier central unique qui réunit l'ensemble du module.
2. "description_generale": Explication synthétique de l'objectif de la carte mentale.
3. "branches_suggerees": Génère exactement {nb_branches} branches principales de départ.
   - Pour chaque branche : "titre" clair, une "description" succincte, et 2 à 3 "questions_guidantes" stimulantes pour inciter les étudiants à ajouter des sous-branches.

Réponds UNIQUEMENT en JSON valide conforme au schéma.
"""

    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 8192,
        "responseMimeType": "application/json",
        "responseSchema": MINDMAP_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    try:
        result = await _call_gemini_api(payload, timeout=120.0, requested_model=model)
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Error generating mindmap with Gemini: {e}")
        # Fallback response structure
        return {
            "concept_central": module_title,
            "description_generale": f"Carte mentale d'exploration pour {module_title}.",
            "branches_suggerees": [
                {
                    "titre": "Fondations & Principes",
                    "description": "Les notions fondamentales du module.",
                    "questions_guidantes": ["Quels sont les termes clés ?", "Quels principes de base applique-t-on ?"]
                },
                {
                    "titre": "Architecture & Méthodologie",
                    "description": "La structure globale et les choix méthodologiques.",
                    "questions_guidantes": ["Comment s'articulent les composants ?", "Quelles étapes suivre ?"]
                },
                {
                    "titre": "Cas d'usage & Applications",
                    "description": "Mise en pratique et scénarios réels.",
                    "questions_guidantes": ["Où s'applique ce concept ?", "Quels sont les pièges fréquents ?"]
                },
                {
                    "titre": "Évaluation & Bonnes Pratiques",
                    "description": "Critères de qualité et optimisation.",
                    "questions_guidantes": ["Comment mesurer l'efficacité ?", "Quelles règles respecter ?"]
                }
            ]
        }
