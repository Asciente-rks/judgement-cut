from fastapi import FastAPI
from .api.auth import router as auth_router
from .api.v1.user_routes import router as user_router
from .api.v1.admin_routes import router as admin_router
from . import db
from .core import config


def create_app() -> FastAPI:
    app = FastAPI(title="Game Deals API")
    app.include_router(user_router, prefix="/v1", tags=["user"])
    app.include_router(admin_router, prefix="/v1/admin", tags=["admin"])
    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    # internal ingestion and monitoring endpoints (protected by scraper secret)
    from .api.internal import router as internal_router
    app.include_router(internal_router, prefix="/internal", tags=["internal"])

    @app.on_event("startup")
    async def startup():
        # create tables sync then connect
        try:
            db.create_tables_sync()
        except Exception:
            # ignore creation errors in environments without DB
            pass
        await db.connect_db()
        try:
            await db.seed_initial_data()
        except Exception:
            pass

    @app.on_event("shutdown")
    async def shutdown():
        await db.disconnect_db()

    return app


app = create_app()
