from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from huggingface_hub import HfApi

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models import User
from app.schemas import HfModelSummary, HfRepoFile


router = APIRouter()


def _api() -> HfApi:
    # One global token (MVP). If HF_TOKEN empty, public search still works.
    return HfApi(token=settings.hf_token or None)


@router.get("/models", response_model=list[HfModelSummary])
def search_models(
    q: str | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    _ = user
    limit = max(1, min(int(limit), 50))
    try:
        models = _api().list_models(
            search=q or "",
            sort="downloads",
            direction=-1,
            limit=limit,
        )
        out: list[HfModelSummary] = []
        for m in models:
            out.append(
                HfModelSummary(
                    repo_id=m.modelId,
                    likes=getattr(m, "likes", None),
                    downloads=getattr(m, "downloads", None),
                    pipeline_tag=getattr(m, "pipeline_tag", None),
                    tags=list(getattr(m, "tags", []) or []),
                )
            )
        return out
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/repo-files", response_model=list[HfRepoFile])
def repo_files(
    repo_id: str,
    only_gguf: bool = True,
    user: User = Depends(get_current_user),
):
    _ = user
    try:
        files = _api().list_repo_files(repo_id=repo_id, repo_type="model")
        if only_gguf:
            files = [f for f in files if f.lower().endswith(".gguf")]
        files.sort()
        return [HfRepoFile(filename=f) for f in files]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

