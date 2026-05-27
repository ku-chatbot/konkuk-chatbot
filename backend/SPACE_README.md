---
title: Kubot Backend
emoji: 🏢
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: kubot-backend
---

# Kubot Backend

FastAPI backend for KU-Bot.

This Space runs two processes in one Docker container:

- Embedding server: `127.0.0.1:9000`
- Main FastAPI server: `0.0.0.0:7860`

Required secrets:

- `OPENAI_API_KEY`
- `SECRET_KEY`

Optional web search secrets:

- `ENABLE_WEB_SEARCH=true`
- `TAVILY_API_KEY`

Frontend CORS:

- `FRONTEND_ORIGIN=https://your-vercel-app.vercel.app`
