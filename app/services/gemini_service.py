"""Service for analyzing module sheets using the Gemini AI API."""

import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-pro")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured in the .env file.")

    prompt = ANALYSIS_PROMPT.format(content=content)

    generation_config = {
        "temperature": 0.2,
        "maxOutputTokens": 16384,
        "responseMimeType": "application/json",
    }

    # Configure thinking budget/level for models that support/require it
    model_lower = GEMINI_MODEL.lower()
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

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    if response.status_code != 200:
        error_detail = response.text
        raise RuntimeError(f"Gemini API error ({response.status_code}): {error_detail}")

    result = response.json()

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
