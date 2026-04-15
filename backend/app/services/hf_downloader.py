from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
from tqdm import tqdm

from app.core.config import settings
from app.db.models import Model, ModelDownloadJob
from app.db.session import SessionLocal
from app.services.ollama_client import register_model_in_ollama

# Throttle DB updates: every N bytes or N seconds
_PROGRESS_UPDATE_INTERVAL_BYTES = 512 * 1024  # 512 KB
_PROGRESS_UPDATE_INTERVAL_SEC = 1.0
_CANCEL_EVENTS: dict[int, threading.Event] = {}
_CANCEL_EVENTS_LOCK = threading.Lock()


class DownloadCancelledError(RuntimeError):
    pass


def _register_cancel_event(job_id: int) -> threading.Event:
    with _CANCEL_EVENTS_LOCK:
        evt = _CANCEL_EVENTS.get(job_id)
        if evt is None:
            evt = threading.Event()
            _CANCEL_EVENTS[job_id] = evt
        return evt


def _clear_cancel_event(job_id: int) -> None:
    with _CANCEL_EVENTS_LOCK:
        _CANCEL_EVENTS.pop(job_id, None)


def cancel_download_job(job_id: int) -> bool:
    with _CANCEL_EVENTS_LOCK:
        evt = _CANCEL_EVENTS.get(job_id)
    if evt is None:
        return False
    evt.set()
    return True


def _make_progress_tqdm(job_id: int, cancel_event: threading.Event):
    """Factory for tqdm class that updates progress_bytes in DB during download."""

    class ProgressTqdm(tqdm):
        _last_db_bytes = 0
        _last_db_time = 0.0

        def update(self, n=1):
            super().update(n)
            if cancel_event.is_set():
                raise DownloadCancelledError("Download cancelled")
            cur = self.n
            now = time.monotonic()
            if (
                cur - self._last_db_bytes >= _PROGRESS_UPDATE_INTERVAL_BYTES
                or now - self._last_db_time >= _PROGRESS_UPDATE_INTERVAL_SEC
            ):
                self._last_db_bytes = cur
                self._last_db_time = now
                try:
                    sess = SessionLocal()
                    try:
                        sess.execute(
                            update(ModelDownloadJob)
                            .where(ModelDownloadJob.id == job_id)
                            .values(progress_bytes=int(cur))
                        )
                        sess.commit()
                    finally:
                        sess.close()
                except Exception:
                    pass

    return ProgressTqdm


def _is_gguf(filename: str) -> bool:
    return filename.lower().endswith(".gguf")


def _safe_repo_dir(repo_id: str) -> str:
    return repo_id.replace("/", "__")


def _model_repo_dir(model: Model) -> Path:
    return Path(settings.models_dir) / _safe_repo_dir(model.hf_repo)


def _cleanup_partial_download(model: Model) -> None:
    repo_dir = _model_repo_dir(model)
    if not repo_dir.exists():
        return

    filename = model.hf_filename
    candidates = {
        filename,
        f"{filename}.incomplete",
        f".{filename}.incomplete",
    }
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name in candidates or filename in name:
            try:
                path.unlink()
            except OSError:
                pass


def delete_model_artifacts(model: Model) -> None:
    if model.local_path:
        try:
            path = Path(model.local_path)
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    _cleanup_partial_download(model)


def start_download_job(job_id: int) -> None:
    _register_cancel_event(job_id)
    t = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    t.start()


def _run_job(job_id: int) -> None:
    db = SessionLocal()
    cancel_event = _register_cancel_event(job_id)
    try:
        job = db.get(ModelDownloadJob, job_id)
        if not job:
            return
        if job.status not in ("pending", "failed"):
            return
        if cancel_event.is_set():
            job.status = "cancelled"
            job.error = "Cancelled by user"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
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
        job.expected_bytes = None
        db.commit()

        # Real file size from Hub (so UI can show X / Y MB — not a fake bar)
        try:
            file_url = hf_hub_url(repo_id=model.hf_repo, filename=model.hf_filename)
            meta = get_hf_file_metadata(
                url=file_url,
                token=settings.hf_token or None,
                timeout=60.0,
            )
            sz = getattr(meta, "size", None)
            if sz is not None and int(sz) > 0:
                _sess = SessionLocal()
                try:
                    _sess.execute(
                        update(ModelDownloadJob)
                        .where(ModelDownloadJob.id == job_id)
                        .values(expected_bytes=int(sz))
                    )
                    _sess.commit()
                finally:
                    _sess.close()
        except Exception:
            pass

        # Rust hf_transfer often skips tqdm — use Python path so progress_bytes updates in DB
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

        os.makedirs(settings.models_dir, exist_ok=True)
        dest_dir = os.path.join(settings.models_dir, _safe_repo_dir(model.hf_repo))
        os.makedirs(dest_dir, exist_ok=True)

        # Fallback: poll file size when hf_transfer (Rust) is used and tqdm is not
        stop_poll = threading.Event()

        def _poll_file_size():
            while not stop_poll.wait(2.0):
                if cancel_event.is_set():
                    return
                try:
                    max_sz = 0
                    for root, _dirs, files in os.walk(dest_dir):
                        for f in files:
                            if f.lower().endswith(".gguf"):
                                p = os.path.join(root, f)
                                if os.path.isfile(p):
                                    max_sz = max(max_sz, os.path.getsize(p))
                    if max_sz > 0:
                        sess = SessionLocal()
                        try:
                            sess.execute(
                                update(ModelDownloadJob)
                                .where(ModelDownloadJob.id == job_id)
                                .values(progress_bytes=max_sz)
                            )
                            sess.commit()
                        finally:
                            sess.close()
                except Exception:
                    pass

        poll_thread = threading.Thread(target=_poll_file_size, daemon=True)
        poll_thread.start()
        try:
            local_path = hf_hub_download(
                repo_id=model.hf_repo,
                filename=model.hf_filename,
                token=settings.hf_token or None,
                local_dir=dest_dir,
                local_dir_use_symlinks=False,
                resume_download=True,
                tqdm_class=_make_progress_tqdm(job_id, cancel_event),
            )
        finally:
            stop_poll.set()

        if cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled")

        final_size = None
        try:
            final_size = os.path.getsize(local_path)
        except OSError:
            pass

        # Fresh session to avoid MariaDB "Record has changed" (1020)
        db_final = SessionLocal()
        try:
            db_final.execute(
                update(Model).where(Model.id == model.id).values(
                    local_path=local_path,
                    size_bytes=int(final_size) if final_size is not None else None,
                )
            )
            db_final.execute(
                update(ModelDownloadJob)
                .where(ModelDownloadJob.id == job_id)
                .values(
                    status="done",
                    progress_bytes=int(final_size) if final_size is not None else 0,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            db_final.commit()
            model_fresh = db_final.get(Model, model.id)
        finally:
            db_final.close()

        # Register in Ollama
        if model_fresh:
            try:
                register_model_in_ollama(model_fresh)
            except Exception:
                pass  # non-fatal
    except DownloadCancelledError:
        db.rollback()
        try:
            job = db.get(ModelDownloadJob, job_id)
            model = db.get(Model, job.model_id) if job else None
            if model:
                delete_model_artifacts(model)
                model.local_path = None
                model.size_bytes = None
            if job:
                job.status = "cancelled"
                job.error = "Cancelled by user"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
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
        _clear_cancel_event(job_id)
        db.close()

