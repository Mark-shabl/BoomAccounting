from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogItem:
    id: str
    label: str
    hf_repo: str
    hf_filename: str
    description: str | None = None


# MVP: curated list so user doesn't need to type repo/filename.
# Keep entries lightweight and public (no gated access required).
CATALOG: list[CatalogItem] = [
    CatalogItem(
        id="tinyllama-q4km",
        label="TinyLlama 1.1B Chat (Q4_K_M, GGUF)",
        hf_repo="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        hf_filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        description="Очень лёгкая модель для быстрой проверки пайплайна (CPU).",
    ),
    CatalogItem(
        id="tinyllama-q5km",
        label="TinyLlama 1.1B Chat (Q5_K_M, GGUF)",
        hf_repo="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        hf_filename="tinyllama-1.1b-chat-v1.0.Q5_K_M.gguf",
        description="Чуть лучше качество/вес, чем Q4.",
    ),
]


def search_catalog(q: str | None) -> list[CatalogItem]:
    if not q:
        return CATALOG
    qn = q.strip().lower()
    if not qn:
        return CATALOG
    out: list[CatalogItem] = []
    for item in CATALOG:
        hay = " ".join([item.id, item.label, item.hf_repo, item.hf_filename, item.description or ""]).lower()
        if qn in hay:
            out.append(item)
    return out

