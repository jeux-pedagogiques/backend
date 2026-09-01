"""Service for generating and evaluating Storytelling Collaboratif using the AI layer."""

import json
import logging
from typing import Any
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

STORYTELLING_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre": {"type": "STRING"},
        "contexte_depart": {"type": "STRING"},
        "mots_cles_obligatoires": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "etapes_narratives": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "etape": {"type": "INTEGER"},
                    "titre": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "consigne": {"type": "STRING"},
                    "temps_minutes": {"type": "INTEGER"}
                },
                "required": ["etape", "titre", "description", "consigne", "temps_minutes"]
            }
        },
        "roles_narratifs": {
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
        "fiche_animateur": {
            "type": "OBJECT",
            "properties": {
                "objectifs_pedagogiques": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "deroulement_pas_a_pas": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "conseils_animation": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            },
            "required": ["objectifs_pedagogiques", "deroulement_pas_a_pas", "conseils_animation"]
        },
        "fiche_participant": {
            "type": "OBJECT",
            "properties": {
                "regles_du_jeu": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "conseils_redaction": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            },
            "required": ["regles_du_jeu", "conseils_redaction"]
        },
        "criteres_evaluation": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "critere": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "bareme": {"type": "STRING"}
                },
                "required": ["critere", "description", "bareme"]
            }
        }
    },
    "required": [
        "titre",
        "contexte_depart",
        "mots_cles_obligatoires",
        "etapes_narratives",
        "roles_narratifs",
        "fiche_animateur",
        "fiche_participant",
        "criteres_evaluation"
    ]
}

STORYTELLING_PROMPT = """Tu es un expert en pédagogie active, en créativité narrative et en ingénierie de formation.
Génère un workshop de **Storytelling Collaboratif** complet basé sur les acquis d'apprentissage (Niveau Bloom N6 : Créer / Concevoir).

**MODULE DU COURS :** {module_title}

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES DU WORKSHOP :**
- Nombre d'étapes narratives dans l'arc de l'histoire : {nb_etapes}
- Durée totale ciblée : {duree_minutes} minutes
- Niveau de créativité : {difficulte_creative}

**CONSIGNES OBLIGATOIRES :**
1. **Amorce narrative captivante (`contexte_depart`)** : Crée un scénario / intrigue immersif où les protagonistes font face à un défi professionnel, technique ou sociétal directement ancré dans les concepts du cours.
2. **Mots-clés obligatoires (`mots_cles_obligatoires`)** : Sélectionne 6 à 10 termes techniques précis issus du cours qui DOIVENT être mobilisés avec pertinence dans l'histoire par les étudiants.
3. **Étapes narratives structurées (`etapes_narratives`)** : Découpe l'arc narratif en {nb_etapes} étapes progressives (ex. Situation Initiale -> Élément Perturbateur -> Péripéties & Défi Technique -> Résolution par l'application des concepts -> Climax & Morale). Pour chaque étape, fournis une consigne précise et un temps alloué.
4. **Rôles narratifs (`roles_narratifs`)** : Définis au moins 4 rôles d'équipe (ex. "Le Scénariste Cadreur", "L'Expert Conceptuel", "Le Perturbateur d'Intrigue", "Le Synthétiseur").
5. **Fiche Animateur & Participant** : Rédige des guides pratiques pas-à-pas pour l'enseignant et les étudiants.
6. **Grille de Débriefing (`criteres_evaluation`)** : 4 critères précis (Intégration des concepts du cours, Cohérence narrative, Créativité & Originalité, Collaboration d'équipe).

Ne sors JAMAIS du cadre des concepts du cours. Réponds sous forme d'un objet JSON strict respectant exactement le schéma fourni.
"""

STORY_EVALUATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "note_globale": {"type": "NUMBER"},
        "appreciation": {"type": "STRING"},
        "concepts_identifies": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "concepts_manquants": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "points_forts": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        },
        "axes_amelioration": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": [
        "note_globale",
        "appreciation",
        "concepts_identifies",
        "concepts_manquants",
        "points_forts",
        "axes_amelioration"
    ]
}

STORY_EVALUATION_PROMPT = """Tu es un évaluateur pédagogique bienveillant et rigoureux.
Évalue l'histoire collaborative suivante rédigée par des étudiants par rapport aux concepts attendus :

**HISTOIRE COMPLÈTE :**
{texte_complet}

**MOTS-CLÉS / CONCEPTS ATTENDUS :**
{mots_cles_obligatoires}

**CONSIGNES D'ÉVALUATION :**
1. Note globale sur 20 selon la pertinence de l'intégration des concepts, la créativité et la cohérence.
2. Identifie les concepts clés effectivement et correctement mobilisés.
3. Repère les concepts attendus qui n'ont pas été mentionnés ou mal compris.
4. Fournis une appréciation constructive et personnalisée avec points forts et axes d'amélioration.

Retourne un objet JSON strict selon le schéma demandé.
"""


async def generate_storytelling(
    module_title: str,
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_etapes: int = 4,
    duree_minutes: int = 20,
    difficulte_creative: str = "standard",
    model: str | None = None,
) -> dict:
    """Generate a collaborative storytelling workshop using LLM."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA n'est configurée dans le fichier .env.")

    formatted_outcomes = "\n".join(
        f"- AA{lo.get('id', i+1)}: {lo.get('description', '')} (Niveau: {lo.get('bloom_level', 'creer')})"
        for i, lo in enumerate(learning_outcomes)
    ) or "Aucun AA explicite."

    prompt = STORYTELLING_PROMPT.format(
        module_title=module_title or "Cours",
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts) if key_concepts else "Général",
        keywords=", ".join(keywords) if keywords else "Général",
        nb_etapes=nb_etapes,
        duree_minutes=duree_minutes,
        difficulte_creative=difficulte_creative,
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
            "responseSchema": STORYTELLING_RESPONSE_SCHEMA,
        },
    }

    result = await _call_gemini_api(payload, timeout=120.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Format de réponse IA inattendu : {e}")

    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Échec de décodage JSON pour le Storytelling : {e}\nRéponse brute : {text}")


async def evaluate_storytelling(
    texte_complet: str,
    mots_cles_obligatoires: list[str] | None = None,
    model: str | None = None,
) -> dict:
    """Evaluate a completed collaborative story against required concepts."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA n'est configurée dans le fichier .env.")

    prompt = STORY_EVALUATION_PROMPT.format(
        texte_complet=texte_complet,
        mots_cles_obligatoires=", ".join(mots_cles_obligatoires) if mots_cles_obligatoires else "Concepts du module",
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseSchema": STORY_EVALUATION_SCHEMA,
        },
    }

    result = await _call_gemini_api(payload, timeout=120.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Format de réponse IA inattendu : {e}")

    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Échec de décodage JSON de l'évaluation : {e}\nRéponse brute : {text}")
