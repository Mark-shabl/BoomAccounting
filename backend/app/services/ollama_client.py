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


def register_model_in_ollama(model: Model) -> None:
    """Create model in Ollama from downloaded GGUF file."""
    if not model.local_path or not os.path.isfile(model.local_path):
        return
    model_dir = Path(model.local_path).parent
    modelfile_path = model_dir / "Modelfile"
    modelfile_path.write_text(f"FROM {model.local_path}\n", encoding="utf-8")
    ollama_name = _ollama_model_name(model)
    try:
        client = docker.from_env()
        container_id = open("/etc/hostname").read().strip()
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


def chat_stream(
    model: Model,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 512,
    top_p: float = 0.95,
    top_k: int = 40,
    repeat_penalty: float = 1.1,
):
    """Stream chat completion from Ollama. Yields (content_delta, done, eval_count)."""
    ollama_name = _ollama_model_name(model)
    url = _ollama_url("/api/chat")
    payload = {
        "model": ollama_name,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "repeat_penalty": repeat_penalty,
        },
    }
    with httpx.Client(timeout=300.0) as client:
        with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            eval_count = 0
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message") or {}
                content = msg.get("content") or ""
                if content:
                    yield content, False, 0
                if data.get("done"):
                    eval_count = data.get("eval_count") or 0
                    yield "", True, eval_count
                    return


def load_model_in_ollama(model: Model) -> None:
    """Trigger Ollama to load the model into memory (preload)."""
    ensure_model_in_ollama(model)
    ollama_name = _ollama_model_name(model)
    last_err: Exception | None = None
    for path, payload in (
        ("/api/chat", {"model": ollama_name, "messages": [{"role": "user", "content": " "}], "stream": False, "options": {"num_predict": 1}, "keep_alive": "30m"}),
        ("/api/generate", {"model": ollama_name, "prompt": " ", "stream": False, "options": {"num_predict": 1}, "keep_alive": "30m"}),
    ):
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(_ollama_url(path), json=payload)
                if r.status_code == 200:
                    return
                last_err = RuntimeError(f"{path}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            last_err = e
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
