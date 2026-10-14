"""VaultVoice HTTP API and static UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.orchestrator import SCOPE_TIERS, Vault
from app.samples import seed_vault

log = logging.getLogger("vaultvoice")
STATIC = Path(__file__).resolve().parent.parent / "static"


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    tier: Literal["private", "shared", "public"] | None = None
    scope: Literal["me", "team", "public"] = "me"
    source: Literal["voice", "typed", "seed"] = "typed"


class QueryIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    scope: Literal["me", "team", "public"] = "me"


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    tier: Literal["private", "shared", "public"] | None = None
    source: Literal["voice", "typed", "seed"] = "typed"


def _clean(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Say or type something first.")
    return stripped


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    vault = Vault()
    app.state.vault = vault
    added = seed_vault(vault)
    status = vault.status()
    log.info(
        "ready qdrant=%s embedder=%s lyzr=%s seeded=%s",
        status["qdrant"],
        status["embedder"],
        status["lyzr"],
        added,
    )
    yield
    vault.close()


app = FastAPI(title="VaultVoice", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _vault(request: Request) -> Vault:
    return request.app.state.vault


@app.get("/api/status")
def status(request: Request):
    vault = _vault(request)
    data = vault.status()
    data["notes_count"] = len(vault.list_notes())
    data["scopes"] = SCOPE_TIERS
    return data


@app.get("/api/notes")
def notes(request: Request):
    items = _vault(request).list_notes()
    return {"notes": items, "count": len(items)}


@app.get("/api/audit")
def audit(request: Request):
    entries = _vault(request).list_audit()
    return {"entries": entries, "count": len(entries)}


@app.post("/api/seed")
def seed(request: Request):
    added = seed_vault(_vault(request))
    return {"added": added}


@app.post("/api/turn")
def turn(body: TurnIn, request: Request):
    text = _clean(body.text)
    return _vault(request).turn(text, body.tier, body.scope, body.source)


@app.post("/api/notes")
def create_note(body: NoteIn, request: Request):
    text = _clean(body.text)
    return _vault(request).store_text(text, body.tier, body.source, write_audit=True, use_lyzr=True)


@app.post("/api/query")
def query(body: QueryIn, request: Request):
    text = _clean(body.text)
    return _vault(request).query(text, body.scope)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
