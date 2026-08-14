"""Service for generating pedagogical escape rooms using Gemini AI."""

import json
import logging
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

ESCAPE_ROOM_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre_escape_room": {"type": "STRING"},
        "scenario_intro": {"type": "STRING"},
        "enigmes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "ordre": {"type": "INTEGER"},
                    "aa_source": {"type": "STRING"},
                    "niveau_bloom": {"type": "INTEGER"},
                    "enonce": {"type": "STRING"},
                    "type_enigme": {"type": "STRING"},
                    "solution": {"type": "STRING"},
                    "indice_optionnel": {"type": "STRING"},
                    "penalite_indice": {"type": "INTEGER"},
                    "code_deverrouillage_suivant": {"type": "STRING"}
                },
                "required": ["id", "ordre", "aa_source", "niveau_bloom", "enonce", "type_enigme", "solution", "indice_optionnel", "penalite_indice", "code_deverrouillage_suivant"]
            }
        },
        "resolution_finale": {"type": "STRING"},
        "duree_estimee_minutes": {"type": "INTEGER"},
        "fiche_animateur": {"type": "STRING"},
        "fiche_participant": {"type": "STRING"},
        "grille_evaluation": {
            "type": "OBJECT",
            "properties": {
                "criteres": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "bareme_temps": {"type": "STRING"}
            },
            "required": ["criteres", "bareme_temps"]
        }
    },
    "required": ["titre_escape_room", "scenario_intro", "enigmes", "resolution_finale", "duree_estimee_minutes", "fiche_animateur", "fiche_participant", "grille_evaluation"]
}

ESCAPE_ROOM_PROMPT = """Tu es un expert en ingénierie pédagogique et en conception de jeux sérieux (serious games). Génère un escape room pédagogique complet à partir des acquis d'apprentissage suivants.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre d'énigmes : {nb_enigmes}
- Niveau de difficulté : {difficulte}
- Mode : {mode}
- Durée totale visée : {duree_totale} minutes
- Nombre d'équipes : {nb_equipes}

**CONSIGNES OBLIGATOIRES :**
1. Crée un scénario narratif cohérent qui justifie la présence des énigmes (ex: contexte fictif lié au thème du cours)
2. Chaque énigme doit être ancrée dans un concept précis du cours et cibler explicitement un AA fourni
3. Les énigmes doivent être enchaînées : résoudre l'énigme N déverrouille l'énigme N+1 (fournis l'indice/code de déverrouillage)
4. Respecte le niveau Bloom visé (Appliquer = mise en pratique directe d'un concept ; Analyser = comparaison, décomposition, identification de liens)
5. Prévois un indice optionnel par énigme (pénalité si utilisé) pour éviter les blocages complets
6. Génère la résolution finale qui récapitule les concepts mobilisés
7. Génère une fiche animateur (déroulement, gestion du temps, comment donner les indices) et une fiche participant (règles, contexte narratif, ce qui est attendu)
8. Les types d'énigmes autorisés sont : "code", "question", "manipulation", "association"

Retourne l'escape room sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""


async def generate_escape_room(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_enigmes: int,
    difficulte: str,
    mode: str,
    duree_totale: int,
    nb_equipes: int,
    model: str | None = None,
) -> dict:
    """Generate a pedagogical escape room using specified or default AI model."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    # Format the outcomes for the prompt
    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += f"- AA{lo.get('id', '')}: {lo.get('description', '')} (Niveau Bloom: {lo.get('bloom_level', '')})\n"

    prompt = ESCAPE_ROOM_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_enigmes=nb_enigmes,
        difficulte=difficulte,
        mode=mode,
        duree_totale=duree_totale,
        nb_equipes=nb_equipes,
    )

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": ESCAPE_ROOM_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini escape room response format: {e}")

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
        escape_room_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini escape room response as JSON: {e}\nRaw response: {text}")

    return escape_room_data
