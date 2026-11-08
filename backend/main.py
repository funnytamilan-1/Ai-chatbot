import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import secrets
import hmac
from typing import Literal
from uuid import uuid4

import httpx
from dotenv import load_dotenv

load_dotenv()
import jwt
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, model_validator
from pwdlib import PasswordHash
from pymongo.errors import DuplicateKeyError

APP_NAME = "JustAI API"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "justai").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
TOKEN_HOURS = 72
COOKIE_NAME = "justai_session"
CSRF_COOKIE_NAME = "justai_csrf"
COOKIE_SECURE = os.getenv("APP_ENV", "development").lower() == "production"
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"
password_hash = PasswordHash.recommended()
mongo_client = None
db = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db
    if MONGODB_URI:
        mongo_client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = mongo_client[MONGODB_DATABASE]
        await mongo_client.admin.command("ping")
        await db.users.create_index("email", unique=True)
        await db.chats.create_index([("user_id", 1), ("updated_at", -1)])
        await db.training_datasets.create_index([("user_id", 1), ("created_at", -1)])
        await db.training_jobs.create_index([("user_id", 1), ("created_at", -1)])
        await db.training_models.create_index([("user_id", 1), ("created_at", -1)])
    yield
    if mongo_client:
        mongo_client.close()


app = FastAPI(title=APP_NAME, version="2.0.0", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)


def database():
    if db is None:
        raise HTTPException(status_code=503, detail="Database is not configured. Add MONGODB_URI to backend environment variables.")
    return db


def token_for(user_id: str):
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured. Add a random JWT_SECRET (at least 32 characters).")
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=TOKEN_HOURS)}, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def current_user(session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME), authorization: str | None = Header(default=None)):
    token = session_cookie
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Your session expired. Please sign in again.")
    user = await database().users.find_one({"_id": user_id}, {"password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Account not found. Please sign in again.")
    return user



def set_session_cookies(response: Response, user_id: str):
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(key=COOKIE_NAME, value=token_for(user_id), httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, max_age=TOKEN_HOURS * 60 * 60, path="/")
    response.set_cookie(key=CSRF_COOKIE_NAME, value=csrf_token, httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, max_age=TOKEN_HOURS * 60 * 60, path="/")
    return csrf_token


async def require_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
):
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="Your request could not be verified. Refresh and try again.")


class AuthInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=40)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
    chat_id: str | None = None


