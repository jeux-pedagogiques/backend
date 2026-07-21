"""Unit tests for Pitching Challenge endpoints."""

from unittest.mock import patch
from sqlmodel import Session, select
from app.models.pitching import PitchingSession
from app.models.library_item import LibraryItem


@patch("app.routers.pitching_router.generate_pitching_challenge")
def test_generate_pitching_challenge(mock_generate, client, test_module):
    mock_generate.return_value = {
        "titre_challenge": "Challenge Microservices",
        "sujet_principal": "Transformer un monolithe en microservices",
        "sujets_par_equipe": ["Équipe 1: Eureka", "Équipe 2: Docker"],
        "aa_cibles": ["Analyser le besoin de migration"],
        "criteres_vote": [{"critere": "Clarté", "description": "Présentation claire"}],
        "grille_feedback": {"points_positifs": "Bien", "axes_amelioration": "Code", "note_synthese": "A"},
        "questions_debriefing": ["Comment gérer la résilience ?"],
        "fiche_animateur": "Consignes animateur",
        "fiche_participant": "Consignes participant"
    }

    payload = {
        "module_id": test_module.id,
        "nb_equipes": 2,
        "duree_preparation": 10,
        "duree_pitch": 3,
        "duree_feedback": 5
    }

    res = client.post("/api/pitching/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["titre_challenge"] == "Challenge Microservices"
    assert data["module_id"] == test_module.id


def test_confirm_pitching_challenge(client, session: Session, test_user, test_module):
    payload = {
        "module_id": test_module.id,
        "titre_challenge": "Challenge Confirmé Microservices",
        "sujet_principal": "Sujet principal confirmé par l'utilisateur",
        "sujets_par_equipe": ["Équipe 1: Microservices", "Équipe 2: Gateway"],
        "aa_cibles": ["Analyser", "Créer"],
        "criteres_vote": [{"critere": "Qualité", "description": "Note de qualité"}],
        "grille_feedback": {"points_positifs": "Excellente analyse"},
        "questions_debriefing": ["Question de débriefing ?"],
        "fiche_animateur": "Fiche animateur...",
        "fiche_participant": "Fiche participant..."
    }

    res = client.post("/api/pitching/confirm", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "session_id" in data

    # Verify session saved in DB
    session_id = data["session_id"]
    pitch_session = session.get(PitchingSession, session_id)
    assert pitch_session is not None
    assert pitch_session.titre == "Challenge Confirmé Microservices"
    assert pitch_session.prof_id == test_user.id

    # Verify library item registered
    lib_item = session.exec(
        select(LibraryItem).where(LibraryItem.game_type == "pitching", LibraryItem.game_id == session_id)
    ).first()
    assert lib_item is not None
    assert lib_item.titre == "Challenge Confirmé Microservices"
