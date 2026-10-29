import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import RevokedSession, User, utcnow
from app.errors import ApiError
from app.schemas.auth import MeOut, PasswordChangeIn, RegisterIn, SignInIn
from app.security import audit
from app.security.auth import COOKIE_NAME, COOKIE_PATH, cookie_kwargs, decode_token, issue_token
from app.security.passwords import hash_password, password_problem, verify_password
from app.security.ratelimit import REGISTER_LIMIT, limiter, signin_failures

router = APIRouter(prefix="/auth", tags=["auth"])

ACCOUNT_MAX_FAILURES = 10
ACCOUNT_WINDOW = timedelta(minutes=15)
ACCOUNT_LOCK = timedelta(minutes=15)

INCORRECT = "Email or password is incorrect."
REGISTER_FAILED = (
    "We couldn't create an account with these details. If you already have one, sign in."
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(minutes: int) -> ApiError:
    unit = "minute" if minutes == 1 else "minutes"
    return ApiError(
        429, "too_many_attempts", f"Too many attempts. Try again in {minutes} {unit}.",
        {"retry_after_minutes": minutes},
    )


def _me(user: User, expires_at: datetime) -> MeOut:
    return MeOut(
        id=user.id, full_name=user.full_name, email=user.email, role=user.role,
        is_admin=user.role == "owner", expires_at=expires_at,
    )


def _start_session(response: Response, settings: Settings, user: User) -> datetime:
    token, claims = issue_token(settings, user.id, is_admin=user.role == "owner")
    response.set_cookie(
        value=token, max_age=settings.jwt_ttl_minutes * 60, **cookie_kwargs(settings)
    )
    return claims.expires_at


def _register_account_failure(user: User, now: datetime) -> None:
    if user.first_failed_at is None or now - user.first_failed_at >= ACCOUNT_WINDOW:
        user.first_failed_at = now
        user.failed_attempts = 0
    user.failed_attempts += 1
    if user.failed_attempts >= ACCOUNT_MAX_FAILURES:
        user.locked_until = now + ACCOUNT_LOCK
        user.failed_attempts = 0
        user.first_failed_at = None


@router.post("/session", status_code=204)
async def sign_in(
    body: SignInIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> Response:
    ip = _client_ip(request)
    if (minutes := signin_failures.retry_after_minutes(ip)) is not None:
        raise _too_many(minutes)

    now = utcnow()
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    password_ok = verify_password(user.password_hash if user else None, body.password)

    if user is not None and user.locked_until is not None and user.locked_until > now:
        audit.record(db, settings, "sign_in", "locked", user.id, ip)
        await db.commit()
        raise _too_many(max(1, math.ceil((user.locked_until - now).total_seconds() / 60)))

    if not password_ok or user is None or not user.is_active:
        signin_failures.record_failure(ip)
        if user is not None:
            _register_account_failure(user, now)
        audit.record(db, settings, "sign_in", "failed", user.id if user else None, ip)
        await db.commit()
        raise ApiError(401, "invalid_credentials", INCORRECT)

    user.failed_attempts = 0
    user.first_failed_at = None
    user.locked_until = None
    user.last_login_at = now
    audit.record(db, settings, "sign_in", "success", user.id, ip)
    await db.commit()
    _start_session(response, settings, user)
    response.status_code = 204
    return response


@router.delete("/session", status_code=204)
async def sign_out(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            claims = decode_token(settings, token)
        except Exception:
            claims = None
        if claims is not None:
            exists = await db.get(RevokedSession, claims.jti)
            if exists is None:
                db.add(RevokedSession(
                    jti=claims.jti, user_id=claims.user_id,
                    expires_at=claims.expires_at.astimezone(UTC).replace(tzinfo=None),
                ))
                audit.record(db, settings, "sign_out", "success", claims.user_id,
                             _client_ip(request))
                await db.commit()
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
async def me(session: CurrentSession = Depends(current_session)) -> MeOut:
    return _me(session.user, session.claims.expires_at)


@router.post("/register", status_code=201, response_model=MeOut)
@limiter.limit(REGISTER_LIMIT)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> MeOut:
    ip = _client_ip(request)
    if not settings.signup_enabled:
        raise ApiError(403, "signup_closed",
                       "Sign-up is closed. Ask the workspace owner for access.")
    if problem := password_problem(body.password, settings.password_min_length):
        raise ApiError(400, "weak_password", problem, {"fields": ["password"]})

    email = body.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        audit.record(db, settings, "register", "failed", None, ip)
        await db.commit()
        raise ApiError(400, "registration_failed", REGISTER_FAILED)

    user = User(
        email=email, full_name=body.full_name, password_hash=hash_password(body.password),
        role="member", last_login_at=utcnow(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ApiError(400, "registration_failed", REGISTER_FAILED) from None
    audit.record(db, settings, "register", "success", user.id, ip)
    await db.commit()
    expires_at = _start_session(response, settings, user)
    return _me(user, expires_at)


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> Response:
    user = await db.get(User, session.user.id)
    ip = _client_ip(request)
    if user is None or not verify_password(user.password_hash, body.current_password):
        audit.record(db, settings, "password_change", "failed", session.user.id, ip)
        await db.commit()
        raise ApiError(400, "current_password_incorrect", "Current password is incorrect.",
                       {"fields": ["current_password"]})
    if problem := password_problem(body.new_password, settings.password_min_length):
        raise ApiError(400, "weak_password", problem, {"fields": ["new_password"]})

    user.password_hash = hash_password(body.new_password)
    user.sessions_valid_after = utcnow()
    audit.record(db, settings, "password_change", "success", user.id, ip)
    await db.commit()
    _start_session(response, settings, user)
    response.status_code = 204
    return response
