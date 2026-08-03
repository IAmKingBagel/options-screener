"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chain import router as chain_router
from app.api.routes_health import router as health_router
from app.api.routes_screen import router as screen_router
from app.api.routes_tracking import router as tracking_router
from app.api.routes_volatility import router as volatility_router
from app.config import get_settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Options Screener API",
        description=(
            "Personal quantitative options screener for swing-trade candidate discovery. "
            "Not financial advice."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(chain_router)
    app.include_router(volatility_router)
    app.include_router(screen_router)
    app.include_router(tracking_router)

    @app.get("/")
    def root() -> dict:
        return {
            "message": "Options Screener API",
            "health": "/health",
            "chain": "/api/chain/{symbol}",
            "volatility": "/api/volatility/{symbol}",
            "screen": "POST /api/screen",
            "tracking": "/api/tracking",
            "data_warning": settings.data_delay_warning,
        }

    return app


app = create_app()
