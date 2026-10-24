# Deploying AutoSRE (Render + Vercel)

The hosted version runs the **Docker-free prototype**: a fixture database, cached sandbox checks and a
local git "origin". Everything (incident, fix, PR, merge conflict, merge) plays end to end, no Postgres needed.

Deploy the backend first, because the frontend needs its URL.

## 1. Backend on Render

1. Push this repo to GitHub (Render deploys from a branch).
2. On [render.com](https://render.com): **New → Blueprint**, pick the repo and branch. Render reads `render.yaml`.
3. It asks for the `sync: false` values. For now enter a placeholder, such as `https://example.com`, for
   `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL`. Leave `GROQ_API_KEY` empty for cached mode.
4. Wait for the deploy, then open `https://<service>.onrender.com/api/v1/health`. It should say `healthy`.

Notes:
- Free plan: the service sleeps after 15 min idle, and the first request after that takes about 1 minute.
- State is SQLite on the instance disk, so incidents reset on every deploy or restart. That is fine for a demo.
- One uvicorn worker on purpose: incidents run in background threads inside that process.

## 2. Frontend on Vercel

1. On [vercel.com](https://vercel.com): **Add New → Project**, import the repo.
2. Set **Root Directory** to `frontend` (Vercel detects Vite. `frontend/vercel.json` covers the rest).
3. Add the environment variable `VITE_API_BASE_URL` = `https://<service>.onrender.com` (no trailing slash).
4. Deploy and copy the production URL, for example `https://zero-ops-autosre.vercel.app`.

## 3. Connect them

On Render, open the service's **Environment** tab and set:

| Key | Value |
| --- | --- |
| `CORS_ALLOWED_ORIGINS` | your Vercel URL, e.g. `https://zero-ops-autosre.vercel.app` |
| `FRONTEND_URL` | the same URL |
| `CORS_ALLOWED_ORIGIN_REGEXES` (optional) | `^https://zero-ops-autosre-.*\.vercel\.app$` to allow preview deploys |

Save. Render redeploys. Then open the Vercel URL → **Controls → Play prototype**.

`VITE_API_BASE_URL` is baked in at build time, so redeploy on Vercel if the backend URL changes.

## Live LLM mode (optional)

On Render, set `AUTOSRE_MODE=live` and `GROQ_API_KEY=...`. The sandbox stays `cached` (Render has no Docker).
