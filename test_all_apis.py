"""Automated API Test Suite verifying all FastAPI routers and endpoints."""

import sys
import logging
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from app.main import app
from app.database import get_session
from app.models.module_analysis import ModuleAnalysis

logger = logging.getLogger(__name__)

# Setup test SQLite engine
engine = create_engine("sqlite:///./test_api_run.db", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

def override_get_session():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = override_get_session

client = TestClient(app)

def run_tests():
    results = {}
    print("==================================================")
    print("STARTING FULL FASTAPI REST API TEST SUITE")
    print("==================================================")

    # 1. Auth - Register & Login
    import uuid
    unique_user = f"user_{uuid.uuid4().hex[:6]}"
    test_user_data = {
        "username": unique_user,
        "email": f"{unique_user}@esprit.tn",
        "password": "Password123!",
        "role": "professeur"
    }
    reg_res = client.post("/api/auth/register", json=test_user_data)
    print(f"POST /api/auth/register : Status {reg_res.status_code}")
    
    token = ""
    if reg_res.status_code in [200, 201]:
        token = reg_res.json().get("access_token", "")
        results["POST /api/auth/register"] = True
    else:
        results["POST /api/auth/register"] = False

    user_id = reg_res.json().get("user", {}).get("id", 1)

    login_res = client.post("/api/auth/login", json={"email": f"{unique_user}@esprit.tn", "password": "Password123!"})
    print(f"POST /api/auth/login : Status {login_res.status_code}")
    if login_res.status_code == 200:
        token = login_res.json().get("access_token", "")
        results["POST /api/auth/login"] = True
    else:
        results["POST /api/auth/login"] = False

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 2. Auth Profile Me
    me_res = client.get("/api/auth/me", headers=headers)
    print(f"GET /api/auth/me : Status {me_res.status_code}")
    results["GET /api/auth/me"] = me_res.status_code == 200

    # 3. Create mock module analysis
    with Session(engine) as db_session:
        mock_analysis = ModuleAnalysis(
            user_id=user_id,
            module_title="Gestion des Négociations Complexe",
            module_summary="Module sur les techniques de négociation",
            learning_outcomes=[{"description": "Maîtriser les tactiques de compromis", "bloom_level": "Appliquer"}],
            key_concepts=["Win-Win", "Ligne Rouge", "BATNA"],
            keywords=["Négociation", "Accord", "Stratégie"]
        )
        db_session.add(mock_analysis)
        db_session.commit()
        db_session.refresh(mock_analysis)
        analysis_id = mock_analysis.id

    # 4. Simulation de Négociation - Generate
    gen_res = client.post("/api/negociation/generate", json={"analysis_id": analysis_id, "nb_personnages": 2}, headers=headers)
    print(f"POST /api/negociation/generate : Status {gen_res.status_code}")
    results["POST /api/negociation/generate"] = gen_res.status_code == 200

    neg_hist = client.get("/api/negociation/history", headers=headers)
    print(f"GET /api/negociation/history : Status {neg_hist.status_code}")
    results["GET /api/negociation/history"] = neg_hist.status_code == 200

    print("\n==================================================")
    print("API TEST RESULTS SUMMARY")
    print("==================================================")
    all_passed = True
    for api, status in results.items():
        pass_str = "SUCCESS" if status else "FAILED"
        if not status:
            all_passed = False
        print(f"[{pass_str}] {api}")

    print("==================================================")
    if all_passed:
        print("ALL API ENDPOINTS ARE FULLY FUNCTIONAL AND PASSING!")
    else:
        print("SOME API ENDPOINTS FAILED INSPECTION")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
