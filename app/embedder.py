"""Local embeddings. fastembed all-MiniLM-L6-v2, with a hash fallback."""

from __future__ import annotations

import hashlib
import logging
import re

from app.config import settings

log = logging.getLogger("vaultvoice.embed")

DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
STOP = {
    "the", "a", "an", "to", "in", "on", "at", "for", "of", "and", "or", "is",
    "it", "my", "me", "this", "that", "with", "from", "be", "was", "are", "i",
}


class Embedder:
    def __init__(self) -> None:
        self.model = None
        self.mode = "unloaded"
        self.error = ""
        prefer_hash = settings.embedder in {"hash", "hash-fallback", "fallback"}
        if prefer_hash:
            self.mode = "hash-fallback"
            return
        try:
            from fastembed import TextEmbedding

            self.model = TextEmbedding(model_name=MODEL_NAME)
            # Warm the session so the first note is not the slow one.
            list(self.model.embed(["vault voice warmup"]))
            self.mode = f"fastembed:{MODEL_NAME}"
        except Exception as exc:  # pragma: no cover - depends on the host
            self.error = f"{exc.__class__.__name__}: {exc}"
            self.mode = "hash-fallback"
            self.model = None
            log.warning("fastembed unavailable, using hash fallback: %s", self.error)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.model is not None:
            return [vector.tolist() for vector in self.model.embed(texts)]
        return [self._hash(text) for text in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _hash(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        words = [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOP]
        tokens = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % DIM
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vec[index] += sign
        norm = sum(value * value for value in vec) ** 0.5 or 1.0
        return [value / norm for value in vec]
