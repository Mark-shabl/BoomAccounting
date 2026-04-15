import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.core.config import settings
from app.db.models import Base, ModelDownloadJob
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)


app = FastAPI(title="Boom WebUI API", version="0.1.0")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


def _apply_runtime_schema_fixes():
    """Keep older dev databases compatible with the current code."""
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("model_download_jobs")}
    except Exception:
        columns = set()

    if "model_download_jobs" in inspector.get_table_names() and "expected_bytes" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE model_download_jobs ADD COLUMN expected_bytes BIGINT NULL"))

    try:
        model_columns = {col["name"] for col in inspector.get_columns("models")}
    except Exception:
        model_columns = set()

    if "models" in inspector.get_table_names():
        alter_statements = []
        if "default_temperature" not in model_columns:
            alter_statements.append("ALTER TABLE models ADD COLUMN default_temperature DOUBLE NULL")
        if "default_max_tokens" not in model_columns:
            alter_statements.append("ALTER TABLE models ADD COLUMN default_max_tokens INTEGER NULL")
        if "default_top_p" not in model_columns:
            alter_statements.append("ALTER TABLE models ADD COLUMN default_top_p DOUBLE NULL")
        if "default_top_k" not in model_columns:
            alter_statements.append("ALTER TABLE models ADD COLUMN default_top_k INTEGER NULL")
        if "default_repeat_penalty" not in model_columns:
            alter_statements.append("ALTER TABLE models ADD COLUMN default_repeat_penalty DOUBLE NULL")
        if alter_statements:
            with engine.begin() as conn:
                for stmt in alter_statements:
                    conn.execute(text(stmt))


def _reconcile_interrupted_downloads():
    """Downloads do not survive backend restarts; mark them so UI stays honest."""
    db = SessionLocal()
    try:
        interrupted = (
            db.query(ModelDownloadJob)
            .filter(ModelDownloadJob.status.in_(("pending", "running")))
            .all()
        )
        if not interrupted:
            return
        for job in interrupted:
            job.status = "failed"
            job.error = "Download interrupted by backend restart. Retry download."
            if job.finished_at is None:
                job.finished_at = job.started_at
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    # MVP: auto-create tables so `docker compose up` works without running Alembic manually.
    Base.metadata.create_all(bind=engine)
    _apply_runtime_schema_fixes()
    _reconcile_interrupted_downloads()


@app.get("/health")
def health():
    return {"ok": True}

