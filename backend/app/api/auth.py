"""
Authentication endpoints — register, login, me.
"""

import logging

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field

from app.core.database import User, get_session_factory
from app.core.deps import require_user
from app.services.auth import authenticate_user, create_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


# ─── Schemas ──────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool


# ─── Endpoints ────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest):
    """Create a new user account."""
    factory = await get_session_factory()
    async with factory() as session:
        try:
            user = await create_user(
                email=req.email,
                password=req.password,
                full_name=req.full_name,
                session=session,
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

        token = create_access_token(data={"sub": str(user.id)})
        logger.info(f"User registered: {user.email}")
        return TokenResponse(
            access_token=token,
            user={
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
            },
        )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate and return a JWT token."""
    factory = await get_session_factory()
    async with factory() as session:
        user = await authenticate_user(req.email, req.password, session)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        token = create_access_token(data={"sub": str(user.id)})
        logger.info(f"User logged in: {user.email}")
        return TokenResponse(
            access_token=token,
            user={
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
            },
        )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_user)):
    """Get current authenticated user."""
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )

