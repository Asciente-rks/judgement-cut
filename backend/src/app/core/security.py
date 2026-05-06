
from __future__ import annotations

import asyncio
import collections
import time
from typing import Deque, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",

    "X-XSS-Protection": "0",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cross-Origin-Opener-Policy": "same-origin",
}

class SecurityHeadersMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():

            response.headers.setdefault(key, value)

        response.headers["Server"] = "JudgementCut"
        return response

_lock = asyncio.Lock()

class IPRateLimitMiddleware:

    def __init__(
        self,
        app,
        login_limit: int = 5,
        login_window: int = 60,
        global_limit: int = 120,
        global_window: int = 60,
        exempt_prefixes: Tuple[str, ...] = ("/internal",),
    ) -> None:
        self.app = app
        self.login_limit = login_limit
        self.login_window = login_window
        self.global_limit = global_limit
        self.global_window = global_window
        self.exempt_prefixes = exempt_prefixes
        self._buckets: Dict[Tuple[str, str], Deque[float]] = (
            collections.defaultdict(collections.deque)
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "").upper()

        if any(path.startswith(p) for p in self.exempt_prefixes):
            await self.app(scope, receive, send)
            return

        ip = self._client_ip(scope)
        is_login = path == "/auth/login" and method == "POST"

        bucket_kind = "login" if is_login else "global"
        limit = self.login_limit if is_login else self.global_limit
        window = self.login_window if is_login else self.global_window

        async with _lock:
            now = time.time()
            bucket = self._buckets[(ip, bucket_kind)]

            while bucket and bucket[0] < now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(window - (now - bucket[0])) if bucket else window
                response = JSONResponse(
                    {"detail": "Too many requests. Please slow down."},
                    status_code=429,
                    headers={
                        "Retry-After": str(max(1, retry_after)),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
                await response(scope, receive, send)
                return
            bucket.append(now)

        await self.app(scope, receive, send)

    @staticmethod
    def _client_ip(scope) -> str:

        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                first = value.decode("latin-1").split(",")[0].strip()
                if first:
                    return first
        client = scope.get("client") or ("unknown", 0)
        return client[0] or "unknown"
