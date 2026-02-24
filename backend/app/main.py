import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.core.database import init_db
from app.core.seed_series import seed_series_catalog
from app.api import chat, documents, collections, ask, upload, auth, signals
from app.models.schemas import HealthResponse
from app.services.vectorstore import get_vectorstore_service

_IS_PRODUCTION = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("ENVIRONMENT") == "production"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if _IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Rate Limiter ─────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Validate OpenAI API key
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-your"):
        logger.error("❌ OPENAI_API_KEY is not set! Add it to backend/.env")
        logger.error("   Copy .env.example → .env and fill in your key")
    else:
        logger.info("✅ OpenAI API key configured")

    # Initialize database (with retries — Railway DB may need a moment)
    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e} — continuing without DB")

    # Seed series catalog from YAML
    try:
        await seed_series_catalog()
    except Exception as e:
        logger.warning(f"⚠️  Series catalog seeding failed: {e}")

    # Check Qdrant connection
    try:
        vs = get_vectorstore_service()
        if vs.is_connected():
            logger.info("✅ Qdrant connected")
        else:
            logger.warning("⚠️  Qdrant not reachable — some features may be unavailable")
    except Exception as e:
        logger.warning(f"⚠️  Qdrant check failed: {e}")

    # Run signal pipeline after data is seeded
    try:
        from app.services.quant.runner import run_signal_pipeline
        result = await run_signal_pipeline()
        logger.info(
            f"✅ Signal pipeline: {result['series_processed']} series, "
            f"{result['anomalies_found']} anomalies, "
            f"{result['duration_ms']}ms"
        )
    except Exception as e:
        logger.warning(f"⚠️  Signal pipeline failed: {e}")

    # Load ML models (reranker, changepoint, isolation forest, elastic net, topic cluster)
    try:
        from app.services.models.registry import get_registry
        registry = get_registry()
        model_results = registry.warm_all()
        ready = sum(1 for v in model_results.values() if v == "ready")
        logger.info(f"✅ ML models: {ready}/{len(model_results)} loaded — {model_results}")
    except Exception as e:
        logger.warning(f"⚠️  ML model loading failed: {e}")

    yield

    logger.info("👋 Shutting down JadwaChat")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "JadwaChat — An intelligent RAG-powered chat system for querying "
            "multiple document databases. Built for Jadwa Investment."
        ),
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url=None if _IS_PRODUCTION else "/docs",
        redoc_url=None if _IS_PRODUCTION else "/redoc",
    )

    # ─── Rate Limiter ─────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ─── Global Exception Handler ─────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error: {exc}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. Please try again."},
        )

    # ─── Security Headers ─────────────────────────────
    app.add_middleware(SecurityHeadersMiddleware)

    # ─── CORS ─────────────────────────────────────────
    origins = settings.ALLOWED_ORIGINS
    if origins == "*":
        allow_origins = ["*"]
    else:
        allow_origins = [o.strip() for o in origins.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Routers ──────────────────────────────────────
    app.include_router(auth.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(collections.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(upload.router, prefix="/api")
    app.include_router(signals.router, prefix="/api")

    # ─── Health Check ─────────────────────────────────
    @app.get("/api/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        vs = get_vectorstore_service()

        # Check DB connectivity
        db_ok = False
        try:
            from app.core.database import get_engine
            engine = await get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            pass

        return HealthResponse(
            status="healthy" if db_ok else "degraded",
            app_name=settings.APP_NAME,
            version=settings.APP_VERSION,
            qdrant_connected=vs.is_connected(),
            db_connected=db_ok,
        )

    @app.get("/", tags=["System"])
    async def root():
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
