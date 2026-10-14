"""Runtime settings loaded from the environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Keep the neural model next to the repo so a second boot is warm.
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(ROOT / "data" / "models"))


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.root = ROOT
        self.port = int(os.getenv("PORT", "8741"))
        self.force_local = _flag("VAULT_FORCE_LOCAL")
        self.lyzr_api_key = "" if self.force_local else os.getenv("LYZR_API_KEY", "").strip()
        self.lyzr_agent_id = os.getenv("LYZR_AGENT_ID", "").strip()
        self.lyzr_router_id = os.getenv("LYZR_ROUTER_AGENT_ID", "").strip()
        self.lyzr_guard_id = os.getenv("LYZR_GUARD_AGENT_ID", "").strip()
        self.lyzr_answer_id = os.getenv("LYZR_ANSWER_AGENT_ID", "").strip()
        self.lyzr_base = os.getenv("LYZR_BASE_URL", "https://agent-prod.studio.lyzr.ai").rstrip("/")
        self.lyzr_user = os.getenv("LYZR_USER_ID", "vaultvoice").strip() or "vaultvoice"
        self.qdrant_url = "" if _flag("QDRANT_IN_MEMORY") else os.getenv("QDRANT_URL", "").strip()
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip()
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "vaultvoice_notes").strip() or "vaultvoice_notes"
        self.qdrant_memory = _flag("QDRANT_IN_MEMORY")
        self.qdrant_path = os.getenv("QDRANT_PATH", str(ROOT / "data" / "qdrant"))
        self.embedder = os.getenv("EMBEDDER", "fastembed").strip().lower() or "fastembed"
        audit = os.getenv("AUDIT_PATH", str(ROOT / "data" / "audit.jsonl"))
        self.audit_path = "" if audit.strip() in {"", "off", "none"} else audit
        self.agent_cache_path = str(ROOT / "data" / "lyzr_agents.json")


settings = Settings()
