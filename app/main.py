import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import RateLimitError
from pydantic import BaseModel

from . import agent, config, tools

app = FastAPI(title="MagickWorld chatbot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # tighten to magickworld.in in prod


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index():
    return FileResponse(config.ROOT / "app" / "static" / "index.html")


_hits = defaultdict(deque)
RATE_LIMIT, RATE_WINDOW = 30, 600  # 30 messages per 10 minutes per visitor (protects the Groq key)


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "Too many messages, please wait a few minutes.")
    q.append(now)
    if not config.GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY is not set (see .env.example)")
    msg = body.message.strip()[:1000]
    if not msg:
        raise HTTPException(400, "Empty message")
    sid = body.session_id or uuid.uuid4().hex
    try:
        out = agent.chat(sid, msg)
    except RateLimitError as e:
        print("chat error: Groq rate limit:", str(e)[:300])
        _rollback(sid)
        raise HTTPException(429, "I'm getting a lot of questions right now. Please try again in a minute.")
    except Exception as e:
        print("chat error:", repr(e)[:500])
        _rollback(sid)
        raise HTTPException(502, "The assistant is having trouble right now. Please try again.")
    return {"session_id": sid, **out}


def _rollback(sid):
    """Drop the failed turn (user message + half-finished tool steps) so the user can simply resend."""
    hist = agent.SESSIONS.get(sid, [])
    while hist and hist[-1]["role"] != "user":
        hist.pop()
    if hist:
        hist.pop()


@app.post("/api/reset")
def reset(body: ChatIn):
    agent.SESSIONS.pop(body.session_id or "", None)
    return {"ok": True}


@app.post("/api/reload-data")
def reload_data():
    return {"vendors": tools.load_vendors()}


@app.get("/api/health")
def health():
    return {"ok": True, "vendors": len(tools.VENDORS), "model": config.LLM_MODEL}
