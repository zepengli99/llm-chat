import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    response_description="The newly created user's ID and email.",
    responses={
        409: {"description": "Email already registered."},
        422: {"description": "Validation error — invalid email format or password too short (< 8 chars)."},
    },
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new user account.

    - **email**: must be a valid email address and globally unique.
    - **password**: minimum 8 characters; stored as a bcrypt hash — never returned by the API.

    Returns the new user's `id` and `email`. Use `POST /auth/login` to obtain a JWT token.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("registered new user: %s (id=%s)", user.email, user.id)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and obtain a JWT token",
    response_description="A bearer token valid for `JWT_EXPIRE_MINUTES` minutes (default 24 h).",
    responses={
        401: {"description": "Wrong email or password."},
    },
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with email and password.

    Returns a **JWT bearer token**. Include it in subsequent requests as:

    ```
    Authorization: Bearer <access_token>
    ```

    The token expires after `JWT_EXPIRE_MINUTES` minutes (default: 1440 = 24 h).
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        logger.warning("failed login attempt for %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    logger.info("user logged in: %s (id=%s)", user.email, user.id)
    return TokenResponse(access_token=create_access_token(str(user.id)))
