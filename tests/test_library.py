"""Unit tests for Library service and API endpoints."""

from sqlmodel import Session
from app.services.library_service import register_library_item


def test_register_library_item(session: Session, test_user, test_module):
    item = register_library_item(
        session=session,
        user_id=test_user.id,
        game_type="quiz",
        game_id=10,
        module_id=test_module.id,
        titre="Quiz Architecture",
        niveaux_bloom=["analyser", "creer"],
        concepts_cles=["Microservices", "Docker"]
    )
    session.commit()

    assert item.id is not None
    assert item.game_type == "quiz"
    assert item.game_id == 10
    assert item.titre == "Quiz Architecture"
    assert item.archived is False


def test_get_library_items_endpoint(client, session: Session, test_user, test_module):
    # Register items
    register_library_item(
        session=session,
        user_id=test_user.id,
        game_type="quiz",
        game_id=1,
        module_id=test_module.id,
        titre="Quiz Docker & Microservices",
        niveaux_bloom=["analyser"],
        concepts_cles=["Docker"]
    )
    register_library_item(
        session=session,
        user_id=test_user.id,
        game_type="escape_room",
        game_id=1,
        module_id=test_module.id,
        titre="Escape Room DevOps",
        niveaux_bloom=["creer"],
        concepts_cles=["DevOps"]
    )
    session.commit()

    # Test list without filter
    res = client.get("/api/library")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

    # Test filter by game_type
    res = client.get("/api/library?game_type=quiz")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["game_type"] == "quiz"

    # Test filter by bloom_level
    res = client.get("/api/library?bloom_level=creer")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["game_type"] == "escape_room"


def test_archive_library_item_endpoint(client, session: Session, test_user, test_module):
    register_library_item(
        session=session,
        user_id=test_user.id,
        game_type="quiz",
        game_id=1,
        module_id=test_module.id,
        titre="Quiz to Archive",
        niveaux_bloom=["memoriser"],
        concepts_cles=["Base"]
    )
    session.commit()

    # Archive item
    res = client.patch("/api/library/quiz/1/archive", json={"archived": True})
    assert res.status_code == 200
    assert res.json()["archived"] is True

    # Check that item is excluded from default list (archived=False)
    res_list = client.get("/api/library?archived=false")
    assert res_list.json()["total"] == 0

    # Check that item is present when requested archived=True
    res_archived = client.get("/api/library?archived=true")
    assert res_archived.json()["total"] == 1


def test_get_debat_and_storytelling_detail(client, session: Session, test_user, test_module):
    from app.models.debat import Debat
    from app.models.storytelling import Storytelling

    debat = Debat(
        user_id=test_user.id,
        module_id=test_module.id,
        problematique="L'IA va-t-elle remplacer les développeurs ?",
        camp_pour=["Productivité x10", "Automatisation"],
        camp_contre=["Créativité humaine", "Bugs complexes"],
        roles=[{"nom_role": "Avocat IA", "description": "Défendre l'adoption"}]
    )
    session.add(debat)

    story = Storytelling(
        user_id=test_user.id,
        module_id=test_module.id,
        titre="The Nomad's Dilemma",
        contexte_depart="Une équipe distribuée face à un bug critique.",
        mots_cles_obligatoires=["Docker", "Microservices"],
        etapes_narratives=[{"numero_etape": 1, "titre": "Découverte", "consigne": "Raconter le premier incident."}],
        roles_narratifs=[{"nom_role": "Lead Dev", "mission": "Coordonner l'équipe"}]
    )
    session.add(story)
    session.commit()
    session.refresh(debat)
    session.refresh(story)

    # Test auto-sync on list
    res_list = client.get("/api/library")
    assert res_list.status_code == 200
    types = [i["game_type"] for i in res_list.json()["items"]]
    assert "debat" in types
    assert "storytelling" in types

    # Test detail Debat
    res_debat = client.get(f"/api/library/debat/{debat.id}")
    assert res_debat.status_code == 200
    d_data = res_debat.json()
    assert d_data["problematique"] == "L'IA va-t-elle remplacer les développeurs ?"
    assert len(d_data["camp_pour"]) == 2

    # Test detail Storytelling
    res_story = client.get(f"/api/library/storytelling/{story.id}")
    assert res_story.status_code == 200
    s_data = res_story.json()
    assert s_data["titre"] == "The Nomad's Dilemma"
    assert len(s_data["etapes_narratives"]) == 1

