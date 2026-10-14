"""Qdrant note store. Cloud when configured, local or memory otherwise."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.embedder import DIM

log = logging.getLogger("vaultvoice.store")


class NoteStore:
    def __init__(self) -> None:
        self.collection = settings.qdrant_collection
        if settings.qdrant_memory:
            self.client = QdrantClient(":memory:")
            self.mode = "memory"
            self.detail = "In memory Qdrant. Nothing is written to disk."
        elif settings.qdrant_url:
            self.client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
            )
            self.mode = "cloud"
            self.detail = "Qdrant at the configured URL. Payload filter is the access check."
        else:
            from pathlib import Path

            path = Path(settings.qdrant_path)
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
            self.mode = "local"
            self.detail = f"Local qdrant-client store at {path}."
        self.ensure()

    def ensure(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )
        if self.mode == "cloud":
            # Local mode ignores payload indexes. Cloud uses them for the tier filter.
            from qdrant_client.models import PayloadSchemaType

            self.client.create_payload_index(
                collection_name=self.collection,
                field_name="tier",
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def reset(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.ensure()

    def close(self) -> None:
        closer = getattr(self.client, "close", None)
        if closer:
            closer()

    def upsert(self, note_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=note_id, vector=vector, payload=payload)],
        )

    def list_notes(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=64,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            found.extend(self._view(point.id, point.payload or {}) for point in points)
            if offset is None:
                break
        found.sort(key=lambda note: note.get("timestamp") or "", reverse=True)
        return found

    def search(self, vector: list[float], tiers: list[str], limit: int = 4) -> list[dict[str, Any]]:
        """Vector search that cannot see tiers outside `tiers`."""
        result = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="tier", match=MatchAny(any=list(tiers)))]
            ),
            limit=limit,
            with_payload=True,
        )
        hits = []
        for point in result.points:
            view = self._view(point.id, point.payload or {}, score=point.score)
            # Belt and braces: never return a tier the filter did not allow.
            if view["tier"] not in tiers:
                log.warning("dropped out of scope hit %s tier %s", view["id"], view["tier"])
                continue
            hits.append(view)
        return hits

    @staticmethod
    def _view(point_id: Any, payload: dict[str, Any], score: float | None = None) -> dict[str, Any]:
        note = {
            "id": str(point_id),
            "text": payload.get("text") or "",
            "redacted_text": payload.get("redacted_text") or "",
            "tier": payload.get("tier") or "private",
            "suggested_tier": payload.get("suggested_tier") or payload.get("tier") or "private",
            "pii_flags": list(payload.get("pii_flags") or []),
            "timestamp": payload.get("timestamp") or "",
            "source": payload.get("source") or "typed",
            "seed_id": payload.get("seed_id"),
            "guard_reason": payload.get("guard_reason") or "",
        }
        if score is not None:
            note["score"] = round(float(score), 4)
        return note
