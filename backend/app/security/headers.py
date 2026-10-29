from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src 'self' data:; connect-src 'self' http://localhost:8000; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

SECURITY_HEADERS = {
    b"content-security-policy": CONTENT_SECURITY_POLICY.encode(),
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
    b"x-frame-options": b"DENY",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() not in SECURITY_HEADERS]
                headers.extend(SECURITY_HEADERS.items())
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
