"""FastAPI entrypoint for the Skylark BI agent."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import run_agent
from .config import get_settings
from .monday_client import MondayError, monday_client

app = FastAPI(title="Skylark BI Agent", version="1.0.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Schemas ---------------------------------------------------------------
class Message(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = []
    data_quality: dict = {}
    error: str | None = None


# ---- Routes ----------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Report configuration + live monday.com connectivity."""
    status: dict = {
        "status": "ok",
        "groq_configured": settings.groq_configured,
        "monday_configured": settings.monday_configured,
        "model": settings.groq_model,
    }
    if settings.monday_configured:
        try:
            me = await monday_client.health()
            status["monday_connection"] = "ok"
            status["monday_account"] = me.get("email") or me.get("name")
        except MondayError as exc:
            status["monday_connection"] = "error"
            status["monday_error"] = str(exc)
    else:
        status["monday_connection"] = "not_configured"
    return status


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    result = await run_agent(history)
    return ChatResponse(**result)


@app.post("/leadership-update", response_model=ChatResponse)
async def leadership_update() -> ChatResponse:
    """Generate a ready-to-share leadership briefing from both boards.

    Our interpretation of the optional 'help prepare data for leadership
    updates' requirement: a one-click executive digest.
    """
    prompt = (
        "Prepare a concise leadership update for the founders using BOTH boards. "
        "Pull the deals and work orders data first. Use ONLY figures and category "
        "names that appear in the tool results - do NOT invent sectors, stages, "
        "or numbers, and do NOT create quarterly/time buckets that the data does "
        "not support. Structure it as:\n"
        "1. Headline (2-3 sentences on overall business health).\n"
        "2. Pipeline & Revenue (total pipeline value, the actual top sectors by "
        "value from the sector ranking, win rate, stage concentration, risks).\n"
        "3. Operations (work order status and anything notable).\n"
        "4. Data caveats (the real completeness figures and which key fields are "
        "mostly missing, e.g. close dates).\n"
        "Keep it tight and board-ready. Use markdown headings and bullets."
    )
    result = await run_agent([{"role": "user", "content": prompt}])
    return ChatResponse(**result)


@app.get("/")
async def root() -> dict:
    return {"service": "Skylark BI Agent", "docs": "/docs", "health": "/health"}
