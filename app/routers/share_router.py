"""Router for shareable game URLs — create share links, public game access, and student results."""

from typing import Optional, Any, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.services.auth_service import get_current_user
from app.services.email_service import send_email
from app.models.user import User
from app.models.game_share import GameShare, GameResult
from app.models.quiz import Quiz
from app.models.escape_room import EscapeRoom
from app.models.flashcard import FlashcardSet
from app.models.pitching import PitchingSession
from app.models.cas_etude import CasEtude
from app.models.mindmap import MindMap
from app.models.debat import Debat
from app.models.storytelling import Storytelling

router = APIRouter(prefix="/api/shares", tags=["shares"])

VALID_GAME_TYPES = {"quiz", "escape_room", "flashcards", "pitching", "cas_etude", "mindmap", "debat", "storytelling"}


# ─── Request / Response Schemas ──────────────────────────────────────

class CreateShareRequest(BaseModel):
    game_type: str
    game_id: int


class CreateShareResponse(BaseModel):
    share_token: str
    share_url: str


class ShareGameEmailRequest(BaseModel):
    game_type: str
    game_id: int
    recipient_emails: List[str]
    frontend_url: Optional[str] = None


class SubmitResultRequest(BaseModel):
    student_name: str
    score: Optional[float] = None
    max_score: Optional[float] = None
    completion_time_seconds: Optional[int] = None
    result_data: Optional[dict[str, Any]] = None


# ─── Professor Endpoints (Auth Required) ─────────────────────────────

