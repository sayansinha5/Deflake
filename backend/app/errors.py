import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()

_STATUS_DEFAULTS = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthenticated", "Sign in to continue."),
    403: ("forbidden", "You don't have permission to do that."),
    404: ("not_found", "Not found."),
    405: ("method_not_allowed", "This method is not allowed here."),
    409: ("conflict", "The request conflicts with the current state."),
    413: ("payload_too_large", "The upload is too large."),
    429: ("rate_limited", "Too many requests. Try again later."),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(status: int, code: str, message: str, request_id: str | None,
                   extra: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id, **(extra or {})}}
    return JSONResponse(status_code=status, content=body)


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, request_id_of(request), exc.extra)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _STATUS_DEFAULTS.get(exc.status_code, ("error", "The request failed."))
    return error_response(exc.status_code, code, message, request_id_of(request))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) or "body"
                     for e in exc.errors()})
    return error_response(
        422, "invalid_request", "Some fields are missing or invalid.",
        request_id_of(request), {"fields": fields},
    )


async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    path = request.url.path
    if path.endswith("/auth/register"):
        message = "Too many attempts. Try again in a few minutes."
        code = "too_many_attempts"
    elif path.endswith("/repos/import"):
        message = "You've imported 10 repositories in the last hour. Try again later."
        code = "too_many_imports"
    elif "/github/oauth/start" in path:
        message = "You've started GitHub connect too many times. Try again later."
        code = "too_many_oauth_starts"
    elif path.endswith("/sync"):
        message = "You've synced 20 repositories in the last hour. Try again later."
        code = "too_many_syncs"
    elif "/repos/" in path and path.endswith("/runs"):
        message = "You've started 10 scans in the last hour. Try again later."
        code = "too_many_runs"
    else:
        code, message = _STATUS_DEFAULTS[429]
    return error_response(429, code, message, request_id_of(request))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(RateLimitExceeded, _rate_limited)
