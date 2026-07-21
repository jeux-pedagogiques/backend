"""Dashboard service — SQL aggregation queries for professor analytics."""

import logging
from typing import Any

from sqlmodel import Session, select, func, col

from app.models.module_analysis import ModuleAnalysis
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt
from app.models.escape_room import EscapeRoom
from app.models.pitching import PitchingSession, PitchingTeam, PitchingVote, PitchingFeedback

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HELPER: extract aa_source from quiz_data JSON for a given question_id
# ---------------------------------------------------------------------------
# quiz_data.questions[].id  → matches QuizAttempt.question_id
# quiz_data.questions[].aa_source → the AA we want to aggregate on

def _build_question_aa_map(quiz_data: dict | None) -> dict[str, str]:
    """Map question_id → aa_source from cached quiz_data JSON."""
    if not quiz_data:
        return {}
    mapping = {}
    for q in quiz_data.get("questions", []):
        qid = q.get("id", "")
        aa = q.get("aa_source", "")
        if qid and aa:
            mapping[qid] = aa
    return mapping


# ===========================================================================
# 1) GET /dashboard/overview
# ===========================================================================

def get_overview(session: Session, prof_id: int) -> dict[str, Any]:
    """Global dashboard stats for a professor."""

    # --- Counts by game type ---
    quiz_count = session.exec(
        select(func.count()).where(QuizSession.prof_id == prof_id)
    ).one()
    escape_count = session.exec(
        select(func.count()).where(EscapeRoom.user_id == prof_id)
    ).one()
    pitching_count = session.exec(
        select(func.count()).where(PitchingSession.prof_id == prof_id)
    ).one()

    total_sessions = quiz_count + pitching_count  # live sessions
    total_games_generated = quiz_count + escape_count + pitching_count

    # --- Participation per quiz session ---
    quiz_sessions = session.exec(
        select(QuizSession).where(QuizSession.prof_id == prof_id)
    ).all()

    participation_data = []
    for qs in quiz_sessions:
        participant_count = session.exec(
            select(func.count()).where(
                QuizParticipant.session_id == qs.id,
                QuizParticipant.is_active,
            )
        ).one()
        participation_data.append({
            "session_id": qs.id,
            "code_session": qs.code_session,
            "module_id": qs.module_id,
            "statut": qs.statut,
            "participant_count": participant_count,
            "created_at": qs.created_at.isoformat() if qs.created_at else None,
        })

    avg_participation = (
        sum(p["participant_count"] for p in participation_data) / len(participation_data)
        if participation_data else 0
    )

    # --- Pitching session participation ---
    pitching_sessions = session.exec(
        select(PitchingSession).where(PitchingSession.prof_id == prof_id)
    ).all()

    for ps in pitching_sessions:
        team_count = session.exec(
            select(func.count()).where(PitchingTeam.session_id == ps.id)  # noqa: F821 — imported above
        ).one()
        participation_data.append({
            "session_id": ps.id,
            "type": "pitching",
            "titre": ps.titre,
            "participant_count": team_count,
            "statut": ps.statut,
            "created_at": ps.created_at.isoformat() if ps.created_at else None,
        })

    # --- Bloom distribution across all modules ---
    modules = session.exec(
        select(ModuleAnalysis).where(ModuleAnalysis.user_id == prof_id)
    ).all()

    bloom_counts: dict[str, int] = {}
    for mod in modules:
        for lo in (mod.learning_outcomes or []):
            level = lo.get("bloom_level", "unknown")
            bloom_counts[level] = bloom_counts.get(level, 0) + 1

    # --- Aggregate success rate per AA across quiz sessions ---
    aa_success_rates = _compute_quiz_aa_success_rates(session, prof_id)

    return {
        "total_sessions": total_sessions,
        "total_games_generated": total_games_generated,
        "counts_by_type": {
            "quiz": quiz_count,
            "escape_room": escape_count,
            "pitching": pitching_count,
        },
        "avg_participation": round(avg_participation, 1),
        "participation_by_session": participation_data,
        "bloom_distribution": bloom_counts,
        "aa_success_rates": aa_success_rates,
    }


# ===========================================================================
# 2) GET /dashboard/sessions/{id}/details
# ===========================================================================

def get_session_details(session: Session, prof_id: int, session_id: int, session_type: str) -> dict[str, Any]:
    """Detailed results for a specific quiz or pitching session."""

    if session_type == "quiz":
        return _quiz_session_details(session, prof_id, session_id)
    elif session_type == "pitching":
        return _pitching_session_details(session, prof_id, session_id)
    else:
        return {"error": f"Type de session inconnu: {session_type}"}


