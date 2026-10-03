from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.database.models import User
from app.schemas.auth import UserCreate, UserOut, LoginRequest, Token
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.deps import get_current_user
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.audit.service import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

VALID_ROLES = ["ADMIN", "INVESTIGATOR", "SECURITY_OFFICER", "REVIEWER"]

_login_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)


def _login_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client is not None else "unknown"
    return f"login:{ip}:{email.lower()}"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    role = payload.role or "INVESTIGATOR"
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {VALID_ROLES}")

    user = User(
        email=payload.email.lower(),
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, "user_register", user_id=user.id, entity_type="user", entity_id=user.id, details=f"role={role}")
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if settings.LOGIN_RATE_LIMIT_ENABLED:
        key = _login_key(request, payload.email)
        if not _login_limiter.check(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts; retry in {_login_limiter.retry_after(key)}s",
                headers={"Retry-After": str(_login_limiter.retry_after(key))},
            )

    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        if settings.LOGIN_RATE_LIMIT_ENABLED:
            _login_limiter.hit(_login_key(request, payload.email))
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    if settings.LOGIN_RATE_LIMIT_ENABLED:
        _login_limiter.reset(_login_key(request, payload.email))

    token = create_access_token(user.id, user.role)
    record_audit(db, "login", user_id=user.id, entity_type="user", entity_id=user.id)
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # JWT is stateless; logging out means the client discards the token.
    record_audit(db, "logout", user_id=current_user.id, entity_type="user", entity_id=current_user.id)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
