# DEPLOY_RUNBOOK.md — WaveAI demo deployment (Vercel + Railway)

> **Branch:** `demo/vercel-railway-client` · **Remote:** `waveia` → https://github.com/waveiamusic/WaveIA.git
> **Status:** prepared — no deployment executed, no credentials used.
> **Architecture source of truth:** `docs/runbooks/DEMO_DEPLOYMENT_PLAN.md` (LOCKED). This runbook does not change it.
> **Date:** 2026-09-12

---

## 0. Locked architecture (recap, non-negotiable)

```
Browser → Vercel        → apps/studio (Next.js — UI only, no backend code)
Browser → Railway       → apps/audiomind (FastAPI — upload, analysis, session, process, WAV download)
```

- **NO** `Browser → Vercel API → Railway`, no Server Actions → Railway, no Next.js route proxying audio.
- `apps/audiomind` is deployed to **Railway only**; `apps/studio` is **never** deployed to Railway.
- Neutral parameters = audio passthrough must be preserved on every route (do not touch DSP defaults).

---

## 1. Environment variables (exact names — extracted from code, do not invent)

### 1.1 Backend — Railway (settings in `apps/audiomind/src/audiomind/config.py`, `env_prefix = "AUDIOMIND_"`)

> ⚠️ **CORS env name:** the plan sheet says `CORS_ORIGINS`, but pydantic-settings applies the
> `AUDIOMIND_` prefix to every field. A bare `CORS_ORIGINS` variable is **silently ignored**.
> The real name is **`AUDIOMIND_CORS_ORIGINS`** (a JSON-encoded string array).

| Variable | Value (demo) | Notes |
|---|---|---|
| `AUDIOMIND_CORS_ORIGINS` | `["https://<vercel-domain>", "http://localhost:3000"]` | JSON array string. Replaces the whole default list; keep `http://localhost:3000` for local UI testing against the prod backend. Add the exact Vercel domain **before** the public smoke (plan step 9). |
| `AUDIOMIND_PRERENDER_MODE` | `on_demand` | Upload ends in `uploaded` with zero automatic DSP. |
| `AUDIOMIND_MAX_CONCURRENT_DSP` | `1` | Serializes heavy DSP (never two pipelines at once). |
| `AUDIOMIND_DEMO_MAX_DURATION_SECONDS` | `240` | Demo cap: 4 min per track. |
| `AUDIOMIND_MAX_FILE_SIZE_MB` | `100` | Covers 4-min PCM24 44.1 kHz stereo (~63.5 MB) with headroom. |
| `AUDIOMIND_SESSION_TTL_MINUTES` | `60` | Janitor prunes idle uploads + masters. |
| `AUDIOMIND_DEBUG` | `false` | Optional; defaults to `true` in code. |
| `AUDIOMIND_LICENSE_KEY` | **leave unset/empty** | Demo intent: with no key, `LicenseGuard` unlocks automatically. Setting a key locks the Studio to a license screen. |

Verified source: `config.py` lines 40–55 (license, prerender, concurrency, duration, session TTL) — the demo values match `apps/audiomind/.env.demo.example` and `scripts/validate_demo_duration.py`.

### 1.2 Frontend — Vercel (read by `apps/studio/src/adapters/api/config.ts` and `src/lib/basePath.ts`)

