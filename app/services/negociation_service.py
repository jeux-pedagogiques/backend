"""Service for generating Negotiation Simulations (Simulation de Négociation) using Gemini AI."""

import json
import logging
from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

NEGOCIATION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre": {"type": "STRING"},
        "contexte_scenario": {"type": "STRING"},
        "personnages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nom_personnage": {"type": "STRING"},
                    "role_description": {"type": "STRING"},
                    "objectifs_secrets": {"type": "STRING"},
                    "arguments_cles": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "lignes_rouges_et_compromis": {"type": "STRING"}
                },
                "required": [
                    "nom_personnage",
                    "role_description",
                    "objectifs_secrets",
                    "arguments_cles",
                    "lignes_rouges_et_compromis"
                ]
            }
        },
        "points_passage": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "etape": {"type": "INTEGER"},
                    "temps_pourcentage": {"type": "INTEGER"},
                    "titre": {"type": "STRING"},
                    "instruction": {"type": "STRING"}
                },
                "required": ["etape", "temps_pourcentage", "titre", "instruction"]
            }
        },
        "criteres_debriefing": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nom_critere": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "questions_reflexion": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["nom_critere", "description", "questions_reflexion"]
            }
        }
    },
    "required": [
        "titre",
        "contexte_scenario",
        "personnages",
        "points_passage",
        "criteres_debriefing"
    ]
}


async def generate_negociation(
    module_title: str,
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_personnages: int = 2,
    model: str | None = None,
) -> dict:
    """Generate a realistic Negotiation Simulation using Gemini AI."""
    prompt = f"""Tu es un expert en ingénierie pédagogique, en théorie des jeux et en négociation professionnelle.
Génère une simulation de négociation réaliste et ludo-pédagogique basée sur le cours suivant :

- Titre du module : {module_title}
- Acquis d'apprentissage : {json.dumps(learning_outcomes, ensure_ascii=False)}
- Concepts clés : {json.dumps(key_concepts, ensure_ascii=False)}
- Mots-clés : {json.dumps(keywords, ensure_ascii=False)}

Règles de génération strictes :
1. "contexte_scenario": Raconte une mise en situation professionnelle immersive (ex: renégociation de contrat de licence logicielle, arbitrage budgétaire d'un projet IT, fusion d'équipes, partenariat commercial).
2. "personnages": Génère exactement {nb_personnages} fiches de personnages asymétriques.
   - "nom_personnage": Un nom explicite et professionnel (ex: "Alex - Directeur Acheteur", "Morgan - Fournisseur Editeur").
   - "role_description": La position officielle et publique du personnage.
   - "objectifs_secrets": Les informations strictes et CONFIDENTIELLES que seul ce personnage connaît (budget max/min, priorités masquées).
   - "arguments_cles": 3 à 4 arguments forts pour négocier.
   - "lignes_rouges_et_compromis": Les limites infranchissables et les concessions acceptables.
3. "points_passage": Exactement 3 à 4 jalons temporels (ex: 25% Réchauffement et attentes, 50% Découverte des désaccords clés, 75% Propositions finales, 100% Clôture & Signature).
4. "criteres_debriefing": 3 à 4 critères d'analyse des stratégies de négociation (ex: Négociation raisonnée vs positionnelle, gestion des informations secrètes, création de valeur mutuelle) avec des questions de réflexion pour le débriefing.

Réponds UNIQUEMENT en JSON valide conforme au schéma fourni.
"""

    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
        "responseSchema": NEGOCIATION_RESPONSE_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    try:
        result = await _call_gemini_api(payload, timeout=180.0, requested_model=model)
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Error generating negociation simulation with Gemini: {e}")
        # Fallback structured simulation
        return {
            "titre": f"Simulation de Négociation : {module_title}",
            "contexte_scenario": f"Mise en situation de négociation stratégique autour des enjeux majeurs du module {module_title}.",
            "personnages": [
                {
                    "nom_personnage": "Acheteur - Directeur des Opérations",
                    "role_description": "Représente l'entreprise cliente souhaitant externaliser et optimiser l'infrastructure.",
                    "objectifs_secrets": "Le budget maximal alloué par le conseil d'administration est strictement limité à 120K€. Une pénalité de retard est exigée.",
                    "arguments_cles": [
                        "Volume de commandes futur garanti en cas d'accord satisfaisant",
                        "Présence d'offres concurrentes agressives sur le marché",
                        "Exigence d'un niveau de service (SLA) de 99.9%"
                    ],
                    "lignes_rouges_et_compromis": "Ne peut dépasser 120K€. Peut accorder une référence client publique en contrepartie d'un rabais."
                },
                {
                    "nom_personnage": "Vendeur - Directeur Commercial IT",
                    "role_description": "Représente l'éditeur de solutions proposant le contrat de prestation et de licences.",
                    "objectifs_secrets": "Le prix plancher absolu accepté en interne est de 105K€. L'objectif principal est un engagement minimum sur 3 ans.",
                    "arguments_cles": [
                        "Haute expertise technique et support réactif 24/7",
                        "Économies d'échelle et intégration fluide clés en main",
                        "Flexibilité sur le calendrier de paiement échelonné"
                    ],
                    "lignes_rouges_et_compromis": "Prix minimum 105K€. Prêt à inclure 3 mois de maintenance offerte pour verrouiller 3 ans d'engagement."
                }
            ],
            "points_passage": [
                {
                    "etape": 1,
                    "temps_pourcentage": 25,
                    "titre": "Présentation des attentes & Cadrage",
                    "instruction": "Exposez vos positions officielles et validez les périmètres d'intervention sans révéler vos objectifs secrets."
                },
                {
                    "etape": 2,
                    "temps_pourcentage": 50,
                    "titre": "Identification des blocages & Concessions",
                    "instruction": "Testez les lignes rouges de votre interlocuteur et proposez des compromis donnant-donnant."
                },
                {
                    "etape": 3,
                    "temps_pourcentage": 75,
                    "titre": "Rédaction du projet d'accord",
                    "instruction": "Formalisez les termes clés de l'accord (prix, durée, contreparties) ou constatez le désaccord."
                },
                {
                    "etape": 4,
                    "temps_pourcentage": 100,
                    "titre": "Clôture & Signature",
                    "instruction": "Soumettez le résumé final signé par les deux parties."
                }
            ],
            "criteres_debriefing": [
                {
                    "nom_critere": "Création de valeur mutuelle (Win-Win)",
                    "description": "Capacité des parties à dépasser les arguments de prix pour négocier des contreparties stratégiques.",
                    "questions_reflexion": [
                        "Avez-vous réussi à découvrir les véritables leviers de valeur de l'autre partie ?",
                        "Quelles concessions secondaires ont débloqué les points de blocage principaux ?"
                    ]
                },
                {
                    "nom_critere": "Gestion des informations secrètes",
                    "description": "Utilisation tactique des données confidentielles sans tout dévoiler prématurément.",
                    "questions_reflexion": [
                        "À quel moment avez-vous partagé vos réelles contraintes budgétaires ou opérationnelles ?",
                        "L'autre partie a-t-elle deviné votre prix plancher / plafond ?"
                    ]
                }
            ]
        }
