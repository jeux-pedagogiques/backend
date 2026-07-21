"""Test configuration and fixtures for FastAPI app."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

from app.main import app
from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis


# Setup in-memory SQLite engine for tests
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="test_user")
def test_user_fixture(session: Session):
    user = User(
        id=1,
        email="prof@test.com",
        username="prof_test",
        full_name="Professeur Test",
        hashed_password="hashedpassword",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="test_module")
def test_module_fixture(session: Session, test_user: User):
    module = ModuleAnalysis(
        id=1,
        user_id=test_user.id,
        module_title="App Web Distribuées",
        original_content="Cours sur les Microservices et Docker",
        learning_outcomes=[
            {
                "id": 1,
                "description": "Analyser le besoin de migration microservices",
                "bloom_level": "analyser",
                "bloom_justification": "Justification..."
            },
            {
                "id": 2,
                "description": "Créer des microservices avec Docker",
                "bloom_level": "creer",
                "bloom_justification": "Justification..."
            }
        ],
        key_concepts=["Microservices", "Docker", "RabbitMQ"],
        keywords=["DevOps", "Containers"],
        central_notions=["Architecture distributed"]
    )
    session.add(module)
    session.commit()
    session.refresh(module)
    return module


@pytest.fixture(name="client")
def client_fixture(session: Session, test_user: User):
    def get_session_override():
        return session

    def get_current_user_override():
        return test_user

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_current_user] = get_current_user_override

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()
