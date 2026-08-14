"""Service for generating Atelier Feedback Pair grids using AI and exporting consolidated PDF reports."""

import io
import json
import logging
from typing import Optional, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from app.services.gemini_service import (
    get_gemini_config,
    has_any_ai_key,
    _call_gemini_api,
)

logger = logging.getLogger(__name__)

ATELIER_FEEDBACK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titre": {"type": "STRING"},
        "criteres": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nom": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "ponderation": {"type": "NUMBER"}
                },
                "required": ["nom", "description"]
            }
        },
        "structure_grille": {
            "type": "OBJECT",
            "properties": {
                "note_min": {"type": "NUMBER"},
                "note_max": {"type": "NUMBER"},
                "sections": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                },
                "consignes": {"type": "STRING"}
            },
            "required": ["note_min", "note_max", "sections"]
        }
    },
    "required": ["titre", "criteres", "structure_grille"]
}

ATELIER_PROMPT = """Tu es un expert en ingénierie pédagogique et évaluation formative par les pairs.
Génère une grille d'évaluation et de feedback pour un Atelier Feedback Pair à partir du cours fourni ci-dessous.

**ACQUIS D'APPRENTISSAGE (AA) :**
{learning_outcomes}

**CONCEPTS CLÉS :**
{key_concepts}

**MOTS-CLÉS :**
{keywords}

**PARAMÈTRES :**
- Nombre de critères souhaités : {nb_criteres}

**CONSIGNES :**
1. Génère un titre stimulant pour cet atelier feedback pair.
2. Crée entre {nb_criteres} critères d'évaluation clairs et constructifs (ex: clarté des arguments, qualité de la démonstration, pertinence des exemples, maîtrise des notions).
3. Définis la structure de la grille : échelle de note (note_min: 1, note_max: 5), sections obligatoires (points_positifs, axes_amelioration, note_synthese) et des consignes courtes pour les pairs évaluateurs.
4. N'utilise QUE les concepts et termes explicitement présents dans les acquis d'apprentissage et le contenu fourni.

Retourne le résultat sous la forme d'un objet JSON strict respectant exactement le schéma demandé.
"""


async def generate_atelier_feedback(
    learning_outcomes: list[dict],
    key_concepts: list[str],
    keywords: list[str],
    nb_criteres: int = 4,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Generate an Atelier Feedback rubric grid using Gemini or fallback AI APIs."""
    api_key, default_model, api_url = get_gemini_config()
    if not api_key and not has_any_ai_key():
        raise ValueError("Aucune clé API IA (GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY) n'est configurée dans le fichier .env.")

    formatted_outcomes = ""
    for lo in learning_outcomes:
        formatted_outcomes += (
            f"- AA{lo.get('id', '')}: {lo.get('description', '')} "
            f"(Niveau Bloom: {lo.get('bloom_level', '')})\n"
        )

    prompt = ATELIER_PROMPT.format(
        learning_outcomes=formatted_outcomes,
        key_concepts=", ".join(key_concepts),
        keywords=", ".join(keywords),
        nb_criteres=nb_criteres,
    )

    generation_config = {
        "temperature": 0.4,
        "maxOutputTokens": 8192,
        "responseMimeType": "application/json",
        "responseSchema": ATELIER_FEEDBACK_SCHEMA,
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    result = await _call_gemini_api(payload, timeout=120.0, requested_model=model)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response format: {e}")

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        feedback_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Gemini response as JSON: {e}\nRaw response: {text}")

    return feedback_data


def generate_consolidated_pdf(
    presentation_title: str,
    presenter_name: str,
    atelier_title: str,
    aggregated_data: dict[str, Any],
    is_anonyme: bool = True
) -> bytes:
    """Generate a clean, styled PDF document for aggregated peer feedback."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1E293B'),
        alignment=TA_LEFT
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#64748B'),
        alignment=TA_LEFT
    )

    h2_style = ParagraphStyle(
        'Heading2Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=12,
        spaceAfter=6
    )

    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155')
    )

    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1E293B'),
        leftIndent=15,
        spaceAfter=4
    )

    elements = []

    # Title & Header
    elements.append(Paragraph("<b>Atelier Feedback Pair — Rapport Consolidé</b>", title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<b>Atelier :</b> {atelier_title} | <b>Présentateur / Groupe :</b> {presenter_name}", subtitle_style))
    anonyme_str = "Oui (Évaluateurs anonymisés)" if is_anonyme else "Non"
    elements.append(Paragraph(f"<b>Mode Anonyme :</b> {anonyme_str} | <b>Total Retours Reçus :</b> {aggregated_data.get('total_feedbacks', 0)}", subtitle_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=15))

    # KPI Summary Card
    moyenne_globale = aggregated_data.get("moyenne_note_synthese")
    moyenne_text = f"{moyenne_globale:.2f} / 5" if moyenne_globale is not None else "N/A"
    
    kpi_data = [
        [
            Paragraph("<b>Note de Synthèse Moyenne</b>", ParagraphStyle('KPIHead', parent=body_style, alignment=TA_CENTER, textColor=colors.HexColor('#475569'))),
            Paragraph(f"<b>{moyenne_text}</b>", ParagraphStyle('KPIValue', parent=body_style, fontSize=16, leading=20, alignment=TA_CENTER, textColor=colors.HexColor('#2563EB')))
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[250, 250])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 15))

    # Criteria Averages Table
    elements.append(Paragraph("Moyenne des Notes par Critère", h2_style))
    moyennes_crit = aggregated_data.get("moyennes_par_critere", {})
    
    table_content = [[Paragraph("<b>Critère d'évaluation</b>", body_style), Paragraph("<b>Note moyenne (/5)</b>", body_style)]]
    if moyennes_crit:
        for crit, note in moyennes_crit.items():
            note_fmt = f"{note:.2f}" if isinstance(note, (int, float)) else str(note)
            table_content.append([Paragraph(crit, body_style), Paragraph(note_fmt, body_style)])
    else:
        table_content.append([Paragraph("Aucun critère noté", body_style), Paragraph("-", body_style)])

    crit_table = Table(table_content, colWidths=[380, 120])
    crit_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
    ]))
    elements.append(crit_table)
    elements.append(Spacer(1, 15))

    # Positive Points Compiled
    elements.append(Paragraph("Points Forts et Appréciations", h2_style))
    pts_pos = aggregated_data.get("compilation_points_positifs", [])
    if pts_pos:
        for pt in pts_pos:
            elements.append(Paragraph(f"• {pt}", bullet_style))
    else:
        elements.append(Paragraph("<i>Aucun commentaire saisi.</i>", body_style))
    elements.append(Spacer(1, 12))

    # Areas for Improvement Compiled
    elements.append(Paragraph("Axes d'Amélioration et Pistes de Progrès", h2_style))
    axes_imp = aggregated_data.get("compilation_axes_amelioration", [])
    if axes_imp:
        for ax in axes_imp:
            elements.append(Paragraph(f"• {ax}", bullet_style))
    else:
        elements.append(Paragraph("<i>Aucun commentaire saisi.</i>", body_style))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
