from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Model, ModelDownloadJob, User
from app.db.session import get_db
from app.schemas import ModelDownloadIn, ModelDownloadJobOut, ModelOut
from app.services.hf_downloader import start_download_job
from app.services.ollama_client import get_model_parameters, list_loaded_ollama, load_model_in_ollama, unload_model_from_ollama


router = APIRouter()


@router.get("", response_model=list[ModelOut])
def list_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Model).order_by(desc(Model.id))).all()
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

    existing = db.scalars(
        select(Model).where(
            Model.hf_repo == payload.hf_repo,
            Model.hf_filename == payload.hf_filename,
        )
    ).first()
    if existing:
        if existing.local_path:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Model already exists in library",
            )
        # Broken model (no local_path): retry download
        model = existing
    else:
        model = Model(owner_user_id=None, hf_repo=payload.hf_repo, hf_filename=payload.hf_filename)
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
    """Return model_ids currently loaded in Ollama (shared for all users)."""
    loaded_names = list_loaded_ollama()
    models = []
    for m in db.scalars(select(Model)).all():
        if any(n == f"boom-{m.id}" or n.startswith(f"boom-{m.id}:") for n in loaded_names):
            models.append({"id": m.id, "hf_repo": m.hf_repo, "hf_filename": m.hf_filename})
    return {"model_ids": [m["id"] for m in models], "models": models}


@router.get("/{model_id}/ollama-params")
def get_ollama_params(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return model parameters from Ollama (temperature, num_predict, top_p, top_k, repeat_penalty)."""
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if not model.local_path:
        return {}
    params = get_model_parameters(model)
    # Map Ollama keys to our frontend keys
    return {
        "temperature": params.get("temperature"),
        "num_predict": params.get("num_predict"),
        "top_p": params.get("top_p"),
        "top_k": params.get("top_k"),
        "repeat_penalty": params.get("repeat_penalty"),
    }


@router.post("/{model_id}/retry-download", response_model=ModelDownloadJobOut)
def retry_download_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Retry download for a model that has no local_path (broken/ghost model)."""
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if model.local_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Model already downloaded")
    if not model.hf_filename.lower().endswith(".gguf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .gguf files are supported")

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


@router.post("/{model_id}/load")
def load_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trigger Ollama to load the model into memory."""
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if not model.local_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Model is not downloaded yet")
    try:
        load_model_in_ollama(model)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return {"ok": True, "model_id": model_id}


@router.post("/{model_id}/unload")
def unload_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Unload model from Ollama memory."""
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    try:
        unload_model_from_ollama(model)
    except Exception:
        pass  # non-fatal
    return {"ok": True, "model_id": model_id, "was_loaded": False}


@router.get("/jobs", response_model=list[ModelDownloadJobOut])
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.scalars(select(ModelDownloadJob).order_by(desc(ModelDownloadJob.id))).all()
    out: list[ModelDownloadJobOut] = []
    for job in jobs:
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

