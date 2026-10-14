"""One loop: route, guard, write or filter, answer, audit."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.embedder import Embedder
from app.lyzr import LyzrAgents
from app.pii import _dedupe, detect_flags, redact, route_intent, suggest_tier
from app.store import NoteStore

log = logging.getLogger("vaultvoice")

SCOPE_TIERS = {
    "me": ["private", "shared", "public"],
    "team": ["shared", "public"],
    "public": ["public"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str, limit: int = 320) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."


def _agent_text(note: dict) -> str:
    # Private payloads are redacted before they leave the vault for any agent.
    if note.get("tier") == "private":
        return note.get("redacted_text") or redact(note.get("text") or "")
    return note.get("text") or ""


class Vault:
    def __init__(self) -> None:
        self.embedder = Embedder()
        self.store = NoteStore()
        self.lyzr = LyzrAgents()
        self.audit: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self._load_audit()

    def close(self) -> None:
        self.store.close()

    def _load_audit(self) -> None:
        path = settings.audit_path
        if not path:
            return
        from pathlib import Path

        file = Path(path)
        if not file.exists():
            return
        for line in file.read_text().splitlines()[-200:]:
            line = line.strip()
            if not line:
                continue
            try:
                import json

                self.audit.append(json.loads(line))
            except Exception:
                continue

    def _write_audit(self, entry: dict) -> None:
        self.audit.append(entry)
        self.audit = self.audit[-200:]
        path = settings.audit_path
        if not path:
            return
        import json
        from pathlib import Path

        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def status(self) -> dict:
        lyzr = self.lyzr.status()
        return {
            "app": "VaultVoice",
            "lyzr": lyzr["mode"],
            "lyzr_detail": lyzr["detail"],
            "agents": lyzr["agents"],
            "qdrant": self.store.mode,
            "qdrant_detail": self.store.detail,
            "embedder": self.embedder.mode,
            "embedder_error": self.embedder.error,
            "collection": self.store.collection,
            "scopes": SCOPE_TIERS,
        }

    def list_notes(self) -> list[dict]:
        with self.lock:
            return self.store.list_notes()

    def list_audit(self) -> list[dict]:
        with self.lock:
            return list(reversed(self.audit))

    def turn(self, text: str, tier: str | None, scope: str, source: str) -> dict:
        with self.lock:
            router = self._route(text)
            if router["intent"] == "query":
                return self._query(text, scope, source, router)
            return self._store_turn(text, tier, source, router)

    def query(self, text: str, scope: str, source: str = "typed") -> dict:
        with self.lock:
            router = {
                "name": "Router",
                "mode": "local-mock",
                "intent": "query",
                "reason": "Direct query endpoint. The router step was skipped.",
            }
            return self._query(text, scope, source, router)

    def store_text(
        self,
        text: str,
        tier: str | None,
        source: str,
        seed_id: str | None = None,
        timestamp: str | None = None,
        write_audit: bool = False,
        use_lyzr: bool = False,
    ) -> dict:
        with self.lock:
            router = {
                "name": "Router",
                "mode": "local-mock",
                "intent": "store",
                "reason": "Direct store.",
            }
            return self._store_turn(
                text,
                tier,
                source,
                router,
                seed_id=seed_id,
                timestamp=timestamp,
                write_audit=write_audit,
                use_lyzr=use_lyzr,
            )

    def _route(self, text: str) -> dict:
        parsed, mode = self.lyzr.complete(
            "router",
            "Utterance:\n" + text,
        )
        local = route_intent(text)
        intent = local["intent"]
        reason = local["reason"]
        if parsed and parsed.get("intent") in {"store", "query"}:
            intent = parsed["intent"]
            reason = str(parsed.get("reason") or reason)
            mode = "lyzr"
        else:
            mode = "local-mock"
        return {"name": "Router", "mode": mode, "intent": intent, "reason": reason}

    def _guard(self, text: str, use_lyzr: bool = True) -> dict:
        local = suggest_tier(text)
        mode = "local-mock"
        suggested = local["suggested_tier"]
        flags = list(local["pii_flags"])
        reason = local["reason"]
        if use_lyzr:
            parsed, call_mode = self.lyzr.complete("guard", "Note:\n" + text)
            if parsed and call_mode == "lyzr":
                mode = "lyzr"
                model_tier = str(parsed.get("suggested_tier") or "").lower()
                model_flags = [
                    flag
                    for flag in (parsed.get("pii_flags") or [])
                    if flag in {"phone", "email", "health", "money", "ssn"}
                ]
                # Local scan always contributes. A model cannot hide a phone number.
                flags = _dedupe(model_flags + detect_flags(text))
                if flags:
                    suggested = "private"
                    reason = str(parsed.get("reason") or local["reason"])
                    if "private" not in reason.lower():
                        reason = reason.rstrip(".") + ". Local scan forced private because PII is present."
                elif model_tier in {"private", "shared", "public"}:
                    suggested = model_tier
                    reason = str(parsed.get("reason") or reason)
                else:
                    suggested = local["suggested_tier"]
                    reason = local["reason"]
        return {
            "name": "Privacy Guard",
            "mode": mode,
            "suggested_tier": suggested,
            "pii_flags": flags,
            "reason": reason,
        }

    def _store_turn(
        self,
        text: str,
        tier: str | None,
        source: str,
        router: dict,
        seed_id: str | None = None,
        timestamp: str | None = None,
        write_audit: bool = True,
        use_lyzr: bool = True,
    ) -> dict:
        guard = self._guard(text, use_lyzr=use_lyzr)
        chosen = tier if tier in {"private", "shared", "public"} else guard["suggested_tier"]
        warning = None
        rank = {"public": 0, "shared": 1, "private": 2}
        if rank[chosen] < rank[guard["suggested_tier"]]:
            warning = (
                f"Guard suggested {guard['suggested_tier']}: {guard['reason']} "
                f"Stored tier is {chosen}."
            )
        redacted = redact(text)
        note_id = str(uuid.uuid4())
        stamp = timestamp or _now()
        payload = {
            "text": text,
            "redacted_text": redacted,
            "tier": chosen,
            "suggested_tier": guard["suggested_tier"],
            "pii_flags": guard["pii_flags"],
            "timestamp": stamp,
            "source": source,
            "seed_id": seed_id,
            "guard_reason": guard["reason"],
        }
        vector = self.embedder.embed_one(text)
        self.store.upsert(note_id, vector, payload)
        note = self.store._view(note_id, payload)
        modes = {router["mode"], guard["mode"]}
        reasoning = "lyzr" if modes == {"lyzr"} else "local-mock" if modes == {"local-mock"} else "mixed"
        audit_id = None
        if write_audit:
            audit_id = self._audit(
                action="store",
                text=text,
                source=source,
                scope=None,
                tier=chosen,
                reasoning=reasoning,
                qdrant_filter=[chosen],
                chunks=[],
                agents=[router, _guard_public(guard)],
                answer=None,
                warning=warning,
            )
        return {
            "action": "store",
            "source": source,
            "reasoning_mode": reasoning,
            "router": router,
            "guard": _guard_public(guard),
            "answer_agent": None,
            "note": note,
            "warning": warning,
            "answer": None,
            "scope": None,
            "qdrant_filter": [chosen],
            "chunks": [],
            "audit_id": audit_id,
        }

    def _query(self, text: str, scope: str, source: str, router: dict) -> dict:
        allowed = SCOPE_TIERS.get(scope, SCOPE_TIERS["me"])
        vector = self.embedder.embed_one(text)
        hits = self.store.search(vector, allowed, limit=4)
        # Keep the nearest cluster. The answer agent only receives this set.
        context = _select_context(hits)
        prepared = []
        redacted_count = 0
        for hit in context:
            excerpt = _agent_text(hit)
            was_redacted = hit["tier"] == "private" and excerpt != hit["text"]
            if was_redacted:
                redacted_count += 1
            prepared.append(
                {
                    "id": hit["id"],
                    "tier": hit["tier"],
                    "score": hit.get("score"),
                    "pii_flags": hit["pii_flags"],
                    "timestamp": hit["timestamp"],
                    "redacted": was_redacted,
                    "excerpt": _clip(excerpt),
                }
            )
        guard = {
            "name": "Privacy Guard",
            "mode": "local-mock",
            "suggested_tier": None,
            "pii_flags": _dedupe(flag for chunk in prepared for flag in chunk["pii_flags"]),
            "reason": (
                f"Scope {scope} allows {', '.join(allowed)}. "
                f"{_redacted_line(redacted_count)} "
                "Hits outside the payload filter never reached this step."
            ),
            "allowed_tiers": allowed,
            "redacted_count": redacted_count,
        }
        answer, answer_mode, used_ids = self._answer(text, scope, prepared)
        if used_ids:
            cited = [chunk for chunk in prepared if chunk["id"] in used_ids]
            if cited:
                prepared = cited
        modes = {router["mode"], answer_mode}
        reasoning = "lyzr" if modes == {"lyzr"} else "local-mock" if "lyzr" not in modes else "mixed"
        warning = None
        if redacted_count:
            warning = "Private PII was redacted before the answer agent ran."
        audit_id = self._audit(
            action="query",
            text=text,
            source=source,
            scope=scope,
            tier=None,
            reasoning=reasoning,
            qdrant_filter=allowed,
            chunks=prepared,
            agents=[router, guard, {"name": "Answer", "mode": answer_mode, "reason": "Cited the chunks below."}],
            answer=answer,
            warning=warning,
        )
        return {
            "action": "query",
            "source": source,
            "reasoning_mode": reasoning,
            "router": router,
            "guard": guard,
            "answer_agent": {"name": "Answer", "mode": answer_mode, "reason": "Answered only from the cited chunks."},
            "note": None,
            "warning": warning,
            "answer": answer,
            "scope": scope,
            "qdrant_filter": allowed,
            "chunks": prepared,
            "audit_id": audit_id,
        }

    def _answer(self, question: str, scope: str, chunks: list[dict]) -> tuple[str, str, list[str]]:
        if not chunks:
            return (
                f"No memory in the {scope} scope matched that. "
                "Notes outside this scope never reached the answer agent.",
                "local-mock",
                [],
            )
        payload = {
            "question": question,
            "scope": scope,
            "chunks": [
                {"id": chunk["id"], "tier": chunk["tier"], "text": chunk["excerpt"]}
                for chunk in chunks
            ],
        }
        import json

        parsed, mode = self.lyzr.complete("answer", json.dumps(payload))
        allowed_ids = {chunk["id"] for chunk in chunks}
        if parsed and mode == "lyzr" and isinstance(parsed.get("answer"), str):
            used = [item for item in (parsed.get("used_ids") or []) if item in allowed_ids]
            if not used:
                used = [chunk["id"] for chunk in chunks]
            return parsed["answer"].strip(), "lyzr", used
        text = " ".join(chunk["excerpt"] for chunk in chunks)
        noun = "chunk" if len(chunks) == 1 else "chunks"
        answer = f"Local mock, using {len(chunks)} {noun} from the {scope} scope: {text}"
        return answer, "local-mock", [chunk["id"] for chunk in chunks]

    def _audit(self, **kwargs: Any) -> str:
        audit_id = uuid.uuid4().hex[:12]
        entry = {
            "id": audit_id,
            "timestamp": _now(),
            "action": kwargs["action"],
            "input": _clip(kwargs["text"], 400),
            "source": kwargs["source"],
            "scope": kwargs["scope"],
            "tier": kwargs["tier"],
            "reasoning_mode": kwargs["reasoning"],
            "qdrant_filter": kwargs["qdrant_filter"],
            "chunks": kwargs["chunks"],
            "agents": [
                {
                    "name": agent["name"],
                    "mode": agent["mode"],
                    "summary": agent.get("reason") or agent.get("summary") or "",
                }
                for agent in kwargs["agents"]
            ],
            "answer": kwargs["answer"],
            "warning": kwargs["warning"],
        }
        self._write_audit(entry)
        return audit_id


def _guard_public(guard: dict) -> dict:
    return {
        "name": guard["name"],
        "mode": guard["mode"],
        "suggested_tier": guard["suggested_tier"],
        "pii_flags": guard["pii_flags"],
        "reason": guard["reason"],
    }


def _redacted_line(count: int) -> str:
    if count == 0:
        return "No private chunks needed redaction."
    if count == 1:
        return "1 private chunk was redacted before the answer agent."
    return f"{count} private chunks were redacted before the answer agent."


def _same_memory(left: str, right: str) -> bool:
    a = " ".join(left.lower().split())
    b = " ".join(right.lower().split())
    if not a or not b:
        return False
    return a in b or b in a


def _select_context(hits: list[dict]) -> list[dict]:
    if not hits:
        return []
    top = hits[0].get("score") or 0.0
    chosen: list[dict] = []
    for hit in hits:
        score = hit.get("score") or 0.0
        if chosen and score < top - 0.12:
            break
        if len(chosen) >= 2:
            break
        excerpt = _agent_text(hit)
        if any(_same_memory(excerpt, _agent_text(prev)) for prev in chosen):
            continue
        chosen.append(hit)
    return chosen