def _quiz_session_details(session: Session, prof_id: int, session_id: int) -> dict:
    qs = session.get(QuizSession, session_id)
    if not qs or qs.prof_id != prof_id:
        return {"error": "Session introuvable ou accès refusé"}

    # Get module's quiz_data for AA mapping
    module = session.get(ModuleAnalysis, qs.module_id) if qs.module_id else None
    question_aa_map = _build_question_aa_map(module.quiz_data if module else None)

    # All attempts for this session
    participants = session.exec(
        select(QuizParticipant).where(QuizParticipant.session_id == session_id)
    ).all()

    participant_ids = [p.id for p in participants]
    if not participant_ids:
        return {
            "session_id": session_id,
            "type": "quiz",
            "code_session": qs.code_session,
            "statut": qs.statut,
            "module_title": module.module_title if module else None,
            "total_participants": 0,
            "aa_results": [],
            "hardest_questions": [],
            "participants": [],
        }

    attempts = session.exec(
        select(QuizAttempt).where(col(QuizAttempt.participant_id).in_(participant_ids))
    ).all()

    # --- AA success rates ---
    aa_stats: dict[str, dict] = {}  # aa_source -> {total, correct}
    question_stats: dict[str, dict] = {}  # question_id -> {total, correct}

    for attempt in attempts:
        qid = attempt.question_id
        aa = question_aa_map.get(qid, "unknown")

        if aa not in aa_stats:
            aa_stats[aa] = {"total": 0, "correct": 0}
        aa_stats[aa]["total"] += 1
        aa_stats[aa]["correct"] += 1 if attempt.est_correcte else 0

        if qid not in question_stats:
            question_stats[qid] = {"total": 0, "correct": 0}
        question_stats[qid]["total"] += 1
        question_stats[qid]["correct"] += 1 if attempt.est_correcte else 0

    aa_results = [
        {
            "aa_source": aa,
            "total_attempts": s["total"],
            "correct_count": s["correct"],
            "success_rate": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
        }
        for aa, s in sorted(aa_stats.items())
    ]

    # Hardest questions (lowest success rate, min 2 attempts)
    hardest = [
        {
            "question_id": qid,
            "aa_source": question_aa_map.get(qid, "unknown"),
            "total_attempts": s["total"],
            "error_rate": round((s["total"] - s["correct"]) / s["total"] * 100, 1) if s["total"] > 0 else 0,
        }
        for qid, s in question_stats.items()
        if s["total"] >= 2
    ]
    hardest.sort(key=lambda x: x["error_rate"], reverse=True)

    # Participants summary
    participants_summary = [
        {
            "pseudo": p.pseudo,
            "score_total": p.score_total,
            "attempts_count": len([a for a in attempts if a.participant_id == p.id]),
        }
        for p in participants
    ]

    return {
        "session_id": session_id,
        "type": "quiz",
        "code_session": qs.code_session,
        "statut": qs.statut,
        "mode": qs.mode,
        "module_title": module.module_title if module else None,
        "module_id": qs.module_id,
        "created_at": qs.created_at.isoformat() if qs.created_at else None,
        "total_participants": len(participants),
        "aa_results": aa_results,
        "hardest_questions": hardest[:10],
        "participants": participants_summary,
    }


