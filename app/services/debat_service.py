"""Service for generating structured debates (Débat Structuré) using the AI layer.

Suivant le même pattern que pitching_challenge_service / cas_etude_service :
appel unique vers `_call_gemini_api` avec un `responseSchema` JSON strict.
"""

import json
import logging
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

DEBAT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "problematique": {"type": "STRING"},
        "camp_pour": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "camp_contre": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "roles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nom_role": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "missions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["nom_role", "description", "missions"]
            }
        },
        "questions_relance": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": ["problematique", "camp_pour", "camp_contre", "roles", "questions_relance"]
}

DEBAT_PROMPT = """Tu es un expert en ingénierie pédagogique et en animation de débats structurés (format débat contradictoire). Génère un débat structuré complet à partir des acquis d'apprentissage suivants.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre d'arguments initiaux par camp : {nb_arguments_par_camp}
- Durée maximale par intervention : {duree_intervention_secondes} secondes

**CONSIGNES OBLIGATOIRES :**
1. Génère une problématique réellement controversée et débattable, directement liée aux concepts du cours et aux AA visés (deux positions opposées doivent être défendables avec le contenu du cours).
2. Génère les arguments initiaux du camp POUR (thèse) : chaque argument doit être ancré dans un concept précis du cours et citer explicitement l'AA qu'il mobilise.
3. Génère les arguments initiaux du camp CONTRE (antithèse) : chaque argument doit être un contre-argument crédible et ancré dans le cours.
4. Définis les 4 rôles suivants avec des missions claires :
   - "avocat" : défend la position du camp POUR
   - "avocat_du_diable" : défend la position du camp CONTRE
   - "moderateur" : distribue la parole, fait respecter le chrono, relance le débat
   - "observateur_rapporteur" : prend des notes sur les arguments échangés et prépare la synthèse
5. Génère 3 à 5 questions de relance que le modérateur pourra poser pour approfondir ou débloquer le débat.
6. N'utilise QUE les concepts et termes explicitement présents dans les acquis d'apprentissage et le contenu fourni ci-dessus. Ne complète jamais avec des notions techniques qui n'apparaissent pas dans le texte source, même si elles sont couramment associées au sujet.

Retourne le débat sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""

SYNTHESE_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "resume_debat": {"type": "STRING"},
        "arguments_pour": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "arguments_contre": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "points_cles": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "conclusion": {"type": "STRING"}
    },
    "required": ["resume_debat", "arguments_pour", "arguments_contre", "points_cles", "conclusion"]
}

SYNTHESE_PROMPT = """Tu es un expert en ingénierie pédagogique. Rédige la synthèse finale d'un débat structuré qui vient de se dérouler en classe.

**PROBLÉMATIQUE DÉBATTUE :**
{problematique}

**DÉROULÉ DES PRISES DE PAROLE (chronologiques) :**
{interventions}

**NOTES DE L'OBSERVATEUR-RAPPORTEUR :**
{notes}

**CONSIGNES OBLIGATOIRES :**
1. Résume fidèlement le débat en restituant les arguments POUR et les arguments CONTRE réellement échangés (ne pas inventer).
2. Identifie les points de convergence et de divergence entre les camps.
3. Extrais les points clés à retenir en lien avec les acquis d'apprentissage visés.
4. Termine par une conclusion pédagogique objective, sans prendre parti.
5. Respecte la structure JSON demandée : resume_debat, arguments_pour, arguments_contre, points_cles, conclusion.

Retourne la synthèse sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""


async def generate_debat(
    module_title: str,
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_arguments_par_camp: int = 3,
    duree_intervention_secondes: int = 120,
    model: str | None = None,
) -> dict:
    """Generate a structured debate using the specified or default AI model."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += (
            f"- AA{lo.get('id', '')}: {lo.get('description', '')} "
            f"(Niveau Bloom: {lo.get('bloom_level', '')})\n"
        )

    prompt = DEBAT_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_arguments_par_camp=nb_arguments_par_camp,
        duree_intervention_secondes=duree_intervention_secondes,
    )

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": DEBAT_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini debate response format: {e}")

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        debat_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini debate response as JSON: {e}\nRaw response: {text}")

    return debat_data


async def generate_debat_synthese(
    problematique: str,
    interventions: list[dict],
    notes: list[str],
    model: str | None = None,
) -> dict:
    """Generate the automatic synthesis of the debate from the speech history."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    formatted_interventions = ""
    for idx, inter in enumerate(interventions, start=1):
        contenu = (inter.get("contenu") or "").strip()
        if not contenu:
            continue
        duree = inter.get("duree_secondes")
        formatted_interventions += (
            f"{idx}. [{inter.get('camp', 'neutre')}] {inter.get('pseudo', 'Participant')}"
            f"{f' ({duree}s)' if duree else ''}: {contenu}\n"
        )

    if not formatted_interventions.strip():
        raise RuntimeError("Aucune prise de parole enregistrée, impossible de générer la synthèse.")

    formatted_notes = "\n".join(f"- {n}" for n in notes) if notes else "Aucune note."

    prompt = SYNTHESE_PROMPT.format(
        problematique=problematique,
        interventions=formatted_interventions.strip(),
        notes=formatted_notes,
    )

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 8192,
        "responseMimeType": "application/json",
        "responseSchema": SYNTHESE_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini synthesis response format: {e}")

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        synthese_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini synthesis response as JSON: {e}\nRaw response: {text}")

    return synthese_data
