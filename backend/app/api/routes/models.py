from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Model, ModelDownloadJob, User
from app.db.session import get_db
from app.schemas import ModelCatalogItem, ModelDownloadIn, ModelDownloadJobOut, ModelOut
from app.services.hf_downloader import start_download_job
from app.services.llm_runner import llm_runner
from app.services.model_catalog import search_catalog


router = APIRouter()


@router.get("/catalog", response_model=list[ModelCatalogItem])
def get_catalog(q: str | None = None):
    items = search_catalog(q)
    return [
        ModelCatalogItem(
            id=i.id,
            label=i.label,
            hf_repo=i.hf_repo,
            hf_filename=i.hf_filename,
            description=i.description,
        )
        for i in items
    ]


@router.get("", response_model=list[ModelOut])
def list_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Model).where(Model.owner_user_id == user.id).order_by(desc(Model.id))).all()
    return [
        ModelOut(
            id=m.id,
            hf_repo=m.hf_repo,
            hf_filename=m.hf_filename,
            local_path=m.local_path,
            size_bytes=m.size_bytes,
            created_at=m.created_at,
        )
        for m in items
    ]


@router.post("/download", response_model=ModelDownloadJobOut)
def download_model(payload: ModelDownloadIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.hf_filename.lower().endswith(".gguf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .gguf files are supported in MVP")

    model = Model(owner_user_id=user.id, hf_repo=payload.hf_repo, hf_filename=payload.hf_filename)
    db.add(model)
    db.commit()
    db.refresh(model)

    job = ModelDownloadJob(model_id=model.id, status="pending", progress_bytes=0)
    db.add(job)
    db.commit()
    db.refresh(job)

    start_download_job(job.id)

    return ModelDownloadJobOut(
        id=job.id,
        model_id=job.model_id,
        status=job.status,
        progress_bytes=job.progress_bytes,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/loaded")
def list_loaded_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return model_ids that are currently loaded in memory (only user's models)."""
    loaded_ids = llm_runner.list_loaded()
    models = []
    for mid in loaded_ids:
        m = db.get(Model, mid)
        if m and m.owner_user_id == user.id:
            models.append({"id": m.id, "hf_repo": m.hf_repo, "hf_filename": m.hf_filename})
    return {"model_ids": [m["id"] for m in models], "models": models}


@router.post("/{model_id}/load")
def load_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Preload model into memory."""
    model = db.get(Model, model_id)
    if not model or model.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if not model.local_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Model is not downloaded yet")
    llm_runner.load(model)
    return {"ok": True, "model_id": model_id}


@router.post("/{model_id}/unload")
def unload_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Unload model from memory."""
    model = db.get(Model, model_id)
    if not model or model.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    was_loaded = llm_runner.unload(model_id)
    return {"ok": True, "model_id": model_id, "was_loaded": was_loaded}


@router.get("/jobs", response_model=list[ModelDownloadJobOut])
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = (
        select(ModelDownloadJob, Model)
        .join(Model, Model.id == ModelDownloadJob.model_id)
        .where(Model.owner_user_id == user.id)
        .order_by(desc(ModelDownloadJob.id))
    )
    rows = db.execute(q).all()
    out: list[ModelDownloadJobOut] = []
    for job, _model in rows:
        out.append(
            ModelDownloadJobOut(
                id=job.id,
                model_id=job.model_id,
                status=job.status,
                progress_bytes=job.progress_bytes,
                error=job.error,
                started_at=job.started_at,
                finished_at=job.finished_at,
            )
        )
    return out

