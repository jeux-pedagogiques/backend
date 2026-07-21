"""Service for generating pitching challenges using Gemini AI."""

import json
import logging
from app.services.gemini_service import _call_gemini_api, get_gemini_config

logger = logging.getLogger(__name__)

PITCHING_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre_challenge": {"type": "STRING"},
        "sujet_principal": {"type": "STRING"},
        "sujets_par_equipe": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "aa_cibles": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "criteres_vote": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "critere": {"type": "STRING"},
                    "description": {"type": "STRING"}
                },
                "required": ["critere", "description"]
            }
        },
        "grille_feedback": {
            "type": "OBJECT",
            "properties": {
                "points_positifs": {"type": "STRING"},
                "axes_amelioration": {"type": "STRING"},
                "note_synthese": {"type": "STRING"}
            },
            "required": ["points_positifs", "axes_amelioration", "note_synthese"]
        },
        "questions_debriefing": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "fiche_animateur": {"type": "STRING"},
        "fiche_participant": {"type": "STRING"}
    },
    "required": [
        "titre_challenge",
        "sujet_principal",
        "aa_cibles",
        "criteres_vote",
        "grille_feedback",
        "questions_debriefing",
        "fiche_animateur",
        "fiche_participant"
    ]
}

PITCHING_PROMPT = """Tu es un expert en ingénierie pédagogique et en animation pédagogique. Génère un pitching challenge complet à partir des acquis d'apprentissage suivants.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre d'équipes : {nb_equipes}
- Temps de préparation : {duree_preparation} minutes
- Temps de pitch par équipe : {duree_pitch} minutes (généralement 2-3 min)
- Temps de feedback après chaque pitch : {duree_feedback} minutes (généralement 5 min)

**CONSIGNES :**
1. Génère un sujet de pitch directement lié au cours : une idée à défendre, une solution technique à proposer, ou une position à argumenter en lien avec les concepts du cours
2. Le sujet doit permettre à chaque équipe de développer un angle différent (pas un sujet identique et unique pour toutes les équipes, sauf si demandé)
3. Génère les critères de vote/évaluation des pairs (ex: clarté, conviction, originalité, pertinence par rapport au cours)
4. Génère la grille de feedback structuré que chaque équipe remplira pour évaluer les autres
5. Génère 3 à 5 questions de débriefing collectif à poser après tous les pitchs, pour faire le lien entre les pitchs et les acquis d'apprentissage visés
6. N'utilise QUE les concepts et termes explicitement présents dans les acquis d'apprentissage et le contenu fourni ci-dessus. Ne complète jamais avec des notions techniques qui n'apparaissent pas dans le texte source, même si elles sont couramment associées au sujet.

Retourne le challenge sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""


async def generate_pitching_challenge(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_equipes: int,
    duree_preparation: int,
    duree_pitch: int,
    duree_feedback: int,
) -> dict:
    """Generate a pitching challenge using Gemini from learning outcomes."""
    api_key, model, api_url = get_gemini_config()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += (
            f"- AA{lo.get('id', '')}: {lo.get('description', '')} "
            f"(Niveau Bloom: {lo.get('bloom_level', '')})\n"
        )

    prompt = PITCHING_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_equipes=nb_equipes,
        duree_preparation=duree_preparation,
        duree_pitch=duree_pitch,
        duree_feedback=duree_feedback,
    )

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": PITCHING_RESPONSE_SCHEMA,
    }

    model_lower = model.lower()
    if "3.5" in model_lower:
        generation_config["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    elif "2.5" in model_lower:
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini pitching response format: {e}")

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        pitching_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini pitching response as JSON: {e}\nRaw response: {text}")

    return pitching_data