| Variable | Value (demo) | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<backend-railway>/api` | Contract: must end in `/api` (backend mounts all routers under that prefix). Trailing slash / double `/api` are auto-normalized client-side. Inlined at build time — set it before the first deploy. |
| `NEXT_PUBLIC_BASE_PATH` | **leave unset** | `""` = serve at the Vercel domain root. Only needed if the app is later mounted under a subpath (e.g. `/waveai`). |
| ~~`NEXT_PUBLIC_REQUIRE_AUTH`~~ | **removed** | The login flow was removed from the frontend — the env var no longer does anything. |
| `NEXT_PUBLIC_CONVEX_URL` | **not needed** | `ConvexClientProvider` is a passthrough; the app has zero `convex/_generated` imports today. |
| `ELEVENLABS_*` | **not needed** | Voice agent runtime is off in the demo UI. |

---

## 2. Deployment order (locked by the plan §2 — follow it literally)

```
1. Backend ONLY on Railway (never apps/studio)
2. Railway canary: 15 / 45 / 60 s
3. If stable → 210 s
4. If stable and RAM allows → 240 s
5. Only with an approved backend → deploy apps/studio on Vercel
6. Set NEXT_PUBLIC_API_URL on Vercel → https://<backend-railway>/api
7. Add the exact Vercel domain to AUDIOMIND_CORS_ORIGINS
8. Public smoke → public 240 s controlled test
```

**RAM gate (from the local staircase, plan §1):** 45–60 s → ≥2 GB; 210 s → ≥6 GB;
240 s → ≥8 GB per replica (measured peaks 1.3 / 1.8 / 5.6 / 6.95 GB). Verify the effective
service limit in the Railway dashboard **before** each stage; stop the escalation on OOM or
inviable response time — never deploy the frontend against an unapproved backend.

---

## 3. Railway — backend deploy (dashboard)

1. `railway login` via browser, or Dashboard → your team.
2. **New Project → Deploy from GitHub repo** → select `waveiamusic/WaveIA`.
3. In the service creation dialog:
   - **Root Directory:** `apps/audiomind` ← required (the repo also has a legacy root `railway.json`, see §6.3 — do not use the repo root).
   - Builder reads `apps/audiomind/railway.json` → `DOCKERFILE` (Nixpacks is NOT used — see §6.1), restart on failure (3 retries), healthcheck `GET /health` with a 300 s timeout (librosa imports make boot slow).
4. **Variables:** set the table in §1.1. Do **not** set `AUDIOMIND_LICENSE_KEY`.
5. **Settings → Networking:** enable **Public Networking** (required for the healthcheck and for browser → backend calls). Copy the generated URL, e.g. `https://audiomind-production-xxxx.up.railway.app`.
6. **Settings → Deploy (service):** check the current RAM/CPU limit. For the canary stages, set at least the RAM from the gate table above (Hobby advertises up to 8 GB/replica — confirm what is actually assigned).
7. **Deploy** the service (first deploy builds the Docker image; expect several minutes: onnxruntime + librosa wheels).
8. **Smoke (backend, the plan's canary order):**
   ```bash
   curl -s https://<backend-railway>/health
   # → {"status":"ok","service":"AudioMind"}
   curl -s -H "Origin: http://localhost:3000" -i https://<backend-railway>/api/license/status | Select-String -i "access-control-allow-origin|200"
   ```
   Then run the real canary: upload a **15 s** WAV, master it, download it; repeat with **45 s** and **60 s**; then **210 s**; then **240 s** only if RAM allows. Each stage reuses the local staircase evidence (RAM gate).
9. If a stage fails (OOM, crash, inviable response time): stop the escalation and review the RAM plan — do not proceed to Vercel.

### 3.1 Railway CLI alternative

```bash
npm i -g @railway/cli        # or: npm i -g railway
railway login                # browser flow
railway init                 # link to the project (or create it)
railway link                 # select the service
railway variables set AUDIOMIND_PRERENDER_MODE=on_demand AUDIOMIND_MAX_CONCURRENT_DSP=1 AUDIOMIND_DEMO_MAX_DURATION_SECONDS=240 AUDIOMIND_MAX_FILE_SIZE_MB=100 AUDIOMIND_SESSION_TTL_MINUTES=60 AUDIOMIND_DEBUG=false "AUDIOMIND_CORS_ORIGINS=[\"https://<vercel-domain>\", \"http://localhost:3000\"]"
railway up                   # deploy the current branch service (root dir apps/audiomind)
```

---

## 4. Vercel — Studio deploy (dashboard)

> **Important research findings (Vercel docs, 2026-09-12):**
> - **Root Directory is a project setting**, not a `vercel.json` key — it must be set in the dashboard (or via `vercel link` in the CLI flow).
> - Vercel auto-detects the package manager from the **lockfile at the repository root** (`bun.lock` is committed) → Bun 1.x → `bun install`. The install command should be left at **default (auto)** — overriding it makes Vercel pick the oldest Bun available in the build container, and old Bun cannot read the text `bun.lock`. That is why `apps/studio/vercel.json` sets only `framework` + `buildCommand`.
> - **"Include source files outside of the Root Directory"** is enabled by default for new projects — the build needs it: `bun run build` runs `bun run --filter @midimastering/agent build && next build`, and bun must reach the root `package.json` (workspaces), `bun.lock`, and `apps/agent` from `apps/studio`. If a deploy fails with the agent package unresolved, check this setting.

1. `vercel login` (browser) or Dashboard → **Add New… → Project**.
2. **Import Git Repository** → `waveiamusic/WaveIA` (the `waveia` remote).
3. Before deploy, **Edit → Root Directory → `apps/studio`**.
4. Settings applied from `apps/studio/vercel.json` (read automatically):
   - Framework Preset: **Next.js**
   - Build Command: `bun run build` (package script: `bun run --filter @midimastering/agent build && next build`, verified locally in SETUP.md §6)
   - Install Command: `bun install` (auto-detected, do not override)
   - Root Directory: `apps/studio` (dashboard setting, step 3)
5. **Settings → Git → Production Branch:** set the **Production Branch** to **`main`** (decision 2026-09-13): **any merge/push to `main` deploys directly to production.** Do not use a demo branch as the production source — main is always up to date and is the single source of truth for what ships.
6. **Settings → Environment Variables:** add the table in §1.2 (`NEXT_PUBLIC_API_URL=https://<backend-railway>/api`). `NEXT_PUBLIC_*` is inlined at build time — it must exist before the build starts.
7. Click **Deploy**. Copy the production URL, e.g. `https://waveai-studio.vercel.app`.
8. **Smoke (frontend standalone):** the page loads, the mastering tab renders, no console 4xx to `/api/*` on the Vercel origin.

### 4.1 Vercel CLI alternative

```bash
npm i -g vercel
vercel login                       # browser flow
vercel link --repo                 # link the monorepo (repo mode), pick the studio project
vercel env add NEXT_PUBLIC_API_URL production   # https://<backend-railway>/api
vercel --prod                      # deploys apps/studio as the linked project
```

---

## 5. CORS wiring + end-to-end smoke (plan steps 9–11)

1. Backend is approved, Vercel URL is live.
2. Update **`AUDIOMIND_CORS_ORIGINS`** in Railway → include the **exact** Vercel production origin (e.g. `https://waveai-studio.vercel.app`). Redeploy (or rely on `railway up`).
   > Why: a CORS-silent 502 makes the frontend "freeze" mid-master (comment in `config.py`).
3. Verify the CORS header from the browser's origin:
   ```bash
   curl -s -H "Origin: https://<vercel-domain>" -i https://<backend-railway>/api/license/status | Select-String -i "access-control-allow-origin"
   # → access-control-allow-origin: https://<vercel-domain>
   ```
4. **End-to-end smoke (real browser on the Vercel URL):** upload a 15 s WAV → status passes `uploaded → analyzing → processing → completed` → download the master (PCM24 WAV served by Railway directly). Then the **public 240 s controlled test** with the RAM gate checked (§2).

---

## 6. Decisions, validations and pending items

| # | Item | Decision / state |
|---|---|---|
| 6.1 | **Nixpacks vs Docker (backend)** | **Dockerfile** (existing, v3): `python:3.11-slim` satisfies `requires-python = ">=3.11"` (verified `apps/audiomind/pyproject.toml`); slim/glibc is required because onnxruntime/demucs have no musllinux wheels; editable install `--no-deps -e .` is required because `config.py` resolves `uploads/outputs` from `Path(__file__).parent*3` (paths break with a regular install). No Dockerfile change needed. Port: `$PORT` (Railway-provided, falls back to 8080) matches `EXPOSE 8080`. |
| 6.2 | **Healthcheck** | Added `deploy.healthcheckPath: "/health"` + `healthcheckTimeout: 300` to `apps/audiomind/railway.json`. Verified `GET /health` exists in `app/main.py` (no `/api` prefix) and returns fast once the app is up. Requires **Public Networking** enabled. |
| 6.3 | **Root `railway.json`** | **Legacy config of the old frontend-on-Railway service** (Nixpacks + bun → builds `apps/studio`). The locked architecture forbids that. Left untouched (deleting/modifying it would alter the old service's next redeploy); the runbook forbids creating new Railway services at the repo root. After the old frontend service is stopped, delete the file. |
| 6.4 | **Dead Next.js rewrites** | `next.config.ts` proxied `/api/*` → backend, but **no code uses relative `/api` paths** (verified: all calls go through `API_BASE`, absolute). Rewrites removed to align with the no-proxy architecture; `basePath` logic kept (root on Vercel, no `NEXT_PUBLIC_BASE_PATH`). |
| 6.5 | **Bun monorepo on Vercel** | Works without a custom install command: committed root `bun.lock` → Bun 1.x auto-detected, monorepo detected via root `package.json` `workspaces: ["apps/*"]`. Build runs in `apps/studio` with source-outside-root enabled (default) so `bun run --filter @midimastering/agent build` (tsc → `dist/`) and `next build` resolve correctly. |
| 6.6 | **`.dockerignore`** | Added to `apps/audiomind/` — the local context holds ~1.8 GB of gitignored junk (outputs 1.07 GB, uploads 265 MB, .venv 496 MB). Keeps Railway builds fast and within quota; also excludes `.env*` secrets. |
| 6.7 | **PENDING — RAM cap** | The effective per-replica RAM on the Hobby plan must be verified in the Railway dashboard before each canary stage (§2 gate). The plan does not declare Hobby a no-go: it says verify. |
| 6.8 | **PENDING — exact Vercel domain** | Unknown until the Vercel project is created; it is a required input for `AUDIOMIND_CORS_ORIGINS` (§5). |
| 6.9 | **PENDING — Railway uses latest commit** | Railway deploys from GitHub commits; the branch must be pushed via the `waveia` remote before the service can build (orchestrator handles commits/push). |
| 6.10 | **Production Branch = `main` (decision 2026-09-13)** | Vercel **wave-ia-studio** Production Branch must be `main`. Merging/pushing to `main` = direct production deploy. Build Command override: **disable it** so `apps/studio/vercel.json` applies (`bun run build`) — a bare `next build` fails because `@midimastering/agent` `dist/` is not committed (tsc must run first via the workspace filter). |

---

## 7. Local verification to run before declaring any of this "done"

```bash
cd apps/studio && bun run lint
cd apps/studio && bunx tsc --noEmit        # expect only the 3 known convex/mastering.ts errors from Tomás (SETUP.md pitfall #5)
python -c "import json,sys; json.load(open('railway.json'))"
python -c "import json,sys; json.load(open('apps/audiomind/railway.json'))"
python -c "import json,sys; json.load(open('apps/studio/vercel.json'))"
git diff --stat
```