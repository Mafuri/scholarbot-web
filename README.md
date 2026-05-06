# ScholarBot Web Platform — Deployment Guide
# =============================================

## Quick Deploy Options

### Option 1: Render.com (Recommended — Free tier)
1. Push this folder to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Set environment variables (see below)
5. Click Deploy — live in ~3 minutes

### Option 2: Railway.app
1. Push to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Set PORT=8000 and other env vars
4. Deploy

### Option 3: Run locally
```
pip install -r requirements.txt
uvicorn web_app:app --reload --port 8000
```
Open http://localhost:8000

---

## Environment Variables

Set these in your hosting dashboard:

| Variable | Required | Description |
|----------|----------|-------------|
| ANTHROPIC_API_KEY | Recommended | For Claude-powered essay generation |
| OLLAMA_BASE_URL | Optional | e.g. http://localhost:11434 if self-hosting Ollama |
| OLLAMA_MODEL | Optional | Default: llama3.2:1b |
| SECRET_KEY | Recommended | Random string for security |

---

## LLM Options

ScholarBot needs an LLM to write essays. Three options:

### Option A: Anthropic Claude (best quality, cloud)
- Get API key at https://console.anthropic.com
- Set ANTHROPIC_API_KEY in your hosting dashboard
- Uses claude-haiku for cost efficiency (~$0.01 per essay)

### Option B: Ollama (free, runs locally)
- Install Ollama: https://ollama.ai
- Run: `ollama pull llama3.2:1b`
- Set OLLAMA_BASE_URL=http://localhost:11434

### Option C: No LLM (template essays)
- Leave both unset — ScholarBot uses template essays
- Still works for matching, scoring, and briefing pages

---

## Features

| Feature | UG | Graduate | Postgraduate |
|---------|----|---------:|-------------:|
| Scholarship matching | ✅ | ✅ | ✅ |
| Essay generation | ✅ | ✅ | ✅ |
| Application packages | ✅ | ✅ | ✅ |
| Interview coach | ✅ | ✅ | ✅ |
| Profile from CV | ✅ | ✅ | ✅ |
| Deadline tracking | ✅ | ✅ | ✅ |

---

## API Endpoints

All endpoints documented at /docs (FastAPI auto-docs)

Auth: POST /api/auth/register, /api/auth/login, GET /api/auth/me
Scholarships: GET /api/scholarships, /api/scholarships/matched
Essays: POST /api/essays/generate, GET /api/essays/{id}
Packages: POST /api/packages/prepare, GET /api/packages
Interview: GET /api/interview/questions/{scholarship}, POST /api/interview/score
Dashboard: GET /api/dashboard
Health: GET /api/health
