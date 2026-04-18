from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Unique email address used as the login credential.",
        examples=["alice@example.com"],
    )
    password: str = Field(
        ...,
        description="Plain-text password — minimum 8 characters. Stored as a bcrypt hash; never returned by the API.",
        examples=["secret123"],
    )

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class RegisterResponse(BaseModel):
    id: UUID = Field(..., description="Auto-generated UUID for the new user.")
    email: str = Field(..., description="Registered email address.")


class LoginRequest(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Registered email address.",
        examples=["alice@example.com"],
    )
    password: str = Field(
        ...,
        description="Plain-text password.",
        examples=["secret123"],
    )


class TokenResponse(BaseModel):
    access_token: str = Field(
        ...,
        description=(
            "JWT bearer token. Include in subsequent requests as: "
            "`Authorization: Bearer <token>`. Expires after `JWT_EXPIRE_MINUTES` minutes (default 24 h)."
        ),
    )
    token_type: str = Field(default="bearer", description="Always `bearer`.")
