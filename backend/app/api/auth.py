from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Tenant, User
from app.db.session import engine

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash("unused-password-for-timing")
jwt_secret = settings.auth_jwt_secret.get_secret_value()
jwt_issuer = "enterprise-knowledge-copilot"

active_users = (
    select(User)
    .join(Tenant, Tenant.id == User.tenant_id)
    .where(User.status == "ACTIVE", Tenant.status == "ACTIVE")
)


class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    department_id: UUID | None
    email: str
    display_name: str


def unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login")
def login(data: LoginRequest) -> TokenResponse:
    with Session(engine) as session:
        user = session.scalar(
            active_users.where(
                Tenant.slug == data.tenant_slug.strip().lower(),
                User.email == data.email.strip().lower(),
            )
        )
        stored_hash = user.password_hash if user else None
        valid_password = password_hasher.verify(
            data.password, stored_hash or dummy_hash
        )

        if user is None or not stored_hash or not valid_password:
            raise unauthorized("Invalid credentials")

        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": str(user.id),
                "iss": jwt_issuer,
                "iat": now,
                "exp": now + timedelta(minutes=30),
            },
            jwt_secret,
            algorithm="HS256",
        )
        return TokenResponse(access_token=token)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    if credentials is None:
        raise unauthorized("Missing access token")

    try:
        claims = jwt.decode(
            credentials.credentials,
            jwt_secret,
            algorithms=["HS256"],
            issuer=jwt_issuer,
            options={"require": ["sub", "iss", "iat", "exp"]},
        )
        user_id = UUID(claims["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise unauthorized("Invalid access token") from exc

    with Session(engine) as session:
        user = session.scalar(active_users.where(User.id == user_id))
        if user is None:
            raise unauthorized("Invalid access token")
        return CurrentUser.model_validate(user)

@router.get("/me")
def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    return current_user