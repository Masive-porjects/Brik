# waveai-orchestrator — Cloudflare Containers orchestrator (phase 1 spike)

A minimal Cloudflare Worker that fronts the existing AudioMind FastAPI DSP
image (`apps/audiomind/Dockerfile`) on Cloudflare Containers. It is the
orchestration cornerstone of the Cloudflare migration: the browser keeps
uploading/downloading audio straight against R2 as the phases land, while
this Worker owns routing into the 4 vCPU / 12 GiB DSP containers.

## Quick path

1. Prerequisites: a Cloudflare account with the Workers **Paid** plan
   (Containers are not available on Free) and `r2` + `containers` enabled.
2. `npx wrangler login` inside this folder.
3. Install once in this folder so the workspace root `bun install` of the
   main repo does not pull Wrangler for CI:
   `npm install --prefix . --no-save` or a plain `bun install` here.
4. Deploy a preview: `npx wrangler deploy` → use the printed
   `*.workers.dev` URL.
5. Smoke: `curl <preview>/__diag` (orchestrator alive) and
   `curl <preview>/health` (proxied into the container). For the full DSP
   smoke, upload the 6 s fixture with `POST /api/upload` then run
   `POST /api/session/{id}/process` against the same preview URL;
   expect `completed` with `progress=1.0`.

## What deploys

| Component | File | Role |
|-----------|------|------|
| `DSPContainer` | `src/container.ts` | Keyed container instance of the AudioMind image, port 8000, sleep 10m |
| Worker router | `src/index.ts` | `/__diag` liveness; `/api/*` proxy to the keyed instance |
| Wrangler config | `wrangler.jsonc` | Builds `../audiomind/Dockerfile` into the managed registry, `standard-4` |

## Phase plan

| Phase | Scope | Gate |
|-------|-------|------|
| 1 (this spike) | Worker + container `/health` and `/process` smoke | preview URL responds |
| 2 | Browser → R2 presigned upload/download (endpoint already exists in the backend) | 100 MB file never crosses the Worker |
| 3 | Cloudflare Queues: producer + consumer, one job per keyed container | DLQ on poison job |
| 4 | Studio on Workers via OpenNext | independent of the backend |
| 5 | DNS/cutover; Railway kept warm as rollback | p95 + cost validated |

## Notes and known caveats

- The spike routes everything to the single `dsp-smoke` key; phase 3 will
  key one instance per job id.
- The container stores sessions in memory per instance; pin
  `AUDIOMIND_SESSION_STORE_BACKEND=supabase` before any multi-instance
  routing, otherwise state does not survive between `env.DSP.get()` keys.
- Wrangler builds the image from `../audiomind/Dockerfile`; the
  `ENV PORT=8000` pin there keeps the container aligned with
  `defaultPort = 8000` (Cloudflare does not inject `$PORT` like Railway —
  Railway still overrides it at runtime, so main-side deploys are unaffected).
- If `wrangler deploy` rejects the DO migration, switch
  `new_sqlite_classes` to `new_classes` in `wrangler.jsonc`.
