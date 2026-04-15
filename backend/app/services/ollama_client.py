"""Ollama API client for chat completion."""

from __future__ import annotations

import json
import os
from pathlib import Path

import docker
import httpx

from app.db.models import Model


def _ollama_model_name(model: Model) -> str:
    """Unique Ollama model name for our Model."""
    return f"boom-{model.id}"


def _ollama_url(path: str) -> str:
    base = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    return f"{base}{path}"


def _looks_like_broken_ollama_model_error(message: str) -> bool:
    msg = message.lower()
    return (
        "unable to load model" in msg
        or "/root/.ollama/models/blobs/" in msg
        or "no such file or directory" in msg
    )


def register_model_in_ollama(model: Model) -> None:
    """Create model in Ollama from downloaded GGUF file."""
    if not model.local_path or not os.path.isfile(model.local_path):
        raise RuntimeError("Model file is missing on disk")
    model_dir = Path(model.local_path).parent
    ollama_name = _ollama_model_name(model)
    modelfile_path = model_dir / f"Modelfile.{ollama_name}"
    modelfile_path.write_text(f"FROM {model.local_path}\n", encoding="utf-8")
    try:
        client = docker.from_env()
        container_id = Path("/etc/hostname").read_text(encoding="utf-8").strip()
        client.containers.run(
            "ollama/ollama:latest",
            ["create", ollama_name, "-f", str(modelfile_path)],
            remove=True,
            volumes_from=[container_id],
            network_mode=f"container:{container_id}",
            environment={"OLLAMA_HOST": "http://ollama:11434"},
        )
    except docker.errors.ContainerError as e:
        raise RuntimeError(f"Ollama create failed: {e}") from e


def ensure_model_in_ollama(model: Model) -> None:
    """Register model in Ollama if not already present."""
    ollama_name = _ollama_model_name(model)
    try:
        r = httpx.get(_ollama_url(f"/api/tags"), timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            for m in data.get("models", []):
                if m.get("name", "").startswith(ollama_name):
                    return  # already exists
    except Exception:
        pass
    register_model_in_ollama(model)


def recreate_model_in_ollama(model: Model) -> None:
    """Rebuild a broken Ollama model registration from the GGUF file."""
    try:
        unload_model_from_ollama(model)
    except Exception:
        pass
    try:
        delete_model_from_ollama(model)
    except Exception:
        pass
    register_model_in_ollama(model)


def chat_stream(
    model: Model,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    top_p: float = 0.95,
    top_k: int = 40,
    repeat_penalty: float = 1.1,
):
    """Stream chat completion from Ollama. Yields (content_delta, done, eval_count)."""
    ollama_name = _ollama_model_name(model)
    options = {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repeat_penalty": repeat_penalty,
    }
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    last_err: Exception | None = None
    attempted_recreate = False

    while True:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            for path, payload in (
                (
                    "/api/chat",
                    {
                        "model": ollama_name,
                        "messages": messages,
                        "stream": True,
                        "keep_alive": "30m",
                        "options": options,
                    },
                ),
                (
                    "/api/generate",
                    {
                        "model": ollama_name,
                        "prompt": "\n".join(f"{m['role']}: {m['content']}" for m in messages),
                        "stream": True,
                        "keep_alive": "30m",
                        "options": options,
                    },
                ),
            ):
                try:
                    with client.stream("POST", _ollama_url(path), json=payload) as resp:
                        if resp.status_code >= 400:
                            body = resp.read().decode("utf-8", errors="replace")
                            raise RuntimeError(f"{path}: {resp.status_code} {body[:400]}")
                        eval_count = 0
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if path == "/api/chat":
                                msg = data.get("message") or {}
                                content = msg.get("content") or ""
                            else:
                                content = data.get("response") or ""
                            if content:
                                yield content, False, 0
                            if data.get("done"):
                                eval_count = data.get("eval_count") or 0
                                yield "", True, eval_count
                                return
                except Exception as e:
                    last_err = e
                    continue

        if last_err and (not attempted_recreate) and _looks_like_broken_ollama_model_error(str(last_err)):
            attempted_recreate = True
            recreate_model_in_ollama(model)
            last_err = None
            continue
        break

    raise last_err or RuntimeError("Failed to stream response from Ollama")


def load_model_in_ollama(model: Model) -> None:
    """Trigger Ollama to load the model into memory (preload)."""
    ensure_model_in_ollama(model)
    ollama_name = _ollama_model_name(model)
    last_err: Exception | None = None
    attempted_recreate = False

    while True:
        for path, payload in (
            ("/api/chat", {"model": ollama_name, "messages": [{"role": "user", "content": " "}], "stream": False, "options": {"num_predict": 1}, "keep_alive": "30m"}),
            ("/api/generate", {"model": ollama_name, "prompt": " ", "stream": False, "options": {"num_predict": 1}, "keep_alive": "30m"}),
        ):
            try:
                with httpx.Client(timeout=120.0) as client:
                    r = client.post(_ollama_url(path), json=payload)
                    if r.status_code == 200:
                        return
                    last_err = RuntimeError(f"{path}: {r.status_code} {r.text[:400]}")
            except Exception as e:
                last_err = e

        if last_err and (not attempted_recreate) and _looks_like_broken_ollama_model_error(str(last_err)):
            attempted_recreate = True
            recreate_model_in_ollama(model)
            last_err = None
            continue
        break

    raise (last_err or RuntimeError("Failed to load model"))


def get_model_parameters(model: Model) -> dict:
    """Fetch model parameters from Ollama /api/show. Returns dict with temperature, num_predict, top_p, top_k, repeat_penalty, etc.
    Does NOT register the model - only fetches if already in Ollama."""
    ollama_name = _ollama_model_name(model)
    url = _ollama_url("/api/show")
    try:
        r = httpx.post(url, json={"model": ollama_name}, timeout=10.0)
        if r.status_code != 200:
            return {}
        data = r.json()
        params_str = data.get("parameters") or ""
        out: dict = {}
        for line in params_str.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, val = parts
            try:
                if "." in val:
                    out[key] = float(val)
                else:
                    out[key] = int(val)
            except ValueError:
                out[key] = val
        return out
    except Exception:
        return {}


def unload_model_from_ollama(model: Model) -> None:
    """Unload model from Ollama memory via keep_alive=0. Tries /api/chat then /api/generate."""
    ollama_name = _ollama_model_name(model)
    for path, payload in (
        ("/api/chat", {"model": ollama_name, "messages": [], "keep_alive": 0, "stream": False}),
        ("/api/generate", {"model": ollama_name, "prompt": "", "keep_alive": 0, "stream": False}),
    ):
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(_ollama_url(path), json=payload)
                if r.status_code in (200, 404):
                    return
        except Exception:
            continue


def delete_model_from_ollama(model: Model) -> None:
    """Delete registered model from Ollama. 404 is treated as already deleted."""
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.request("DELETE", _ollama_url("/api/delete"), json={"model": _ollama_model_name(model)})
            if r.status_code in (200, 404):
                return
            raise RuntimeError(f"Ollama delete failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        raise RuntimeError(str(e)) from e


def list_loaded_ollama() -> list[str]:
    """List model names currently loaded in Ollama (for show)."""
    try:
        r = httpx.get(_ollama_url("/api/ps"), timeout=5.0)
        if r.status_code != 200:
            return []
        data = r.json()
        return [m.get("name", "").split(":")[0] for m in data.get("models", [])]
    except Exception:
        return []
