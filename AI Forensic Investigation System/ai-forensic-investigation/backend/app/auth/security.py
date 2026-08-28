import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from jwt import PyJWTError

from app.core.config import settings


def hash_password(password: str) -> str:
    """Hash a password using bcrypt directly (avoids passlib/bcrypt incompat)."""
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, role: str, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = {"sub": str(user_id), "role": role}
    expire = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = datetime.now(timezone.utc) + expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except PyJWTError:
        return None
