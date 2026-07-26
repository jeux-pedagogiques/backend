"""Service for generating Gamified Case Studies (Étude de Cas Gamifiée) using Gemini AI."""

import json
import logging
from app.services.gemini_service import _call_gemini_api, get_gemini_config

logger = logging.getLogger(__name__)

CAS_ETUDE_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre": {"type": "STRING"},
        "contexte_scenario": {"type": "STRING"},
        "format_restitution": {"type": "STRING"},
        "roles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nom_role": {"type": "STRING"},
                    "objectifs": {"type": "STRING"},
                    "infos_privees": {"type": "STRING"},
                    "contraintes_secretes": {"type": "STRING"}
                },
                "required": ["nom_role", "objectifs", "infos_privees", "contraintes_secretes"]
            }
        },
        "questions_decisions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "titre": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "choix_possibles": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["id", "titre", "description"]
            }
        },
        "grille_evaluation": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "critere": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "poids": {"type": "INTEGER"}
                },
                "required": ["critere", "description", "poids"]
            }
        }
    },
    "required": [
        "titre",
        "contexte_scenario",
        "format_restitution",
        "roles",
        "questions_decisions",
        "grille_evaluation"
    ]
}


async def generate_cas_etude(
    module_title: str,
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_roles: int = 3,
    format_restitution: str = "oral"
) -> dict:
    """Generate a realistic business case study with asymmetric roles and decisions."""
    prompt = f"""Tu es un expert en conception pédagogique et ludification d'études de cas professionnelles.
Génère une étude de cas gamifiée basée sur le cours suivant :

- Titre du module : {module_title}
- Acquis d'apprentissage : {json.dumps(learning_outcomes, ensure_ascii=False)}
- Concepts clés : {json.dumps(key_concepts, ensure_ascii=False)}
- Mots-clés : {json.dumps(keywords, ensure_ascii=False)}

Règles de génération :
1. "contexte_scenario": Raconte une situation professionnelle concrète, immersive et réaliste complexe liée au module.
2. "roles": Génère exactement {nb_roles} rôles asymétriques pour l'équipe (ex: Directeur Technique, Responsable Sécurité, Directeur Financier).
   - "infos_privees": Chaque rôle doit avoir des informations EXCLUSIVES et CONFIDENTIELLES qu'aucun autre rôle n'a. Cela doit forcer les membres de l'équipe à communiquer pour résoudre le cas.
   - "contraintes_secretes": Les objectifs personnels et contraintes métiers du rôle.
3. "questions_decisions": 3 à 4 questions stratégiques avec id ("q1", "q2", etc.) demandant une décision concertée et une justification détaillée.
4. "grille_evaluation": 3 à 5 critères d'évaluation pour la restitution finale ({format_restitution}).
5. "format_restitution": "{format_restitution}".

Réponds UNIQUEMENT en JSON valide conforme au schéma.
"""

    api_key, model, api_url = get_gemini_config()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": CAS_ETUDE_RESPONSE_SCHEMA,
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

    try:
        result = await _call_gemini_api(payload, timeout=180.0)
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Error generating cas d'etude with Gemini: {e}")
        # Fallback response structure in case AI call fails
        return {
            "titre": f"Étude de Cas : {module_title}",
            "contexte_scenario": f"Scénario d'analyse pour le module {module_title}.",
            "format_restitution": format_restitution,
            "roles": [
                {
                    "nom_role": "Responsable Technique",
                    "objectifs": "Garantir la viabilité technique.",
                    "infos_privees": "Budget technique limité à 50K€.",
                    "contraintes_secretes": "Ne pas faire de compromis sur la sécurité."
                },
                {
                    "nom_role": "Responsable Métier",
                    "objectifs": "Optimiser l'expérience utilisateur et les processus.",
                    "infos_privees": "La direction exige un déploiement sous 3 mois.",
                    "contraintes_secretes": "Maintenir la satisfaction client au-dessus de 90%."
                },
                {
                    "nom_role": "Directeur Financier",
                    "objectifs": "Assurer le ROI de la décision.",
                    "infos_privees": "Marge d'erreur financière de 10% maximum.",
                    "contraintes_secretes": "Réduire le coût opérationnel global."
                }
            ],
            "questions_decisions": [
                {
                    "id": "q1",
                    "titre": "Stratégie d'implémentation",
                    "description": "Quelle est la meilleure approche d'implémentation compte tenu de vos contraintes ?",
                    "choix_possibles": ["Option A: Déploiement rapide", "Option B: Déploiement progressif", "Option C: Refonte complète"]
                },
                {
                    "id": "q2",
                    "titre": "Gestion des risques",
                    "description": "Comment planifiez-vous d'atténuer le risque principal identifié ?",
                    "choix_possibles": ["Audit externe", "Assurance qualité renforcée", "Plan de secours opérationnel"]
                }
            ],
            "grille_evaluation": [
                {"critere": "Qualité de la décision", "description": "Cohérence globale avec les objectifs", "poids": 3},
                {"critere": "Collaboration & Rôles", "description": "Prise en compte des infos spécifiques de chaque rôle", "poids": 2},
                {"critere": "Clarté de la justification", "description": "Rigueur des arguments présentés", "poids": 2}
            ]
        }
