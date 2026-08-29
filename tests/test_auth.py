"""Unit tests for authentication, email verification code, forgot-password, and reset-password endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models.user import User, RegistrationVerification
from app.services.auth_service import verify_password


def test_forgot_password_valid_and_invalid_user(client: TestClient, session: Session, test_user: User):
    # Valid existing user
    response = client.post("/api/auth/forgot-password", json={"email": "prof@test.com"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["can_reset_directly"] is True

    # Non-existing user
    response_unknown = client.post("/api/auth/forgot-password", json={"email": "unknown@example.com"})
    assert response_unknown.status_code == 200
    data_unknown = response_unknown.json()
    assert data_unknown["status"] == "ok"
    assert data_unknown["can_reset_directly"] is False


def test_reset_password_success(client: TestClient, session: Session, test_user: User):
    # Reset password for valid user
    response = client.post("/api/auth/reset-password", json={
        "email": "prof@test.com",
        "new_password": "newSecurePassword123!"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

    # Verify updated password in database
    session.refresh(test_user)
    assert verify_password("newSecurePassword123!", test_user.hashed_password)


def test_signup_email_verification_flow(client: TestClient, session: Session):
    # 1. Send verification code
    payload = {
        "username": "new_student",
        "email": "student.new@esprit.tn",
        "password": "strongPassword2026!",
        "role": "student"
    }
    send_res = client.post("/api/auth/send-verification-code", json=payload)
    assert send_res.status_code == 200
    send_data = send_res.json()
    assert send_data["status"] == "ok"

    # 2. Check that pending verification exists in database
    verification = session.exec(
        select(RegistrationVerification).where(RegistrationVerification.email == "student.new@esprit.tn")
    ).first()
    assert verification is not None
    code = verification.code
    assert len(code) == 6

    # 3. Test wrong code fails
    fail_res = client.post("/api/auth/verify-registration", json={
        "email": "student.new@esprit.tn",
        "code": "000000"
    })
    assert fail_res.status_code == 400

    # 4. Test correct code succeeds and returns access_token
    success_res = client.post("/api/auth/verify-registration", json={
        "email": "student.new@esprit.tn",
        "code": code
    })
    assert success_res.status_code == 200
    success_data = success_res.json()
    assert "access_token" in success_data
    assert success_data["user"]["email"] == "student.new@esprit.tn"
    assert success_data["user"]["username"] == "new_student"

    # 5. Check user was saved in DB and verification was removed
    created_user = session.exec(
        select(User).where(User.email == "student.new@esprit.tn")
    ).first()
    assert created_user is not None
    assert verify_password("strongPassword2026!", created_user.hashed_password)

    remaining_verification = session.exec(
        select(RegistrationVerification).where(RegistrationVerification.email == "student.new@esprit.tn")
    ).first()
    assert remaining_verification is None