def _pitching_session_details(session: Session, prof_id: int, session_id: int) -> dict:
    ps = session.get(PitchingSession, session_id)
    if not ps or ps.prof_id != prof_id:
        return {"error": "Session introuvable ou accès refusé"}

    teams = session.exec(
        select(PitchingTeam).where(PitchingTeam.session_id == session_id)
    ).all()

    votes = session.exec(
        select(PitchingVote).where(PitchingVote.session_id == session_id)
    ).all()

    feedbacks = session.exec(
        select(PitchingFeedback).where(PitchingFeedback.session_id == session_id)
    ).all()

    # Team rankings
    team_data = []
    for t in teams:
        team_votes = [v for v in votes if v.team_id == t.id]
        avg_score = (
            sum(v.score for v in team_votes) / len(team_votes) if team_votes else 0
        )
        team_data.append({
            "team_id": t.id,
            "nom": t.nom,
            "auteur_username": t.auteur_username,
            "vote_count": len(team_votes),
            "avg_score": round(avg_score, 2),
            "score_total": t.score_total,
            "rang": t.rang,
        })

    team_data.sort(key=lambda x: x["avg_score"], reverse=True)

    # Criteria averages across all votes
    criteria_agg: dict[str, list[int]] = {}
    for v in votes:
        if v.criteria_scores:
            for crit, val in v.criteria_scores.items():
                if crit not in criteria_agg:
                    criteria_agg[crit] = []
                criteria_agg[crit].append(val)

    criteria_averages = {
        crit: round(sum(vals) / len(vals), 2) if vals else 0
        for crit, vals in criteria_agg.items()
    }

    # Feedbacks
    feedbacks_list = [
        {
            "author": f.author_username,
            "texte": f.texte,
            "sentiment": f.sentiment,
            "team_id": f.team_id,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in feedbacks
    ]

    return {
        "session_id": session_id,
        "type": "pitching",
        "titre": ps.titre,
        "statut": ps.statut,
        "mode": ps.mode,
        "module_id": ps.module_id,
        "created_at": ps.created_at.isoformat() if ps.created_at else None,
        "teams": team_data,
        "criteria_averages": criteria_averages,
        "total_votes": len(votes),
        "total_feedbacks": len(feedbacks),
        "feedbacks": feedbacks_list,
    }


# ===========================================================================
# 3) GET /dashboard/sessions/{id}/comparison
# ===========================================================================

def get_session_comparison(session: Session, prof_id: int, session_id: int) -> dict:
    """Compare a quiz session with previous sessions on the same module."""

    qs = session.get(QuizSession, session_id)
    if not qs or qs.prof_id != prof_id:
        return {"error": "Session introuvable ou accès refusé"}

    if not qs.module_id:
        return {"error": "Pas de module associé à cette session pour comparaison"}

    # All quiz sessions on the same module, ordered by date
    all_sessions = session.exec(
        select(QuizSession)
        .where(
            QuizSession.prof_id == prof_id,
            QuizSession.module_id == qs.module_id,
        )
        .order_by(QuizSession.created_at)
    ).all()

    module = session.get(ModuleAnalysis, qs.module_id)

    # Compute AA success rates for each session
    history = []
    for s in all_sessions:
        participants = session.exec(
            select(QuizParticipant).where(QuizParticipant.session_id == s.id)
        ).all()
        participant_ids = [p.id for p in participants]
        if not participant_ids:
            history.append({
                "session_id": s.id,
                "code_session": s.code_session,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "participant_count": 0,
                "aa_results": [],
                "overall_success_rate": 0,
            })
            continue

        attempts = session.exec(
            select(QuizAttempt).where(col(QuizAttempt.participant_id).in_(participant_ids))
        ).all()

        question_aa_map = _build_question_aa_map(module.quiz_data if module else None)

        aa_stats: dict[str, dict] = {}
        total_correct = 0
        for a in attempts:
            aa = question_aa_map.get(a.question_id, "unknown")
            if aa not in aa_stats:
                aa_stats[aa] = {"total": 0, "correct": 0}
            aa_stats[aa]["total"] += 1
            aa_stats[aa]["correct"] += 1 if a.est_correcte else 0
            total_correct += 1 if a.est_correcte else 0

        aa_results = [
            {
                "aa_source": aa,
                "success_rate": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
            }
            for aa, s in sorted(aa_stats.items())
        ]

        overall = round(total_correct / len(attempts) * 100, 1) if attempts else 0

        history.append({
            "session_id": s.id,
            "code_session": s.code_session,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "participant_count": len(participants),
            "aa_results": aa_results,
            "overall_success_rate": overall,
        })

    return {
        "module_title": module.module_title if module else None,
        "module_id": qs.module_id,
        "total_sessions": len(history),
        "current_session_id": session_id,
        "history": history,
    }


# ===========================================================================
# Internal helpers
# ===========================================================================

def _compute_quiz_aa_success_rates(session: Session, prof_id: int) -> list[dict]:
    """Aggregate success rate per AA across ALL quiz sessions for this prof."""
    quiz_sessions = session.exec(
        select(QuizSession).where(QuizSession.prof_id == prof_id)
    ).all()

    global_aa: dict[str, dict] = {}

    for qs in quiz_sessions:
        module = session.get(ModuleAnalysis, qs.module_id) if qs.module_id else None
        qmap = _build_question_aa_map(module.quiz_data if module else None)

        participants = session.exec(
            select(QuizParticipant).where(QuizParticipant.session_id == qs.id)
        ).all()
        pids = [p.id for p in participants]
        if not pids:
            continue

        attempts = session.exec(
            select(QuizAttempt).where(col(QuizAttempt.participant_id).in_(pids))
        ).all()

        for a in attempts:
            aa = qmap.get(a.question_id, "unknown")
            if aa not in global_aa:
                global_aa[aa] = {"total": 0, "correct": 0}
            global_aa[aa]["total"] += 1
            global_aa[aa]["correct"] += 1 if a.est_correcte else 0

    return [
        {
            "aa_source": aa,
            "total_attempts": s["total"],
            "correct_count": s["correct"],
            "success_rate": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
        }
        for aa, s in sorted(global_aa.items())
    ]
