from pydantic import BaseModel, EmailStr


class UserRegister(BaseModel):
    """Schema for user registration requests."""

    username: str
    email: EmailStr
    password: str
    role: str = "student"


class UserLogin(BaseModel):
    """Schema for user login requests."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user data returned to the client (no password)."""

    id: int
    username: str
    email: str
    is_active: bool
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    address: str | None = None
    bio: str | None = None
    avatar: str | None = None
    role: str

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    """Schema for user profile update requests."""

    username: str | None = None
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    address: str | None = None
    bio: str | None = None
    avatar: str | None = None
    role: str | None = None



class TokenResponse(BaseModel):
    """Schema for JWT token responses."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