@router.post("", response_model=CreateShareResponse)
def create_share(
    req: CreateShareRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Professor creates a shareable link for a game."""
    if req.game_type not in VALID_GAME_TYPES:
        raise HTTPException(400, f"Invalid game_type. Must be one of: {VALID_GAME_TYPES}")

    # Verify the game exists and belongs to the current user
    _get_game_or_404(session, req.game_type, req.game_id, current_user.id)

    # Check if a share already exists for this game
    existing = session.exec(
        select(GameShare).where(
            GameShare.game_type == req.game_type,
            GameShare.game_id == req.game_id,
            GameShare.user_id == current_user.id,
            GameShare.is_active,
        )
    ).first()

    if existing:
        return CreateShareResponse(
            share_token=existing.share_token,
            share_url=f"/play/{req.game_type}/{existing.share_token}",
        )

    share = GameShare(
        game_type=req.game_type,
        game_id=req.game_id,
        user_id=current_user.id,
    )
    session.add(share)
    session.commit()
    session.refresh(share)

    return CreateShareResponse(
        share_token=share.share_token,
        share_url=f"/play/{req.game_type}/{share.share_token}",
    )


@router.post("/email")
def share_game_email(
    req: ShareGameEmailRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Send invitation emails for a shared game via SMTP."""
    if req.game_type not in VALID_GAME_TYPES:
        raise HTTPException(400, f"Invalid game_type. Must be one of: {VALID_GAME_TYPES}")

    game = _get_game_or_404(session, req.game_type, req.game_id, current_user.id)

    # Get or create share token
    existing_share = session.exec(
        select(GameShare).where(
            GameShare.game_type == req.game_type,
            GameShare.game_id == req.game_id,
            GameShare.user_id == current_user.id,
            GameShare.is_active,
        )
    ).first()

    if not existing_share:
        existing_share = GameShare(
            game_type=req.game_type,
            game_id=req.game_id,
            user_id=current_user.id,
        )
        session.add(existing_share)
        session.commit()
        session.refresh(existing_share)

    base_url = req.frontend_url.rstrip("/") if req.frontend_url else "http://localhost:4200"
    join_link = f"{base_url}/play/{req.game_type}/{existing_share.share_token}"

    title = getattr(game, "titre", None) or getattr(game, "title", None) or getattr(game, "name", None) or "Jeu ESPRIT"
    creator_name = (
        f"{current_user.first_name} {current_user.last_name}".strip()
        if current_user.first_name and current_user.last_name
        else (current_user.username or "Professeur")
    )

    game_type_labels = {
        "quiz": "Quiz Interactif",
        "escape_room": "Escape Room Pédagogique",
        "flashcards": "Flashcards d'Étude",
        "pitching": "Challenge Pitching",
        "cas_etude": "Étude de Cas",
        "mindmap": "Carte Mentale (Mind Map)",
        "debat": "Débat Structuré",
        "storytelling": "Storytelling Collaboratif"
    }
    type_label = game_type_labels.get(req.game_type, "Activité Pédagogique")

    subject = f"Invitation : {type_label} ESPRIT - {title}"

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invitation {type_label} ESPRIT AI</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
    
    <!-- Top Accent Gradient Line -->
    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
            <td style="height: 5px; background: #9f0d15; background: linear-gradient(90deg, #7f1d1d 0%, #c51414 50%, #ea580c 100%);"></td>
        </tr>
    </table>

    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f1f5f9; padding: 25px 15px 40px 15px;">
        <tr>
            <td align="center">
                
                <!-- Main Wrapper Container -->
                <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 540px;">
                    
                    <!-- Header Logo -->
                    <tr>
                        <td align="left" style="padding: 15px 10px 25px 10px;">
                            <span style="font-size: 24px; font-weight: 900; color: #0f172a; font-family: 'Segoe UI', Arial, sans-serif; letter-spacing: -0.5px;">
                                ESPRIT<span style="color: #9f0d15;">.AI</span>
                            </span>
                        </td>
                    </tr>

                    <!-- Main White Card -->
                    <tr>
                        <td style="background-color: #ffffff; border-radius: 20px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.05); padding: 36px 30px; border: 1px solid #e2e8f0;">
                            
                            <p style="margin: 0 0 18px 0; color: #0f172a; font-size: 16px; font-weight: 600;">Bonjour,</p>
                            <p style="margin: 0 0 26px 0; color: #334155; font-size: 15px; line-height: 1.6;">
                                <strong style="color: #0f172a; font-weight: 700;">{creator_name}</strong> vous invite à réaliser une activité pédagogique en ligne sur la plateforme ESPRIT AI.
                            </p>

                            <!-- 2x2 Grid Info Box -->
                            <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; margin-bottom: 30px; border-collapse: separate; border-spacing: 0; overflow: hidden;">
                                <tr>
                                    <td width="50%" align="center" style="padding: 24px 15px; border-right: 1px solid #e2e8f0; text-align: center; vertical-align: middle;">
                                        <div style="font-size: 11px; font-weight: 800; letter-spacing: 1px; color: #9f0d15; text-transform: uppercase; margin-bottom: 6px;">
                                            TITRE DU JEU
                                        </div>
                                        <div style="font-size: 15px; font-weight: 700; color: #0f172a; word-break: break-word;">
                                            {title}
                                        </div>
                                    </td>
                                    <td width="50%" align="center" style="padding: 24px 15px; text-align: center; vertical-align: middle;">
                                        <div style="font-size: 11px; font-weight: 800; letter-spacing: 1px; color: #9f0d15; text-transform: uppercase; margin-bottom: 6px;">
                                            TYPE D'ACTIVITÉ
                                        </div>
                                        <div style="font-size: 15px; font-weight: 700; color: #0f172a;">
                                            {type_label}
                                        </div>
                                    </td>
                                </tr>
                            </table>

                            <!-- Call To Action Button -->
                            <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 28px;">
                                <tr>
                                    <td align="center">
                                        <table role="presentation" border="0" cellspacing="0" cellpadding="0">
                                            <tr>
                                                <td align="center" bgcolor="#8C0A10" style="border-radius: 30px; background-color: #8C0A10; box-shadow: 0 6px 18px rgba(140, 10, 16, 0.3);">
                                                    <a href="{join_link}" target="_blank" style="font-size: 16px; font-weight: 800; color: #ffffff !important; text-decoration: none; padding: 16px 38px; border-radius: 30px; display: inline-block; background-color: #8C0A10; border: 1px solid #8C0A10; letter-spacing: 0.3px;">
                                                        Commencer le Jeu
                                                    </a>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>

                            <!-- Direct Link Fallback -->
                            <div style="background-color: #f1f5f9; padding: 14px 18px; border-radius: 12px; text-align: center; font-size: 12px; color: #64748b; line-height: 1.5;">
                                Si le bouton ne s'affiche pas correctement, copiez ce lien :<br>
                                <a href="{join_link}" target="_blank" style="color: #0f172a !important; font-weight: 700; text-decoration: underline; word-break: break-all; margin-top: 4px; display: inline-block;">
                                    {join_link}
                                </a>
                            </div>

                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td align="center" style="padding: 25px 20px 10px 20px; text-align: center; font-size: 12px; color: #94a3b8;">
                            © ESPRIT AI Platform • Partage automatique de jeu pédagogique
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    text_content = f"Bonjour,\n\n{creator_name} vous invite à réaliser '{title}' ({type_label}).\nLien direct : {join_link}\n\nCordialement."

    targets = list(dict.fromkeys([e.strip() for e in req.recipient_emails if e and e.strip()]))
    if not targets:
        raise HTTPException(400, "Veuillez fournir au moins une adresse email valide.")

    sent_count = 0
    failed_emails = []

    for email in targets:
        ok = send_email(
            to_email=email,
            subject=subject,
            body_html=html_content,
            body_text=text_content
        )
        if ok:
            sent_count += 1
        else:
            failed_emails.append(email)

    if sent_count == 0:
        raise HTTPException(500, "Échec de l'envoi des emails via le serveur SMTP.")

    msg = f"Invitation au jeu envoyée avec succès par email à {sent_count} destinataire(s)."
    if failed_emails:
        msg += f" (Échec pour : {', '.join(failed_emails)})"

    return {"status": "success", "message": msg, "sent_count": sent_count, "failed_count": len(failed_emails)}


@router.get("/results/{game_type}/{game_id}")
def get_results(
    game_type: str,
    game_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Professor views all student results for a shared game."""
    shares = session.exec(
        select(GameShare).where(
            GameShare.game_type == game_type,
            GameShare.game_id == game_id,
            GameShare.user_id == current_user.id,
        )
    ).all()

    if not shares:
        return {"results": [], "total": 0}

    share_ids = [s.id for s in shares]
    results = session.exec(
        select(GameResult).where(GameResult.share_id.in_(share_ids)).order_by(GameResult.completed_at.desc())
    ).all()

    return {
        "results": [
            {
                "id": r.id,
                "student_name": r.student_name,
                "score": r.score,
                "max_score": r.max_score,
                "completion_time_seconds": r.completion_time_seconds,
                "result_data": r.result_data,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in results
        ],
        "total": len(results),
    }


class ClaimSubjectRequest(BaseModel):
    student_name: str
    subject_index: int
    subject_title: str


# ─── Public Endpoints (No Auth) ──────────────────────────────────────

@router.get("/{token}")
def get_shared_game(token: str, session: Session = Depends(get_session)):
    """Public — load game data for a shared token."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    game_data, titre = _load_game_data(session, share.game_type, share.game_id)

    claimed_subjects = []
    if share.game_type == "pitching":
        results = session.exec(
            select(GameResult).where(GameResult.share_id == share.id)
        ).all()
        for r in results:
            if r.result_data and "claimed_subject_index" in r.result_data:
                claimed_subjects.append({
                    "subject_index": r.result_data["claimed_subject_index"],
                    "subject_title": r.result_data.get("claimed_subject_title", ""),
                    "student_name": r.student_name,
                })

    return {
        "game_type": share.game_type,
        "game_id": share.game_id,
        "titre": titre,
        "game_data": game_data,
        "claimed_subjects": claimed_subjects,
    }


@router.post("/{token}/claim-subject")
def claim_subject(
    token: str,
    req: ClaimSubjectRequest,
    session: Session = Depends(get_session),
):
    """Public — student claims a subject in pitching challenge."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    if not req.student_name or not req.student_name.strip():
        raise HTTPException(400, "Student name is required")

    # Check if subject index is already claimed
    results = session.exec(
        select(GameResult).where(GameResult.share_id == share.id)
    ).all()

    for r in results:
        if r.result_data and r.result_data.get("claimed_subject_index") == req.subject_index:
            if r.student_name != req.student_name.strip():
                raise HTTPException(
                    400, f"Ce sujet a déjà été réservé par {r.student_name}."
                )

    # Record claim
    result = GameResult(
        share_id=share.id,
        student_name=req.student_name.strip(),
        score=0,
        max_score=5,
        completion_time_seconds=0,
        result_data={
            "claimed_subject_index": req.subject_index,
            "claimed_subject_title": req.subject_title,
        },
    )
    session.add(result)
    session.commit()

    return {
        "status": "success",
        "subject_index": req.subject_index,
        "claimed_by": req.student_name.strip(),
    }


@router.post("/{token}/results")
def submit_result(
    token: str,
    req: SubmitResultRequest,
    session: Session = Depends(get_session),
):
    """Public — student submits game results."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    if not req.student_name or not req.student_name.strip():
        raise HTTPException(400, "Student name is required")

    result = GameResult(
        share_id=share.id,
        student_name=req.student_name.strip(),
        score=req.score,
        max_score=req.max_score,
        completion_time_seconds=req.completion_time_seconds,
        result_data=req.result_data,
    )
    session.add(result)
    session.commit()
    session.refresh(result)

    return {
        "id": result.id,
        "student_name": result.student_name,
        "score": result.score,
        "max_score": result.max_score,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
    }


# ─── Internal Helpers ─────────────────────────────────────────────────

def _get_game_or_404(session: Session, game_type: str, game_id: int, user_id: int):
    """Verify the game exists and belongs to the user."""
    model_map = {
        "quiz": (Quiz, "user_id"),
        "escape_room": (EscapeRoom, "user_id"),
        "flashcards": (FlashcardSet, "user_id"),
        "pitching": (PitchingSession, "prof_id"),
        "cas_etude": (CasEtude, "user_id"),
        "mindmap": (MindMap, "user_id"),
        "debat": (Debat, "user_id"),
        "storytelling": (Storytelling, "user_id"),
    }
    model_cls, owner_field = model_map[game_type]
    game = session.get(model_cls, game_id)
    if not game:
        raise HTTPException(404, f"{game_type} with id {game_id} not found")
    if getattr(game, owner_field) != user_id:
        raise HTTPException(403, "You don't own this game")
    return game


def _load_game_data(session: Session, game_type: str, game_id: int):
    """Load the full game data for public consumption."""
    if game_type == "quiz":
        quiz = session.get(Quiz, game_id)
        if not quiz:
            raise HTTPException(404, "Quiz not found")
        return quiz.quiz_data, quiz.titre

    elif game_type == "escape_room":
        room = session.get(EscapeRoom, game_id)
        if not room:
            raise HTTPException(404, "Escape room not found")
        return room.escape_room_data, room.titre_escape_room

    elif game_type == "flashcards":
        stmt = select(FlashcardSet).where(FlashcardSet.id == game_id).options(
            selectinload(FlashcardSet.cartes)
        )
        fset = session.exec(stmt).first()
        if not fset:
            raise HTTPException(404, "Flashcard set not found")
        cards = [
            {
                "id": c.id,
                "recto": c.recto,
                "verso": c.verso,
                "aa_source": c.aa_source,
                "niveau_bloom": c.niveau_bloom,
                "ordre": c.ordre,
            }
            for c in sorted(fset.cartes, key=lambda x: x.ordre)
        ]
        return {"cards": cards, "nb_cartes": fset.nb_cartes}, fset.titre

    elif game_type == "pitching":
        ps = session.get(PitchingSession, game_id)
        if not ps:
            raise HTTPException(404, "Pitching session not found")
        return {"description": ps.description, "mode": ps.mode}, ps.titre

    elif game_type == "cas_etude":
        cas = session.get(CasEtude, game_id)
        if not cas:
            raise HTTPException(404, "Cas d'étude not found")
        return {
            "contexte_scenario": cas.contexte_scenario,
            "roles": cas.roles,
            "questions_decisions": cas.questions_decisions,
            "grille_evaluation": cas.grille_evaluation,
            "format_restitution": cas.format_restitution
        }, cas.titre

    elif game_type == "mindmap":
        mindmap = session.get(MindMap, game_id)
        if not mindmap:
            raise HTTPException(404, "Mind Map not found")
        return {
            "concept_central": mindmap.concept_central,
            "branches_suggerees": mindmap.branches_suggerees
        }, f"Mind Map : {mindmap.concept_central}"

    elif game_type == "debat":
        debat = session.get(Debat, game_id)
        if not debat:
            raise HTTPException(404, "Débat not found")
        return {
            "problematique": debat.problematique,
            "camp_pour": debat.camp_pour,
            "camp_contre": debat.camp_contre,
            "roles": debat.roles,
            "questions_relance": debat.questions_relance,
        }, debat.problematique or "Débat structuré"

    elif game_type == "storytelling":
        story = session.get(Storytelling, game_id)
        if not story:
            raise HTTPException(404, "Storytelling introuvable")
        return {
            "titre": story.titre,
            "contexte_depart": story.contexte_depart,
            "mots_cles_obligatoires": story.mots_cles_obligatoires,
            "etapes_narratives": story.etapes_narratives,
            "roles_narratifs": story.roles_narratifs,
            "fiche_participant": story.fiche_participant,
            "criteres_evaluation": story.criteres_evaluation,
        }, story.titre

    raise HTTPException(400, "Unknown game type")
