"""Unit tests for Atelier Feedback Pair module."""

import pytest
from unittest.mock import patch, AsyncMock
from sqlmodel import Session, select

from app.models.atelier_feedback import AtelierFeedback, PresentationAtelier, FeedbackRecu
from app.services.socket_service import (
    on_atelier_launch,
    on_atelier_start_presentation,
    on_atelier_submit_feedback,
    on_atelier_show_aggregated
)


@pytest.mark.asyncio
@patch("app.routers.atelier_feedback_router.generate_atelier_feedback")
async def test_generate_atelier_feedback_endpoint(mock_generate, client, test_module):
    mock_generate.return_value = {
        "titre": "Atelier Feedback Microservices",
        "criteres": [
            {"nom": "Clarté", "description": "Présentation des concepts", "ponderation": 1.0},
            {"nom": "Architecture", "description": "Qualité du découpage", "ponderation": 1.0}
        ],
        "structure_grille": {
            "note_min": 1,
            "note_max": 5,
            "sections": ["points_positifs", "axes_amelioration", "note_synthese"],
            "consignes": "Évaluez avec bienveillance."
        }
    }

    payload = {
        "module_id": test_module.id,
        "titre": "Atelier Feedback Microservices",
        "anonyme": True,
        "nb_criteres": 2
    }

    res = client.post("/atelier-feedback/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["titre"] == "Atelier Feedback Microservices"
    assert data["module_id"] == test_module.id
    assert data["anonyme"] is True
    assert len(data["criteres"]) == 2


@pytest.mark.asyncio
async def test_socket_atelier_flow_and_anonymity(session: Session, test_module):
    from tests.conftest import engine as test_engine
    from sqlmodel import SQLModel
    import app.models  # Ensures all models are registered in SQLModel.metadata

    SQLModel.metadata.create_all(test_engine)

    # 1. Create AtelierFeedback record in DB

    atelier = AtelierFeedback(
        module_id=test_module.id,
        titre="Atelier Test Socket",
        criteres=[{"nom": "Pertinence", "description": "Description"}],
        structure_grille={"note_min": 1, "note_max": 5},
        anonyme=True
    )
    session.add(atelier)
    session.commit()
    session.refresh(atelier)

    # Patch socketio emit and Session to use fixture session
    with patch("app.services.socket_service.sio.emit", new_callable=AsyncMock) as mock_emit, \
         patch("app.services.socket_service.Session", return_value=session):
        # 2. Test atelier:launch

        launch_res = await on_atelier_launch("sid_prof", {
            "session_code": "123456",
            "atelier_feedback_id": atelier.id,
            "presentations": [
                {"participant_ou_groupe_id": "groupe_1", "nom_presentateur": "Équipe Alpha", "ordre_passage": 1},
                {"participant_ou_groupe_id": "groupe_2", "nom_presentateur": "Équipe Beta", "ordre_passage": 2}
            ]
        })
        assert launch_res["status"] == "success", f"Error message: {launch_res.get('message')}"



        presentations = launch_res["atelier"]["presentations"]
        assert len(presentations) == 2
        pres_1_id = presentations[0]["id"]

        # 3. Test atelier:start_presentation
        start_res = await on_atelier_start_presentation("sid_prof", {
            "session_code": "123456",
            "presentation_id": pres_1_id
        })
        assert start_res["status"] == "success"
        assert start_res["presentation"]["statut"] == "en_cours"

        # 4. Test atelier:submit_feedback (with anonyme=True)
        sub_res_1 = await on_atelier_submit_feedback("sid_student_1", {
            "session_code": "123456",
            "presentation_id": pres_1_id,
            "evaluateur_id": "student_secret_id_1",
            "notes_par_critere": {"Pertinence": 4.5},
            "points_positifs": "Super explications !",
            "axes_amelioration": "Parler un peu plus fort.",
            "note_synthese": 4.5
        })
        assert sub_res_1["status"] == "success"

        sub_res_2 = await on_atelier_submit_feedback("sid_student_2", {
            "session_code": "123456",
            "presentation_id": pres_1_id,
            "evaluateur_id": "student_secret_id_2",
            "notes_par_critere": {"Pertinence": 3.5},
            "points_positifs": "Bonne structure",
            "axes_amelioration": "Ajouter des schémas",
            "note_synthese": 3.5
        })
        assert sub_res_2["status"] == "success"

        # Verify DB anonymity: evaluateur_id must be NULL for both feedback submissions
        fb_records = session.exec(select(FeedbackRecu).where(FeedbackRecu.presentation_id == pres_1_id)).all()
        assert len(fb_records) == 2
        for fb in fb_records:
            assert fb.evaluateur_id is None

        # 5. Test atelier:show_aggregated
        agg_res = await on_atelier_show_aggregated("sid_prof", {
            "session_code": "123456",
            "presentation_id": pres_1_id
        })
        assert agg_res["status"] == "success"
        aggregated = agg_res["aggregated"]
        assert aggregated["total_feedbacks"] == 2
        assert aggregated["moyenne_note_synthese"] == 4.0
        assert aggregated["moyennes_par_critere"]["Pertinence"] == 4.0

        # Verify response anonymity: evaluateur_id must be None in broadcast payload
        for f_item in aggregated["feedbacks"]:
            assert f_item["evaluateur_id"] is None


def test_rest_results_and_pdf_export(client, session: Session, test_module):
    # Setup data
    atelier = AtelierFeedback(
        module_id=test_module.id,
        titre="Atelier REST Test",
        criteres=[{"nom": "Maîtrise", "description": "Contenu"}],
        anonyme=True
    )
    session.add(atelier)
    session.commit()
    session.refresh(atelier)

    pres = PresentationAtelier(
        session_id=10,
        atelier_feedback_id=atelier.id,
        participant_ou_groupe_id="groupe_devops",
        nom_presentateur="Groupe DevOps",
        ordre_passage=1
    )
    session.add(pres)
    session.commit()
    session.refresh(pres)

    fb1 = FeedbackRecu(
        presentation_id=pres.id,
        evaluateur_id=None,
        notes_par_critere={"Maîtrise": 5.0},
        points_positifs="Excellente démo",
        axes_amelioration="Rien à signaler",
        note_synthese=5.0
    )
    session.add(fb1)
    session.commit()

    # Test GET results
    res_results = client.get(f"/atelier-feedback/10/results/{pres.id}")
    assert res_results.status_code == 200
    res_data = res_results.json()
    assert res_data["nom_presentateur"] == "Groupe DevOps"
    assert res_data["total_feedbacks"] == 1
    assert res_data["moyenne_note_synthese"] == 5.0
    assert res_data["feedbacks"][0]["evaluateur_id"] is None

    # Test GET export-pdf
    res_pdf = client.get(f"/atelier-feedback/10/export-pdf/{pres.id}")
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF")
