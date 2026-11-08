import os
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "JustAI API"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").strip()

app = FastAPI(title=APP_NAME, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)


class ChatResponse(BaseModel):
    reply: str
    model: str


@app.get("/")
async def root():
    return {"name": APP_NAME, "status": "online", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok", "ai_configured": bool(GEMINI_API_KEY), "model": GEMINI_MODEL}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI is not configured. Add GEMINI_API_KEY to the backend environment variables.",
        )

    contents = []
    for item in payload.history[-20:]:
        text = item.content.strip()
        if text:
            contents.append({"role": item.role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": payload.message.strip()}]})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {
            "parts": [{
                "text": (
                    "You are JustAI, a helpful, accurate, friendly AI assistant. "
                    "Answer in the language used by the user. Explain technical topics clearly. "
                    "Use Markdown when it improves readability. If unsure, say so."
                )
            }]
        },
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(url, params={"key": GEMINI_API_KEY}, json=body)
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", "AI provider request failed")
            except Exception:
                detail = "AI provider request failed"
            raise HTTPException(status_code=502, detail=detail)

        data = response.json()
        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        reply = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not reply.strip():
            raise HTTPException(status_code=502, detail="The AI provider returned an empty response.")
        return ChatResponse(reply=reply, model=GEMINI_MODEL)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="The AI provider took too long to respond. Try again.")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not connect to the AI provider.")
