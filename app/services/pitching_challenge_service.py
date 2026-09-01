"""Service for generating pitching challenges using Gemini AI."""

import json
import logging
import re
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

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

PITCHING_PROMPT = """Tu es un expert en ingénierie pédagogique et en animation d'ateliers d'éloquence / pitching. Génère un pitching challenge complet et stimulant à partir des acquis d'apprentissage suivants.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre d'équipes / participants : {nb_equipes}
- Temps de préparation : {duree_preparation} minutes
- Temps de pitch : {duree_pitch} minutes
- Temps de feedback après chaque pitch : {duree_feedback} minutes

**CONSIGNES :**
1. Génère un sujet de pitch directement lié au cours : une idée à défendre, une solution technique à proposer, ou une position à argumenter en lien avec les concepts du cours
2. Génère {nb_equipes} sous-sujets ou angles spécifiques dans `sujets_par_equipe` pour que chaque équipe ait un angle distinct
3. Génère des critères d'évaluation par les pairs pertinents (ex: clarté, pertinence technique, conviction, respect du temps)
4. Génère la grille de feedback structuré (`grille_feedback`)
5. Génère 3 à 5 questions de débriefing collectif pour relier les pitchs aux acquis d'apprentissage
6. Rédige une fiche animateur et une fiche participant claires et actionnables
7. N'utilise QUE les concepts et termes explicitement présents dans les acquis d'apprentissage et le contenu fourni.

Tu DOIS répondre avec un objet JSON strict respectant exactement cette structure :
{{
  "titre_challenge": "Titre du Challenge de Pitching",
  "sujet_principal": "Sujet général du pitch",
  "sujets_par_equipe": ["Sujet ou angle pour Équipe 1", "Sujet ou angle pour Équipe 2"],
  "aa_cibles": ["Description des AA ciblés"],
  "criteres_vote": [
    {{"critere": "Nom du critère", "description": "Description du critère"}}
  ],
  "grille_feedback": {{
    "points_positifs": "Critères d'appréciation positive...",
    "axes_amelioration": "Axes de progression suggérés...",
    "note_synthese": "Synthèse et grille globale..."
  }},
  "questions_debriefing": ["Question 1 ?", "Question 2 ?"],
  "fiche_animateur": "Guide pour l'enseignant / animateur...",
  "fiche_participant": "Consignes et conseils pour les participants..."
}}
"""


async def generate_pitching_challenge(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_equipes: int,
    duree_preparation: int,
    duree_pitch: int,
    duree_feedback: int,
    model: str | None = None,
) -> dict:
    """Generate a pitching challenge using specified or default AI model."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, BAI_API_KEY) n'est configurée.")

    if isinstance(learning_outcomes, str):
        try:
            learning_outcomes = json.loads(learning_outcomes)
        except Exception:
            learning_outcomes = [{"description": learning_outcomes, "bloom_level": "evaluer"}]

    if isinstance(key_concepts, str):
        try:
            key_concepts = json.loads(key_concepts)
        except Exception:
            key_concepts = [key_concepts]

    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = [keywords]

    formatted_outcomes = ""
    for lo in (learning_outcomes or []):
        if isinstance(lo, dict):
            lo_id = lo.get("id", "")
            desc = lo.get("description", "")
            bloom = lo.get("bloom_level", "")
        elif isinstance(lo, str):
            lo_id = ""
            desc = lo
            bloom = ""
        else:
            lo_id = getattr(lo, "id", "")
            desc = getattr(lo, "description", str(lo))
            bloom = getattr(lo, "bloom_level", "")
        formatted_outcomes += f"- AA{lo_id}: {desc} (Niveau Bloom: {bloom})\n"

    prompt = PITCHING_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(str(k) for k in (key_concepts or [])),
        keywords=", ".join(str(k) for k in (keywords or [])),
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

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Format de réponse IA inattendu : {e}")

    text = text.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        cleaned_json = match.group(0)
    else:
        cleaned_json = text
        if cleaned_json.startswith("```json"):
            cleaned_json = cleaned_json[7:]
        if cleaned_json.startswith("```"):
            cleaned_json = cleaned_json[3:]
        if cleaned_json.endswith("```"):
            cleaned_json = cleaned_json[:-3]
        cleaned_json = cleaned_json.strip()

    try:
        pitching_data = json.loads(cleaned_json)
    except json.JSONDecodeError:
        try:
            fixed_json = re.sub(r",\s*([}\]])", r"\1", cleaned_json)
            pitching_data = json.loads(fixed_json)
        except Exception as e:
            raise RuntimeError(f"Échec de l'analyse du JSON généré par l'IA : {e}\nRéponse brute : {text[:500]}")

    # Ensure required fields have fallback defaults
    pitching_data.setdefault("titre_challenge", "Pitching Challenge")
    pitching_data.setdefault("sujet_principal", "Défi de Pitching")
    if not pitching_data.get("sujets_par_equipe"):
        pitching_data["sujets_par_equipe"] = [f"Équipe {i+1} : Sujet et argumentation" for i in range(nb_equipes)]
    pitching_data.setdefault("aa_cibles", [])
    if not pitching_data.get("criteres_vote"):
        pitching_data["criteres_vote"] = [
            {"critere": "Clarté et Structure", "description": "Structure logique et clarté de l'exposé"},
            {"critere": "Pertinence Technique", "description": "Justesse des concepts mobilisés"},
            {"critere": "Conviction & Éloquence", "description": "Impact, force d'argumentation et dynamisme"}
        ]
    if not isinstance(pitching_data.get("grille_feedback"), dict):
        pitching_data["grille_feedback"] = {
            "points_positifs": "Points forts et arguments solides",
            "axes_amelioration": "Pistes de progression et clarté",
            "note_synthese": "Synthèse globale de la prestation"
        }
    else:
        pitching_data["grille_feedback"].setdefault("points_positifs", "Points forts observés")
        pitching_data["grille_feedback"].setdefault("axes_amelioration", "Pistes d'amélioration")
        pitching_data["grille_feedback"].setdefault("note_synthese", "Synthèse générale")

    if not pitching_data.get("questions_debriefing"):
        pitching_data["questions_debriefing"] = [
            "Quels ont été les arguments les plus percutants présentés lors des pitchs ?",
            "Comment ces pitchs illustrent-ils les acquis d'apprentissage du module ?"
        ]
    pitching_data.setdefault("fiche_animateur", "Consignes d'animation pour l'enseignant.")
    pitching_data.setdefault("fiche_participant", "Consignes et conseils pour les participants.")

    return pitching_data

