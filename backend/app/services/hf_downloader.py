from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from huggingface_hub import hf_hub_download

from app.core.config import settings
from app.db.models import Model, ModelDownloadJob
from app.db.session import SessionLocal


def _is_gguf(filename: str) -> bool:
    return filename.lower().endswith(".gguf")


def _safe_repo_dir(repo_id: str) -> str:
    return repo_id.replace("/", "__")


def start_download_job(job_id: int) -> None:
    t = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    t.start()


def _run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(ModelDownloadJob, job_id)
        if not job:
            return
        if job.status not in ("pending", "failed"):
            return

        model = db.get(Model, job.model_id)
        if not model:
            job.status = "failed"
            job.error = "Model not found"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        if not _is_gguf(model.hf_filename):
            job.status = "failed"
            job.error = "Only .gguf files are allowed in MVP"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        job.status = "running"
        job.error = None
        job.progress_bytes = 0
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = None
        db.commit()

        os.makedirs(settings.models_dir, exist_ok=True)
        dest_dir = os.path.join(settings.models_dir, str(model.owner_user_id), _safe_repo_dir(model.hf_repo))
        os.makedirs(dest_dir, exist_ok=True)
        expected_path = os.path.join(dest_dir, model.hf_filename)

        stop_flag = {"stop": False}

        def progress_loop() -> None:
            # Use a separate DB session in this thread.
            db2 = SessionLocal()
            try:
                while not stop_flag["stop"]:
                    try:
                        if os.path.exists(expected_path):
                            size = os.path.getsize(expected_path)
                            job2 = db2.get(ModelDownloadJob, job_id)
                            if job2 and job2.status == "running":
                                job2.progress_bytes = int(size)
                                db2.commit()
                    except Exception:
                        db2.rollback()
                    time.sleep(1.0)
            finally:
                db2.close()

        progress_thread = threading.Thread(target=progress_loop, daemon=True)
        progress_thread.start()

        try:
            local_path = hf_hub_download(
                repo_id=model.hf_repo,
                filename=model.hf_filename,
                token=settings.hf_token or None,
                local_dir=dest_dir,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
        finally:
            stop_flag["stop"] = True

        final_size = None
        try:
            final_size = os.path.getsize(local_path)
        except OSError:
            pass

        model.local_path = local_path
        model.size_bytes = int(final_size) if final_size is not None else None

        job.status = "done"
        job.progress_bytes = int(final_size) if final_size is not None else job.progress_bytes
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        try:
            job = db.get(ModelDownloadJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()