class ChatTitle(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class LocalChatSaveInput(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    reply: str = Field(min_length=1, max_length=30000)
    chat_id: str | None = None


class TrainingMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class TrainingExample(BaseModel):
    messages: list[TrainingMessage] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def validate_conversation(self):
        roles = [message.role for message in self.messages]
        if "user" not in roles:
            raise ValueError("Each training example must include a user message.")
        if roles[-1] != "assistant":
            raise ValueError("Each training example must end with an assistant answer.")
        return self


class TrainingDatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    examples: list[TrainingExample] = Field(min_length=2, max_length=2000)


class TrainingJobInput(BaseModel):
    dataset_id: str = Field(min_length=36, max_length=36)
    epochs: int = Field(default=1, ge=1, le=3)
    lora_rank: Literal[8, 16, 32] = 8


def public_user(user):
    return {"id": user["_id"], "name": user["name"], "email": user["email"]}


@app.get("/")
async def root():
    return {"name": APP_NAME, "status": "online", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok", "ai_configured": bool(GEMINI_API_KEY), "database_configured": bool(MONGODB_URI), "model": GEMINI_MODEL}


@app.post("/api/auth/register")
async def register(payload: AuthInput, response: Response):
    store = database()
    email = str(payload.email).lower().strip()
    if await store.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = {"_id": str(uuid4()), "name": payload.name.strip(), "email": email, "password_hash": password_hash.hash(payload.password), "created_at": datetime.now(timezone.utc)}
    try:
        await store.users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    csrf_token = set_session_cookies(response, user["_id"])
    return {"user": public_user(user), "csrf_token": csrf_token}


@app.post("/api/auth/login")
async def login(payload: LoginInput, response: Response):
    user = await database().users.find_one({"email": str(payload.email).lower().strip()})
    if not user or not password_hash.verify(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    csrf_token = set_session_cookies(response, user["_id"])
    return {"user": public_user(user), "csrf_token": csrf_token}


@app.post("/api/auth/logout")
async def logout(response: Response, _csrf=Depends(require_csrf)):
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE)
    return {"signed_out": True}


@app.get("/api/auth/me")
async def me(user=Depends(current_user), csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME)):
    return {"user": public_user(user), "csrf_token": csrf_cookie}


@app.get("/api/training/overview")
async def training_overview(user=Depends(current_user)):
    store = database()
    jobs = store.training_jobs
    queued = await jobs.count_documents({"user_id": user["_id"], "status": "queued"})
    running = await jobs.count_documents({"user_id": user["_id"], "status": "running"})
    completed = await jobs.count_documents({"user_id": user["_id"], "status": "completed"})
    datasets = await store.training_datasets.count_documents({"user_id": user["_id"]})
    models = await store.training_models.count_documents({"user_id": user["_id"]})
    return {
        "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
        "method": "LoRA fine-tuning",
        "queued_jobs": queued,
        "running_jobs": running,
        "completed_jobs": completed,
        "datasets": datasets,
        "models": models,
        "worker_required": True,
    }


@app.get("/api/training/datasets")
async def list_training_datasets(user=Depends(current_user)):
    cursor = database().training_datasets.find({"user_id": user["_id"]}, {"examples": 0}).sort("created_at", -1).limit(50)
    items = []
    async for item in cursor:
        items.append({"id": item["_id"], "name": item["name"], "example_count": item["example_count"], "created_at": item["created_at"].isoformat()})
    return {"datasets": items}


@app.post("/api/training/datasets")
async def create_training_dataset(payload: TrainingDatasetInput, user=Depends(current_user), _csrf=Depends(require_csrf)):
    total_chars = 0
    for example in payload.examples:
        roles = [message.role for message in example.messages]
        if "user" not in roles or roles[-1] != "assistant":
            raise HTTPException(status_code=422, detail="Each example must include a user message and end with an assistant answer.")
        total_chars += sum(len(message.content) for message in example.messages)
    if total_chars > 1_000_000:
        raise HTTPException(status_code=413, detail="Dataset text is too large. Keep each upload under 1 MB.")
    now = datetime.now(timezone.utc)
    item = {
        "_id": str(uuid4()), "user_id": user["_id"], "name": payload.name.strip(),
        "example_count": len(payload.examples), "examples": [example.model_dump() for example in payload.examples],
        "created_at": now,
    }
    await database().training_datasets.insert_one(item)
    return {"dataset": {"id": item["_id"], "name": item["name"], "example_count": item["example_count"], "created_at": now.isoformat()}}


@app.get("/api/training/jobs")
async def list_training_jobs(user=Depends(current_user)):
    cursor = database().training_jobs.find(
        {"user_id": user["_id"]},
        {"_id": 1, "dataset_name": 1, "status": 1, "progress": 1, "epochs": 1, "lora_rank": 1, "error": 1, "created_at": 1, "model_id": 1},
    ).sort("created_at", -1).limit(30)
    items = []
    async for item in cursor:
        items.append({
            "id": item["_id"], "dataset_name": item["dataset_name"], "status": item["status"],
            "progress": item.get("progress", 0), "epochs": item["epochs"], "lora_rank": item["lora_rank"],
            "error": item.get("error"), "model_id": item.get("model_id"), "created_at": item["created_at"].isoformat(),
        })
    return {"jobs": items}


@app.post("/api/training/jobs")
async def create_training_job(payload: TrainingJobInput, user=Depends(current_user), _csrf=Depends(require_csrf)):
    store = database()
    dataset = await store.training_datasets.find_one({"_id": payload.dataset_id, "user_id": user["_id"]})
    if not dataset:
        raise HTTPException(status_code=404, detail="Training dataset not found.")
    active = await store.training_jobs.find_one({"user_id": user["_id"], "status": {"$in": ["queued", "running"]}})
    if active:
        raise HTTPException(status_code=409, detail="You already have a training job queued or running.")
    now = datetime.now(timezone.utc)
    job = {
        "_id": str(uuid4()), "user_id": user["_id"], "dataset_id": dataset["_id"],
        "dataset_name": dataset["name"], "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
        "method": "LoRA", "epochs": payload.epochs, "lora_rank": payload.lora_rank,
        "status": "queued", "progress": 0, "created_at": now, "updated_at": now,
    }
    await store.training_jobs.insert_one(job)
    return {"job": {"id": job["_id"], "status": job["status"], "dataset_name": job["dataset_name"]}}


@app.get("/api/training/models")
async def list_training_models(user=Depends(current_user)):
    cursor = database().training_models.find(
        {"user_id": user["_id"]},
        {"_id": 1, "name": 1, "base_model": 1, "method": 1, "dataset_name": 1, "artifact_path": 1, "created_at": 1, "job_id": 1},
    ).sort("created_at", -1).limit(30)
    items = []
    async for item in cursor:
        items.append({
            "id": item["_id"], "name": item["name"], "base_model": item["base_model"],
            "method": item["method"], "dataset_name": item["dataset_name"],
            "artifact_path": item["artifact_path"], "job_id": item["job_id"],
            "created_at": item["created_at"].isoformat(),
        })
    return {"models": items}


@app.get("/api/chats")
async def list_chats(user=Depends(current_user)):
    cursor = database().chats.find({"user_id": user["_id"]}).sort("updated_at", -1).limit(100)
    chats = []
    async for item in cursor:
        chats.append({"id": item["_id"], "title": item["title"], "updated_at": item["updated_at"].isoformat()})
    return {"chats": chats}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str, user=Depends(current_user)):
    item = await database().chats.find_one({"_id": chat_id, "user_id": user["_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"id": item["_id"], "title": item["title"], "messages": item.get("messages", [])}


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, user=Depends(current_user), _csrf=Depends(require_csrf)):
    result = await database().chats.delete_one({"_id": chat_id, "user_id": user["_id"]})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"deleted": True}


@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, payload: ChatTitle, user=Depends(current_user), _csrf=Depends(require_csrf)):
    result = await database().chats.update_one({"_id": chat_id, "user_id": user["_id"]}, {"$set": {"title": payload.title.strip(), "updated_at": datetime.now(timezone.utc)}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"updated": True}




@app.post("/api/chat/local/save")
async def save_local_chat(payload: LocalChatSaveInput, user=Depends(current_user), _csrf=Depends(require_csrf)):
    """Persist a reply generated privately in the user's browser with WebLLM."""
    store = database()
    chat_id = payload.chat_id or str(uuid4())
    record = await store.chats.find_one({"_id": chat_id, "user_id": user["_id"]})
    if payload.chat_id and not record:
        raise HTTPException(status_code=404, detail="Chat not found.")
    now = datetime.now(timezone.utc)
    title = (record or {}).get("title") or payload.message.strip()[:48] or "New chat"
    await store.chats.update_one(
        {"_id": chat_id, "user_id": user["_id"]},
        {
            "$set": {"title": title, "updated_at": now},
            "$push": {"messages": {"$each": [
                {"role": "user", "content": payload.message.strip()},
                {"role": "model", "content": payload.reply.strip()},
            ], "$slice": -100}},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"saved": True, "chat_id": chat_id, "title": title, "model": "Qwen2.5-0.5B-Instruct-q4f16_1-MLC", "provider": "browser-local"}


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, user=Depends(current_user), _csrf=Depends(require_csrf)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured. Add GEMINI_API_KEY to backend environment variables.")
    store = database()
    chat_id = payload.chat_id or str(uuid4())
    record = await store.chats.find_one({"_id": chat_id, "user_id": user["_id"]})
    if payload.chat_id and not record:
        raise HTTPException(status_code=404, detail="Chat not found.")

    contents = []
    for item in payload.history[-20:]:
        text = item.content.strip()
        if text:
            contents.append({"role": item.role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": payload.message.strip()}]})
    system_prompt = (
        "You are JustAI, a helpful, accurate, friendly AI assistant. Answer in the language used by the user. "
        "Understand Tamil written in Latin letters (Tanglish) and reply naturally in the same style when appropriate. "
        "Explain technical topics clearly, help with coding, and use Markdown when useful. "
        "Never claim to have performed actions you did not perform. If unsure, say so."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse"
    body = {"systemInstruction": {"parts": [{"text": system_prompt}]}, "contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}}

    async def events():
        chunks = []
        try:
            timeout = httpx.Timeout(90.0, connect=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers={"x-goog-api-key": GEMINI_API_KEY}, json=body) as upstream:
                    if upstream.status_code >= 400:
                        raw = await upstream.aread()
                        try:
                            detail = json.loads(raw).get("error", {}).get("message", "AI provider request failed")
                        except (ValueError, TypeError):
                            detail = "AI provider request failed"
                        yield "data: " + json.dumps({"error": detail}) + "\n\n"
                        return
                    async for line in upstream.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            packet = json.loads(raw)
                        except ValueError:
                            continue
                        candidates = packet.get("candidates", [])
                        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
                        piece = "".join(part.get("text", "") for part in parts if part.get("text"))
                        if piece:
                            chunks.append(piece)
                            yield "data: " + json.dumps({"text": piece}, ensure_ascii=False) + "\n\n"
            reply = "".join(chunks)
            if not reply.strip():
                yield "data: " + json.dumps({"error": "The AI provider returned an empty response."}) + "\n\n"
                return
            now = datetime.now(timezone.utc)
            title = (record or {}).get("title") or payload.message.strip()[:48] or "New chat"
            await store.chats.update_one(
                {"_id": chat_id, "user_id": user["_id"]},
                {
                    "$set": {"title": title, "updated_at": now},
                    "$push": {"messages": {"$each": [
                        {"role": "user", "content": payload.message.strip()},
                        {"role": "model", "content": reply},
                    ], "$slice": -100}},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
            yield "data: " + json.dumps({"done": True, "chat_id": chat_id, "model": GEMINI_MODEL}) + "\n\n"
        except httpx.TimeoutException:
            yield "data: " + json.dumps({"error": "The AI provider took too long to respond. Try again."}) + "\n\n"
        except httpx.RequestError:
            yield "data: " + json.dumps({"error": "Could not connect to the AI provider."}) + "\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
async def chat(payload: ChatRequest, user=Depends(current_user), _csrf=Depends(require_csrf)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured. Add GEMINI_API_KEY to backend environment variables.")
    store = database()
    chat_id = payload.chat_id or str(uuid4())
    record = await store.chats.find_one({"_id": chat_id, "user_id": user["_id"]})
    if payload.chat_id and not record:
        raise HTTPException(status_code=404, detail="Chat not found.")
    contents = []
    for item in payload.history[-20:]:
        text = item.content.strip()
        if text:
            contents.append({"role": item.role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": payload.message.strip()}]})
    system_prompt = (
        "You are JustAI, a helpful, accurate, friendly AI assistant. Answer in the language used by the user. "
        "Understand Tamil written in Latin letters (Tanglish) and reply naturally in the same style when appropriate. "
        "Explain technical topics clearly, help with coding, and use Markdown when useful. "
        "Never claim to have performed actions you did not perform. If unsure, say so."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": system_prompt}]}, "contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(url, headers={"x-goog-api-key": GEMINI_API_KEY}, json=body)
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
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="The AI provider took too long to respond. Try again.")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not connect to the AI provider.")
    now = datetime.now(timezone.utc)
    title = (record or {}).get("title") or payload.message.strip()[:48] or "New chat"
    await store.chats.update_one(
        {"_id": chat_id, "user_id": user["_id"]},
        {
            "$set": {"title": title, "updated_at": now},
            "$push": {"messages": {"$each": [
                {"role": "user", "content": payload.message.strip()},
                {"role": "model", "content": reply},
            ], "$slice": -100}},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"reply": reply, "model": GEMINI_MODEL, "chat_id": chat_id}
