"""Unit and integration tests for Storytelling Collaboratif."""

from sqlmodel import Session
from app.models.storytelling import Storytelling, StorytellingContribution
from app.services.library_service import register_library_item


def test_storytelling_model_and_library_item(session: Session, test_user, test_module):
    story = Storytelling(
        user_id=test_user.id,
        module_id=test_module.id,
        titre="Quête des Architectures Résilientes",
        contexte_depart="En 2030, le système central de la métropole subit une panne majeure...",
        mots_cles_obligatoires=["Microservices", "Load Balancer", "Circuit Breaker"],
        etapes_narratives=[
            {
                "etape": 1,
                "titre": "La Panne",
                "description": "L'incident se déclenche.",
                "consigne": "Décrivez la réaction de l'équipe d'ingénieurs.",
                "temps_minutes": 5,
            }
        ],
        roles_narratifs=[
            {
                "nom_role": "Scénariste Lead",
                "description": "Pilote l'intrigue",
                "missions": ["Garantir le rythme"],
            }
        ],
        criteres_evaluation=[
            {
                "critere": "Mobilisation technique",
                "description": "Pertinence des termes",
                "bareme": "5 pts",
            }
        ],
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    assert story.id is not None
    assert story.titre == "Quête des Architectures Résilientes"
    assert len(story.mots_cles_obligatoires) == 3

    # Test library registration
    item = register_library_item(
        session=session,
        user_id=test_user.id,
        game_type="storytelling",
        game_id=story.id,
        module_id=test_module.id,
        titre=story.titre,
        niveaux_bloom=["creer"],
        concepts_cles=story.mots_cles_obligatoires,
    )
    session.commit()

    assert item.id is not None
    assert item.game_type == "storytelling"
    assert item.game_id == story.id


def test_storytelling_endpoints(client, session: Session, test_user, test_module):
    story = Storytelling(
        user_id=test_user.id,
        module_id=test_module.id,
        titre="Histoire Collaborative Test",
        contexte_depart="Amorce de test...",
        mots_cles_obligatoires=["Algorithmique", "Complexité"],
        etapes_narratives=[
            {
                "etape": 1,
                "titre": "Introduction",
                "description": "Démarrage",
                "consigne": "Rédigez l'intro",
                "temps_minutes": 5,
            }
        ],
        roles_narratifs=[],
        criteres_evaluation=[],
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    # Get by ID
    res = client.get(f"/api/storytelling/{story.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["titre"] == "Histoire Collaborative Test"

    # Add contribution
    contrib_res = client.post(
        f"/api/storytelling/{story.id}/contribute",
        json={
            "participant_id": "part-123",
            "pseudo": "Alice",
            "etape_index": 0,
            "texte_contribution": "Alice analyse la Complexité spatiale.",
            "mots_cles_utilises": ["Complexité"],
        },
    )
    assert contrib_res.status_code == 200
    contrib_data = contrib_res.json()
    assert contrib_data["pseudo"] == "Alice"
    assert "Complexité" in contrib_data["mots_cles_utilises"]

    # List contributions
    list_res = client.get(f"/api/storytelling/{story.id}/contributions")
    assert list_res.status_code == 200
    contribs = list_res.json()
    assert len(contribs) == 1
    assert contribs[0]["pseudo"] == "Alice"
