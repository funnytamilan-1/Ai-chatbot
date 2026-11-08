# JustAI

A mobile-first AI assistant web app built with React, Vite, FastAPI, and Google Gemini.

## Included in this first release

- Responsive chat interface with premium dark and light themes
- Multiple conversations saved in the browser on the current device
- Recent conversation context sent to the AI model
- Markdown and code rendering
- Copy responses, delete chats, and prompt starters
- FastAPI backend keeps the Gemini API key off the frontend
- Health endpoint and clear provider error handling

## Project structure

- `frontend/` — React + Vite application
- `backend/` — FastAPI AI service

## Run locally

### Backend

1. Use Python 3.10 or newer.
2. Open a terminal in `backend/`.
3. Install packages: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and add your Gemini API key.
5. Start the API: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

API health: `http://localhost:8000/health`  
API docs: `http://localhost:8000/docs`

### Frontend

1. Open another terminal in `frontend/`.
2. Install packages: `npm install`
3. Copy `.env.example` to `.env` if the backend is not running at `http://localhost:8000`.
4. Start Vite: `npm run dev`

## Environment variables

### Backend

- `GEMINI_API_KEY` — required; keep this secret and configure it only on the backend host.
- `GEMINI_MODEL` — defaults to `gemini-2.5-flash`.
- `FRONTEND_URL` — frontend origin allowed by CORS.

### Frontend

- `VITE_API_BASE_URL` — backend base URL. This is public configuration, not a secret.

## Deploy

### Backend on Render

- Create a Python web service from this repository.
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add `GEMINI_API_KEY`, `GEMINI_MODEL`, and `FRONTEND_URL` in the service environment.

### Frontend on Vercel

- Import this repository.
- Root directory: `frontend`
- Framework preset: Vite
- Build command: `npm run build`
- Output directory: `dist`
- Add `VITE_API_BASE_URL` with the deployed backend URL before building.

## Current limitations

This is a functional first foundation, not a copy of OpenAI's proprietary ChatGPT service. Conversation history is stored in browser local storage on that device. Authentication, cloud-synced history, image/document understanding, voice, and token streaming are not implemented yet and should be added as separate modules. Never put provider API keys in frontend code or commit a real `.env` file.
