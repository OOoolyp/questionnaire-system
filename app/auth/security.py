import os
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("not-a-real-user-password")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")
TOKEN_SECONDS = 1800


def configure_secret(application):
    # 本机开发可临时生成；设置 JWT_SECRET 后可跨重启验证令牌。
    secret = os.getenv("JWT_SECRET")
    if secret is not None and len(secret.encode()) < 32:
        raise RuntimeError("JWT_SECRET 至少需要32字节")
    application.state.jwt_secret = secret or token_urlsafe(48)


def issue_token(user_id: str, secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(seconds=TOKEN_SECONDS)},
        secret,
        algorithm="HS256",
    )


def unauthorized():
    return HTTPException(
        status_code=401,
        detail="登录凭证无效或已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(request: Request, token: str = Depends(oauth2_scheme)) -> dict:
    try:
        claims = jwt.decode(
            token,
            request.app.state.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        subject = claims["sub"]
        if not isinstance(subject, str) or not ObjectId.is_valid(subject):
            raise unauthorized()
    except InvalidTokenError:
        raise unauthorized()
    user = request.app.state.database.users.find_one({"_id": ObjectId(subject)})
    if user is None:
        raise unauthorized()
    return user
