# JustAI

A mobile-first, full-stack AI assistant built with React + Vite, FastAPI, MongoDB Atlas, and Google Gemini.

## Features in this build
- Responsive chat interface with premium dark and light themes
- Account registration and sign-in
- Argon2 password hashing and signed JWT sessions in HttpOnly cookies
- CSRF-token checks for state-changing requests including logout; session and CSRF cookies are HttpOnly and tokens stay out of browser localStorage
- MongoDB-backed conversations synced to the signed-in account
- Open, rename, delete, and automatically title chat history
- Real on-device AI chat using Qwen2.5 0.5B through WebLLM in WebGPU-capable browsers (no Gemini/OpenAI API key required)
- Optional Gemini server provider remains available when a backend Gemini key is configured
- Training Studio with JSONL file import, private datasets, queued LoRA jobs, automatic job-status refresh, and an adapter registry
- Server-sent-event streaming so assistant text appears as it is generated
- Tanglish/Tamil-aware assistant instructions
- Markdown and code rendering, copy responses, prompt starters, and an auto-growing mobile chat composer
- Gemini and database credentials stay on the backend

## Project structure
- `frontend/` — React + Vite application
- `backend/` — FastAPI API, authentication, MongoDB persistence, Gemini integration, and optional model-training worker
- `frontend/src/TrainingStudio.jsx` — dataset manager and fine-tuning dashboard

## Backend setup
1. Use Python 3.11 or newer.
2. Open a terminal in `backend/`.
3. Install: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`.
5. Set `GEMINI_API_KEY`, `MONGODB_URI`, `MONGODB_DATABASE`, `JWT_SECRET` (random string, 32+ characters), `APP_ENV=development`, and `CORS_ORIGINS`.
6. Run: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

API health: `http://localhost:8000/health`  
API docs: `http://localhost:8000/docs`

## Frontend setup
1. Use Node.js 20 or newer.
2. Run `cd frontend && npm install`.
3. Copy `.env.example` to `.env` and set `VITE_API_BASE_URL` to your backend URL.
4. Run `npm run dev`.
5. Create a production build with `npm run build`.

## Deployment
### Backend on Render
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add `MONGODB_URI`, `MONGODB_DATABASE`, `JWT_SECRET`, `APP_ENV=production`, and `CORS_ORIGINS` in Render environment settings. `GEMINI_API_KEY` is optional and only needed if you later use the Gemini server route.
- `APP_ENV=production` enables `Secure` + `SameSite=None` session cookies for the cross-site Vercel frontend and Render API. Use HTTPS and set `CORS_ORIGINS` to the exact Vercel origin (no wildcard).

### Frontend on Vercel
- Root directory: `frontend`
- Framework preset: Vite
- Build command: `npm run build`
- Output directory: `dist`
- Set `VITE_API_BASE_URL` to the deployed backend URL.

Set `CORS_ORIGINS` to the exact deployed frontend origin. The frontend sends credentialed requests and receives a CSRF token in the auth response; both session and CSRF cookies are HttpOnly. Never put Gemini, MongoDB, or JWT secrets in `VITE_*` variables or commit a real `.env` file.

## Own model training (optional)

JustAI includes a Training Studio for creating private chat datasets, queuing fine-tuning jobs, and tracking saved LoRA adapters. The first training target is the small open-weight `Qwen/Qwen2.5-0.5B-Instruct` model. This is fine-tuning, not training a foundation model from random initialization.

The Render API only validates and queues jobs. Actual model training must run in a separate worker environment with sufficient RAM and preferably a CUDA GPU. Follow [backend/training/README.md](backend/training/README.md), install `backend/requirements-training.txt` in that worker, configure the same MongoDB database plus a persistent `MODEL_OUTPUT_DIR`, and start `python -m training.worker` from `backend/`.

The first release saves LoRA adapters in the model registry. It does not yet activate a trained adapter in live chat. Browser-local chat currently uses the base Qwen2.5 0.5B model; trained adapter inference/activation and persistent artifact hosting remain later steps. Do not upload private, confidential, or unlicensed data.

## API routes
- `GET /`, `GET /health`
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `GET /api/chats`, `GET /api/chats/{id}`, `PATCH /api/chats/{id}`, `DELETE /api/chats/{id}`
- `GET /api/training/overview`, `GET /api/training/datasets`, `POST /api/training/datasets`
- `GET /api/training/jobs`, `POST /api/training/jobs`, `GET /api/training/models`
- `POST /api/chat` (complete response)
- `POST /api/chat/stream` (Gemini server-side streaming, optional)
- `POST /api/chat/local/save` (persist a response generated on-device by WebLLM)

## Current scope
This is an original AI assistant using open-weight Qwen locally in the browser by default, with optional Gemini API support, not a copy of OpenAI's proprietary ChatGPT service. Image/document input, voice, password reset, and account deletion are not included in this increment. Streaming uses the Gemini streaming API and saves the completed exchange to MongoDB.


## Browser-local AI (no cloud API key)

The default chat provider runs the open-weight Qwen2.5 0.5B Instruct model directly in the browser using WebLLM and WebGPU. The model is downloaded on first use and cached by the browser. Select **Load local model** before chatting to check device support and show download progress. Prompts and generated text are processed on the device; only the completed user/assistant exchange is sent to the authenticated API to save in MongoDB.

Requirements and limitations:
- A browser/device with working WebGPU and enough GPU memory is required. WebGPU is not available on every phone or browser; unsupported devices cannot use this local provider.
- The first model download can be large and requires an internet connection. Later use may reuse the browser cache.
- Local inference uses the device's own memory, battery, and GPU. Performance varies significantly by device.
- The Render API does not host or run the model. It only handles account/session security and conversation persistence.
- The Qwen model runs with its published model weights. The separate Training Studio LoRA adapters are not yet loaded into this browser runtime.
