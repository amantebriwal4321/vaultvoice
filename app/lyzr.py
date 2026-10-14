"""Lyzr Studio inference client.

Chat: POST {base}/v3/inference/chat/ with header x-api-key.
Create: POST {base}/v3/agents/template/single-task when no agent id is set.
Missing key, or a failed call, returns mode local-mock so the demo still runs.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger("vaultvoice.lyzr")

PROMPTS = {
    "router": (
        "You are the VaultVoice Router, the first role in a three agent loop. "
        "Decide if the user is storing a new note or querying the vault. "
        "Reply with one JSON object and nothing else. "
        'Schema: {"intent":"store","reason":"short reason"} '
        'or {"intent":"query","reason":"short reason"}. '
        "intent must be store or query."
    ),
    "guard": (
        "You are the VaultVoice Privacy Guard. "
        "Classify the note into exactly one tier: private, shared, or public. "
        "Flag PII using only these labels when they apply: phone, email, health, money, ssn. "
        "Choose private when any PII is present or when you are unsure. "
        "Choose shared for team operations with no PII. "
        "Choose public only for content that is safe for anyone. "
        "Reply with one JSON object and nothing else. "
        'Schema: {"suggested_tier":"private","pii_flags":[],"reason":"short reason"}.'
    ),
    "answer": (
        "You are the VaultVoice Answer agent. "
        "Answer using only the memory chunks in the user message. "
        "Those chunks were already filtered by an access scope. Do not invent other memories. "
        "Never try to reconstruct redacted tokens such as [phone], [email], [health], [amount], [ssn], or [clinician]. "
        "Reply with one JSON object and nothing else. "
        'Schema: {"answer":"two or three plain sentences","used_ids":["id"]}.'
    ),
}

ROLE_NAMES = {
    "router": "VaultVoice Router",
    "guard": "VaultVoice Privacy Guard",
    "answer": "VaultVoice Answer",
}

ROLE_BLURBS = {
    "router": "Decides whether an utterance is a note to store or a question to answer.",
    "guard": "Suggests a privacy tier and lists PII categories.",
    "answer": "Answers from Qdrant chunks that already passed the scope filter.",
}


def parse_agent_json(text: str | None) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    blob = fenced.group(1) if fenced else None
    if blob is None:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        blob = cleaned[start : end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_text(data: object) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        return _extract_text(data[0])
    if not isinstance(data, dict):
        return str(data)
    for key in ("response", "message", "output", "answer", "content", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("data", "result"):
        if key in data:
            return _extract_text(data[key])
    return json.dumps(data)


class LyzrAgents:
    def __init__(self) -> None:
        self.api_key = settings.lyzr_api_key
        self.base = settings.lyzr_base
        self.cache_path = Path(settings.agent_cache_path)
        self.created: dict[str, str] = self._load_cache()
        self.last_error = ""

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: str(value) for key, value in data.items() if value}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.created, indent=2))
        except OSError as exc:
            log.warning("could not cache agent ids: %s", exc)

    def env_id(self, role: str) -> str:
        mapping = {
            "router": settings.lyzr_router_id,
            "guard": settings.lyzr_guard_id,
            "answer": settings.lyzr_answer_id,
        }
        return mapping.get(role) or settings.lyzr_agent_id or self.created.get(role, "")

    def status(self) -> dict:
        if not self.api_key:
            return {
                "mode": "local-mock",
                "detail": "No LYZR_API_KEY. Router, Privacy Guard, and Answer run on local rules.",
                "agents": {
                    role: {"id": None, "mode": "local-mock"}
                    for role in ("router", "guard", "answer")
                },
            }
        agents = {}
        ready = True
        for role in ("router", "guard", "answer"):
            agent_id = self.env_id(role)
            agents[role] = {"id": agent_id or None, "mode": "lyzr" if agent_id else "pending"}
            if not agent_id:
                ready = False
        if ready:
            detail = "Lyzr key is set and each role has an agent id."
        else:
            detail = (
                "Lyzr key is set. Missing agent ids are created on the first loop "
                "via POST /v3/agents/template/single-task."
            )
        if self.last_error:
            detail = f"{detail} Last error: {self.last_error}"
        return {"mode": "lyzr", "detail": detail, "agents": agents}

    def complete(self, role: str, task: str) -> tuple[dict | None, str]:
        """Return (parsed json, mode). mode is lyzr or local-mock."""
        if not self.api_key:
            return None, "local-mock"
        agent_id = self.env_id(role) or self._create(role)
        if not agent_id:
            return None, "local-mock"
        message = PROMPTS[role] + "\n\nTask:\n" + task
        try:
            raw = self._chat(agent_id, message)
        except Exception as exc:
            self.last_error = f"{role}: {exc}"
            log.warning("lyzr %s failed: %s", role, exc)
            return None, "local-mock"
        parsed = parse_agent_json(raw)
        if parsed is None:
            self.last_error = f"{role}: response was not JSON"
            log.warning("lyzr %s returned non json", role)
            return None, "local-mock"
        return parsed, "lyzr"

    def _chat(self, agent_id: str, message: str) -> str:
        session_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
        payload = {
            "user_id": settings.lyzr_user,
            "agent_id": agent_id,
            "session_id": session_id,
            "message": message,
        }
        response = httpx.post(
            f"{self.base}/v3/inference/chat/",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
        return _extract_text(response.json())

    def _create(self, role: str) -> str:
        body = {
            "name": ROLE_NAMES[role],
            "description": ROLE_BLURBS[role],
            "agent_role": ROLE_NAMES[role],
            "agent_instructions": PROMPTS[role],
            "provider_id": "OpenAI",
            "model": "gpt-4o-mini",
            "top_p": 0.9,
            "temperature": 0.2,
            "llm_credential_id": "lyzr_openai",
            "features": [],
            "response_format": {"type": "text"},
        }
        try:
            response = httpx.post(
                f"{self.base}/v3/agents/template/single-task",
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json=body,
                timeout=45,
            )
        except Exception as exc:
            self.last_error = f"create {role}: {exc}"
            return ""
        if response.status_code >= 400:
            self.last_error = f"create {role}: HTTP {response.status_code}: {response.text[:240]}"
            log.warning(self.last_error)
            return ""
        data = response.json()
        agent_id = ""
        if isinstance(data, dict):
            agent_id = str(data.get("agent_id") or data.get("id") or "")
        if not agent_id:
            self.last_error = f"create {role}: no agent_id in response"
            return ""
        self.created[role] = agent_id
        self._save_cache()
        log.info("created lyzr %s agent %s", role, agent_id)
        return agent_id
