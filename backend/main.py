import os
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
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
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
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE)
    return {"signed_out": True}


@app.get("/api/auth/me")
async def me(user=Depends(current_user), csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME)):
    return {"user": public_user(user), "csrf_token": csrf_cookie}


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
    messages = (record or {}).get("messages", [])
    messages.extend([{"role": "user", "content": payload.message.strip()}, {"role": "model", "content": reply}])
    title = (record or {}).get("title") or payload.message.strip()[:48] or "New chat"
    await store.chats.update_one(
        {"_id": chat_id, "user_id": user["_id"]},
        {"$set": {"title": title, "messages": messages[-100:], "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"reply": reply, "model": GEMINI_MODEL, "chat_id": chat_id}
