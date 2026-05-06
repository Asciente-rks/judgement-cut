from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.v1.user_routes import router as user_router
from .api.v1.admin_routes import router as admin_router
from . import db
from .core import config
from .core.security import IPRateLimitMiddleware, SecurityHeadersMiddleware

def create_app() -> FastAPI:

    docs_kwargs = (
        dict(docs_url=None, redoc_url=None, openapi_url=None)
        if config.IS_PRODUCTION
        else dict()
    )
    app = FastAPI(title="Game Deals API", **docs_kwargs)

    app.add_middleware(IPRateLimitMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

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
