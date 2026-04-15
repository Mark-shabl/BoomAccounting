from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Chat, Model, ModelDownloadJob, User
from app.db.session import get_db
from app.schemas import ModelDownloadIn, ModelDownloadJobOut, ModelOut, ModelParamsOut, ModelSettingsIn
from app.services.hf_downloader import cancel_download_job, delete_model_artifacts, start_download_job
from app.services.ollama_client import (
    delete_model_from_ollama,
    get_model_parameters,
    list_loaded_ollama,
    load_model_in_ollama,
    unload_model_from_ollama,
)


router = APIRouter()


def _resolved_model_params(model: Model) -> ModelParamsOut:
    saved = {
        "temperature": model.default_temperature,
        "num_predict": model.default_max_tokens,
        "top_p": model.default_top_p,
        "top_k": model.default_top_k,
        "repeat_penalty": model.default_repeat_penalty,
    }
    saved_present = any(v is not None for v in saved.values())

    ollama = {}
    if model.local_path:
        raw = get_model_parameters(model)
        ollama = {
            "temperature": raw.get("temperature"),
            "num_predict": raw.get("num_predict"),
            "top_p": raw.get("top_p"),
            "top_k": raw.get("top_k"),
            "repeat_penalty": raw.get("repeat_penalty"),
        }
    ollama_present = any(v is not None for v in ollama.values())

    merged = {key: saved.get(key) if saved.get(key) is not None else ollama.get(key) for key in saved}
    source = "none"
    if saved_present and ollama_present:
        source = "saved+ollama"
    elif saved_present:
        source = "saved"
    elif ollama_present:
        source = "ollama"

    return ModelParamsOut(source=source, **merged)


def _job_out(job: ModelDownloadJob) -> ModelDownloadJobOut:
    return ModelDownloadJobOut(
        id=job.id,
        model_id=job.model_id,
        status=job.status,
        progress_bytes=job.progress_bytes,
        expected_bytes=job.expected_bytes,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _cancel_job_in_db(db: Session, job: ModelDownloadJob, reason: str) -> ModelDownloadJobOut:
    model = db.get(Model, job.model_id)
    if model:
        delete_model_artifacts(model)
        model.local_path = None
        model.size_bytes = None
    job.status = "cancelled"
    job.error = reason
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_out(job)


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
            default_temperature=m.default_temperature,
            default_max_tokens=m.default_max_tokens,
            default_top_p=m.default_top_p,
            default_top_k=m.default_top_k,
            default_repeat_penalty=m.default_repeat_penalty,
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

    return _job_out(job)


@router.get("/loaded")
def list_loaded_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return model_ids currently loaded in Ollama (shared for all users)."""
    loaded_names = list_loaded_ollama()
    models = []
    for m in db.scalars(select(Model)).all():
        if any(n == f"boom-{m.id}" or n.startswith(f"boom-{m.id}:") for n in loaded_names):
            models.append({"id": m.id, "hf_repo": m.hf_repo, "hf_filename": m.hf_filename})
    return {"model_ids": [m["id"] for m in models], "models": models}


@router.get("/{model_id}/ollama-params", response_model=ModelParamsOut)
def get_ollama_params(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return model generation defaults, preferring saved app settings over Ollama parameters."""
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return _resolved_model_params(model)


@router.put("/{model_id}/settings", response_model=ModelParamsOut)
def update_model_settings(
    model_id: int,
    payload: ModelSettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    model.default_temperature = payload.temperature
    model.default_max_tokens = payload.num_predict
    model.default_top_p = payload.top_p
    model.default_top_k = payload.top_k
    model.default_repeat_penalty = payload.repeat_penalty
    db.commit()
    db.refresh(model)
    return _resolved_model_params(model)


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

    return _job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=ModelDownloadJobOut)
def cancel_model_download(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(ModelDownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download job not found")
    if job.status in ("done", "failed", "cancelled"):
        return _job_out(job)

    cancel_sent = cancel_download_job(job.id)
    if job.status == "pending":
        return _cancel_job_in_db(db, job, "Cancelled by user")
    if not cancel_sent:
        # No in-memory worker means this is a stale zombie job left after restart/crash.
        return _cancel_job_in_db(db, job, "Cancelled stale job")
    return _job_out(job)


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


@router.delete("/{model_id}")
def delete_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    active_job = db.scalars(
        select(ModelDownloadJob)
        .where(
            ModelDownloadJob.model_id == model.id,
            ModelDownloadJob.status.in_(("pending", "running")),
        )
        .order_by(desc(ModelDownloadJob.id))
    ).first()
    if active_job:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cancel download first")

    chat_count = db.scalar(select(func.count()).select_from(Chat).where(Chat.model_id == model.id)) or 0
    if chat_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model is used in chats. Delete those chats first.",
        )

    try:
        unload_model_from_ollama(model)
    except Exception:
        pass
    try:
        delete_model_from_ollama(model)
    except Exception:
        pass

    delete_model_artifacts(model)
    db.delete(model)
    db.commit()
    return {"ok": True, "model_id": model_id}


@router.get("/jobs", response_model=list[ModelDownloadJobOut])
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.scalars(select(ModelDownloadJob).order_by(desc(ModelDownloadJob.id))).all()
    return [_job_out(job) for job in jobs]

