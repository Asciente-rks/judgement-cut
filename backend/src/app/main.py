from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.v1.user_routes import router as user_router
from .api.v1.admin_routes import router as admin_router
from . import db
from .core import config
from .core.security import IPRateLimitMiddleware, SecurityHeadersMiddleware

# Service identifier returned by the public health probes. Kept short so it
# travels cheaply over Lambda Function URL responses.
SERVICE_NAME = "judgement-cut-backend"


def create_app() -> FastAPI:

    docs_kwargs = (
        dict(docs_url=None, redoc_url=None, openapi_url=None)
        if config.IS_PRODUCTION
        else dict()
    )
    app = FastAPI(title="Game Deals API", **docs_kwargs)

    # System Pulse pings /health as the liveness probe. Add /health (and the
    # bare-root probe) to the rate-limit exemption list so a flaky cron run
    # can't 429 the worker into a false DOWN.
    app.add_middleware(
        IPRateLimitMiddleware,
        exempt_prefixes=("/internal", "/health"),
    )

    app.add_middleware(SecurityHeadersMiddleware)

    # ------------------------------------------------------------------
    #   Liveness probe — consumed by system-pulse health-worker.
    #   Response shape mirrors swiftrace's /health: `status`, `service`,
    #   `message`, `time`. System Pulse only inspects HTTP status code so
    #   any 200 OK marks the system UP, but the body keeps us debuggable.
    # ------------------------------------------------------------------
    @app.get("/health", tags=["health"], include_in_schema=False)
    @app.get("/", tags=["health"], include_in_schema=False)
    async def health() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "status": 200,
                "service": SERVICE_NAME,
                "message": "ok",
                "time": datetime.now(timezone.utc).isoformat(),
            },
        )

    app.include_router(user_router, prefix="/v1", tags=["user"])
    app.include_router(admin_router, prefix="/v1/admin", tags=["admin"])
    app.include_router(auth_router, prefix="/auth", tags=["auth"])

    from .api.internal import router as internal_router
    app.include_router(internal_router, prefix="/internal", tags=["internal"])

    @app.on_event("startup")
    async def startup():

        try:
            db.create_tables_sync()
        except Exception:

            pass
        await db.connect_db()
        try:
            await db.seed_initial_data()
        except Exception:
            pass

    @app.on_event("shutdown")
    async def shutdown():
        await db.disconnect_db()

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app

app = create_app()
