import secrets
import time

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response

log = structlog.get_logger()

STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "deflake"


def new_request_id() -> str:
    return f"req_{secrets.token_hex(6)}"


class RequestContextMiddleware:
    """Assigns a request ID, logs one line per request, and turns crashes into the error shape."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled_error", path=scope.get("path"))
            if not response_started:
                response = error_response(
                    500, "internal_error", "Something went wrong on our side.", request_id
                )
                await response(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.clear_contextvars()


class CsrfHeaderMiddleware:
    """Requires X-Requested-With: deflake on every state-changing API request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in STATE_CHANGING_METHODS
            and scope["path"].startswith("/api/")
        ):
            request = Request(scope)
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                response = error_response(
                    403, "csrf_header_missing", "This request is missing a required header.",
                    scope.get("state", {}).get("request_id"),
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
