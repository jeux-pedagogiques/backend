from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
import random
from datetime import datetime, timedelta
from app.models.user import User, RegistrationVerification
from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse, UserProfileUpdate
from app.services.auth_service import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services.email_service import send_verification_email

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/send-verification-code")
def send_registration_verification_code(data: UserRegister, session: Session = Depends(get_session)):
    """Send a 6-digit verification code to the user's email before creating the account."""
    email_val = data.email.strip().lower()
    username_val = data.username.strip()

    # Check if email already exists
    existing_email = session.exec(select(User).where(User.email == email_val)).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte avec cette adresse email existe déjà",
        )

    # Check if username already exists
    existing_username = session.exec(select(User).where(User.username == username_val)).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce nom d'utilisateur est déjà utilisé",
        )

    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit comporter au moins 8 caractères",
        )

    # Generate 6-digit verification code
    code = f"{random.randint(100000, 999999)}"
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Check for existing pending verification
    verification = session.exec(
        select(RegistrationVerification).where(RegistrationVerification.email == email_val)
    ).first()

    hashed_pwd = hash_password(data.password)

    user_role = data.role if data.role in ["prof", "admin", "student"] else "prof"

    if verification:
        verification.username = username_val
        verification.hashed_password = hashed_pwd
        verification.role = user_role
        verification.code = code
        verification.expires_at = expires_at
        verification.created_at = datetime.utcnow()
    else:
        verification = RegistrationVerification(
            email=email_val,
            username=username_val,
            hashed_password=hashed_pwd,
            role=user_role,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    session.commit()

    # Send verification email
    email_sent = send_verification_email(
        to_email=email_val,
        username=username_val,
        code=code
    )

    return {
        "status": "ok",
        "message": f"Code de vérification envoyé avec succès à {email_val}",
        "email": email_val,
        "email_sent": email_sent
    }


@router.post("/verify-registration", response_model=TokenResponse)
def verify_registration(data: dict, session: Session = Depends(get_session)):
    """Verify the 6-digit code and create the user account."""
    email_val = data.get("email", "").strip().lower()
    code_val = str(data.get("code", "")).strip()

    if not email_val or not code_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'adresse email et le code de vérification sont requis",
        )

    verification = session.exec(
        select(RegistrationVerification).where(RegistrationVerification.email == email_val)
    ).first()

    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune demande d'inscription en attente trouvée pour cet email",
        )

    if verification.expires_at < datetime.utcnow():
        session.delete(verification)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le code de vérification a expiré. Veuillez demander un nouveau code.",
        )

    if verification.code != code_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Code de vérification incorrect. Veuillez vérifier vos emails.",
        )

    # Check again if user already exists
    existing = session.exec(select(User).where(User.email == email_val)).first()
    if existing:
        session.delete(verification)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte avec cette adresse email existe déjà",
        )

    # Create the user account
    new_user = User(
        username=verification.username,
        email=verification.email,
        hashed_password=verification.hashed_password,
        role=verification.role,
    )
    session.add(new_user)
    session.delete(verification)
    session.commit()
    session.refresh(new_user)

    # Generate JWT token
    token = create_access_token({"sub": str(new_user.id)})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(new_user),
    )


@router.post("/resend-verification-code")
def resend_verification_code(data: dict, session: Session = Depends(get_session)):
    """Resend a new 6-digit code for pending registration."""
    email_val = data.get("email", "").strip().lower()
    if not email_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'adresse email est requise",
        )

    verification = session.exec(
        select(RegistrationVerification).where(RegistrationVerification.email == email_val)
    ).first()

    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune inscription en attente trouvée. Veuillez recommencer le formulaire.",
        )

    new_code = f"{random.randint(100000, 999999)}"
    verification.code = new_code
    verification.expires_at = datetime.utcnow() + timedelta(minutes=15)
    session.add(verification)
    session.commit()

    email_sent = send_verification_email(
        to_email=email_val,
        username=verification.username,
        code=new_code
    )

    return {
        "status": "ok",
        "message": f"Nouveau code de vérification envoyé à {email_val}",
        "email": email_val,
        "email_sent": email_sent
    }


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserRegister, session: Session = Depends(get_session)):
    """Direct registration without email verification code."""
    email_val = data.email.strip().lower()
    username_val = data.username.strip()

    # Check if email already exists
    existing_email = session.exec(select(User).where(User.email == email_val)).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte avec cette adresse email existe déjà",
        )

    # Check if username already exists
    existing_username = session.exec(select(User).where(User.username == username_val)).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce nom d'utilisateur est déjà utilisé",
        )

    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit comporter au moins 8 caractères",
        )

    user_role = data.role if data.role in ["prof", "admin", "student"] else "prof"

    # Create the user
    user = User(
        username=username_val,
        email=email_val,
        hashed_password=hash_password(data.password),
        role=user_role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Return token so user is logged in immediately after registration
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, session: Session = Depends(get_session)):
    """Authenticate a user and return a JWT token."""

    user = session.exec(select(User).where(User.email == data.email)).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/forgot-password")
def forgot_password(data: dict, session: Session = Depends(get_session)):
    """Request a password reset for a given email address."""
    email_val = data.get("email", "").strip().lower()
    if not email_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required"
        )
    user = session.exec(select(User).where(User.email == email_val)).first()
    if not user:
        # Avoid user enumeration while giving friendly feedback
        return {
            "status": "ok",
            "message": "If an account exists with this email, password reset instructions have been generated.",
            "email": email_val,
            "can_reset_directly": False
        }

    return {
        "status": "ok",
        "message": "Password reset verification initiated.",
        "email": email_val,
        "can_reset_directly": True
    }


@router.post("/reset-password")
def reset_password(data: dict, session: Session = Depends(get_session)):
    """Reset password for a user with the provided email and new password."""
    email_val = data.get("email", "").strip().lower()
    new_password = data.get("new_password", "")
    if not email_val or not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and new password are required"
        )
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )

    user = session.exec(select(User).where(User.email == email_val)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user found with this email address"
        )

    user.hashed_password = hash_password(new_password)
    session.add(user)
    session.commit()
    session.refresh(user)

    return {
        "status": "ok",
        "message": "Your password has been successfully reset. You can now log in with your new password."
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user


@router.put("/profile", response_model=UserResponse)
def update_profile(
    data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Update user profile data."""
    if data.username is not None and data.username != current_user.username:
        existing = session.exec(select(User).where(User.username == data.username)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is already taken",
            )
        current_user.username = data.username

    if data.email is not None and data.email != current_user.email:
        existing = session.exec(select(User).where(User.email == data.email)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email is already taken",
            )
        current_user.email = data.email

    # Allow optional fields to be updated or cleared (set to None)
    current_user.first_name = data.first_name
    current_user.last_name = data.last_name
    current_user.phone = data.phone
    current_user.address = data.address
    current_user.bio = data.bio
    current_user.avatar = data.avatar
    
    if data.role is not None:
        current_user.role = data.role

    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user

