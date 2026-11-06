# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha del relevamiento**: 2026-11-06 · **Base verificada**: `waveia/main` @ `20cf2d1`.
> **Novedades (5-nov → 6-nov)**: tema claro/oscuro aplicado a TODO el sitio (landing, upload, mezclas) — commit `7fcfeec` ya desplegado en Vercel Production (success, sha `20cf2d1`); biblioteca "Mis Canciones" se refresca al abrir el modal — commit `20cf2d1`; correcciones de auth 401/Bearer/persistencia de sesión (`cea33fc`, `c0c285f`, `6d252f9`, `b32de23`); rendimiento (WaveformBars → canvas único, IntersectionObserver, `contain: layout`) (`4455a97`, `c667147`, `d81548d`); mix "anillo indeterminado" y etapa real en progreso 0 % (`c748507`). Backend AudioMind suite: **1634 passed / 0 failed**. Studio suite: **191 passed / 3 fallos preexistentes** (`logTrackEvent.test.ts`, mock carece de `.upsert()`). Build: OK · ESLint: 0 errores / 41 warnings.
> **Operación de ramas acordada**: cambios puntuales empiezan en `main`; si el alcance requiere integración, se trabaja primero en `develop` y luego se integra a `main`. No dejar trabajo funcional únicamente en ramas locales.
> **Alcance**: repositorio completo — los dos motores DSP vivos (Mastering, Mix), el flujo de proyectos multitenant, landing, Studio, agentes de IA, capa de inteligencia, contratos, orquestador Cloudflare, entorno, CI/CD, ramas y pendientes — más la **guía de cómo funciona el sistema de extremo a extremo (§9)**: topología, vida de una sesión, jobs, agente, mix, frontend, auth, almacenamiento y release. El Live Engine, Convex, `apps/bridge` y `simulator/` ya no existen; ver §5.
> **Fuentes**: código (`apps/`, `packages/`, `supabase/`, `e2e/`), estado git real verificado hoy, workflow de CI leído en el árbol y suites de verificación ejecutadas (fechas citadas en cada cifra).

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | 🟡 Código en `main`, API productiva en Cloudflare Containers · cadena proporcional + Character Stage + métricas reales (`band_energies_dbfs`, `GET /api/session/{id}/metrics`, `ChangeReport`) · **SSE `GET /api/jobs/agent/{id}/events` ya en `main`** (pendiente de publicar en la imagen del contenedor vía `wrangler deploy`) · suite **1634 passed / 0 failed** (6-nov; 1 warning preexistente de Starlette) · ruff 0 errores, gate bloqueante en CI |
| **Motor de Mezcla (Mix Engine)** | ✅ Pasos 01–08 (TDD estricto) + Stem Balance T1–T7 + Character Stage P3/P4 (`texture_recipe` v2 con deltas medidos) + P5 wiring async/proyecto · defecto del camino async corregido y commiteado · fix "anillo indeterminado / etapa real en progreso 0 %" (`c748507`) · queda el A/B auditivo con la sesión hip_hop del productor (su WAV no está en el repo) |
| **Flujo de proyectos multitenant ("Moises")** | 🟡 Backend completo (WU1–WU5) + subida directa de originales a R2 verificada · **UI dormida**: `ProjectContext`/`useProject` y los stores siguen sin consumidores · falta cargar las 4 tablas y env en producción |
| **Orquestador / API Cloudflare Containers** | ✅ **En producción**: Worker `waveai-orchestrator` enruta a `DSPContainer` `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB) con imagen v3 · `GET /api/license/status` con ACAO 200 para `www` y apex; preflight `OPTIONS /api/upload` 200 para `www` · **pendiente** redeploy del código `b462cf6` en adelante para activar SSE en el contenedor (fase 6–7) · fases 2–4 (R2 browser direct, Queues, OpenNext) siguen como roadmap |
| **Motor en vivo (Live Engine)** | ❌ **Removido del producto** (`ba3b4a6`, 27-Sep). Queda el schema como contrato dormido |
| **Landing page** | ✅ Nueva, en producción (Vercel) — GSAP, i18n completo, A/B demo local, SEO/JSON-LD · Tema claro/oscuro global ya aplicado (`7fcfeec`) · 3 decisiones de producto abiertas (#P3) |
| **Frontend y Mobile (web)** | ✅ Studio + landing · sin app nativa/PWA · `AgentPanel` persiste mensajes por sesión en Zustand/localStorage y consume SSE con fallback al GET de estado · `ChangeReport` renderiza · `/mezclas` y `/voz` usan shell `100dvh` · tema claro/oscuro en todo el árbol (tokens `var(--bg-app)`, `glass-elevated`, sin hardcodeos de color en upload/mastering) |
| **Agent de interpretación (IA)** | 🟡 Compila · `vocal_focus` en el contrato · **llamada real sin probar** (faltan credenciales Gemini) |
| **Productor IA (bucle agéntico, Python)** | 🟡 Bucle de 4 fases + tool calling + transporte model-agnostic · `POST /api/jobs/agent/{session_id}` + SSE `GET /api/jobs/agent/{id}/events` · publica stems luego de Demucs antes de mix/master · métricas reales y `ChangeReport` · corrida real con LLM todavía no verificada por credenciales |
| **Capa de inteligencia (RAG)** | 🟡 CLI local sobre los libros de mezcla (OCR, BM25+vector RRF, Ollama) · expuesto por `POST /api/agent/rag/search` (en el contenedor responde 503 sin índice) · el bucle agéntico **todavía no lo consume** · **aprobado como backlog**: RAG de producción "Opción A" (R2) |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | ❌ **Eliminado** (repo + CI) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** |
| **Deploy (Vercel + Cloudflare + R2 + Supabase)** | ✅ Frontend en Vercel (sha `20cf2d1` publicado, Production, success) · API AudioMind en Cloudflare Worker + Container · R2 para audio, Supabase para auth/metadata/jobs · Railway ya no es destino operativo |
| **Sesiones del backend** | ✅ Durables en Postgres (`sessions`, backend `auto`) con fallback a archivo · **aplicación en prod sin verificar** |
| **Suites de verificación** | AudioMind **1634 passed / 0 failed** (6-nov) · Studio full: **191 passed, 3 fallos preexistentes** en el mock de `logTrackEvent.test.ts` (`insert` vs `.upsert()`) · build exit 0 · ESLint 0 errores / 41 warnings · i18n ES/EN 806/806 · e2e no ejecutado |

---

## 2. Estado del repositorio (git, verificado 2026-11-06)

### 2.1 Ramas y remotes

| Remote | URL | Rol |
|---|---|---|
| `waveia` | `https://github.com/Masive-porjects/Brik.git` | **Producción/staging**: `main` y `develop` viven aquí (canónico) |
| `origin` | `https://github.com/brikpaul569-cmd/BrikMaster2027.git` | Espejo **stale**: `main` @ `1c0379b`, sin `develop`. **No tocar sin instrucción.** |

| Rama | Tip | Estado |
|---|---|---|
| `main` | `20cf2d1` | **== `waveia/main`** · rama activa · working tree limpio (salvo `apps/orchestrator/.wrangler/`, excluido) |
| `develop` | `92bb917` | **== `waveia/develop`** · 25 commits detrás de `main`; no usar para cambios nuevos hasta sincronizarlo desde `main` |
| `origin/main` | `1c0379b` | Espejo **stale**; no es fuente de trabajo |
| `feat/ui-sse-stems-chat-layout` | `b462cf6` | Ref local redundante: mismo commit que un ancestro de `main`, ya publicado |
| `feat/cf-orchestrator-spike` | `2219d2b` | Ref local histórica; el orquestador ya está en `main` y desplegado |

El remoto canónico es `waveia`; `origin` queda solo como espejo histórico. Cambios puntuales parten de `main`; para trabajo amplio, alinear `develop` desde `main`, trabajar allí y luego integrar a `main`. No dejar cambios funcionales únicamente en ramas locales.

### 2.2 Commits recientes en `main` (orden cronológico, más reciente primero)

| Commit | Fecha | Qué trajo |
|---|---|---|
| `20cf2d1` | 6-nov | `fix(library): refresh Mis Canciones when the modal opens` — `LibraryView` reconsulta la biblioteca cada vez que se abre el modal (antes solo fetchaba una vez al cargar la página) |
| `7fcfeec` | 6-nov | `fix(theme): make light mode apply to the whole landing` — tema claro/oscuro global en landing, upload y mezclas (tokens en `globals.css`, `layout.tsx` sin wipe de `localStorage`, `ThemeToggle` puro sin efectos en el setter) |
| `b32de23` | 5-nov | `fix(studio): track persistence in mis canciones, button visibility, audio fallback and sse timeouts` — pusheado a `waveia/main`; Vercel + Railway desplegaron ese SHA; `www.brikmusic.online` verificado |
| `6d252f9` | 5-nov | `fix(auth): refresh de sesión antes de redirigir en 401 + fallback de token en upload` |
| `cea33fc` | 5-nov | `fix(auth): enviar Bearer token en upload de audio y configurar persistencia de sesión Supabase` |
| `c0c285f` | 5-nov | `fix(auth): manejo automático de 401 en cliente de API` |
| `d81548d` | 5-nov | `perf(layout): eliminar lecturas de geometría en eventos de alta frecuencia` (WaveformBars → canvas único, requestAnimationFrame, sin getBoundingClientRect por elemento) |
| `c667147` | 5-nov | `perf(css): contención de estilo en contenedores independientes` (`contain: layout` en capas fixed) |
| `4455a97` | 5-nov | `perf(waveform): migrar 32 divs a un único canvas` + cache de rects en header/Player/ABPlayer |
| `c748507` | 5-nov | `fix(mix): anillo indeterminado y etapa real mientras progreso 0 %` |
| `683b425` | 5-nov | `fix(ui): upload CLS y filtro de presencia de stems (falsa voz)` |
| `3ace12d` | 5-nov | `fix(ui): mobile layout defects — auth scroll, dock, player hit areas, stems, 100dvh` |
| `4771b80` … `88e6b15` | 4-nov | Landing refactor + theme toggle + mobile menu (ver historial completo con `git log`) |

Untracked que **no** se comitea: `apps/orchestrator/.wrangler/` (excluido por `.git/info/exclude` junto con `odd/`, `.atl/`, `docs/proposals/` y `docs/postmortems/`).

---

## 3. Los motores

### 3.1 Motor 1 — Mastering (AudioMind, backend FastAPI)

**Ubicación**: `apps/audiomind/src/audiomind/` · Python 3.12 · FastAPI, librosa, pedalboard, numpy, demucs-onnx. **Dockerfile**: `python:3.12-slim`, `pip install -e .` con `src/` copiada antes, escucha en `${PORT:-8000}` (hay `tests/test_runtime_python_contract.py` que pinnea el contraste CI↔imagen).

**Pipeline del engine** (`processing/engine.py`, ~2.092 líneas):

1. **QC de entrada** (`strict_mode`) → rechaza HTTP 422 si clipping duro o true peak ≥ −0.3 dBTP.
2. **Gain staging** a −6 dBFS.
3. **De-esser dinámico** 3–8 kHz (neutral = bit-exacto).
4. **Match EQ por género** contra `TARGET_BANDS_HZ` [60,150,400,1000,2500,6000,10000,15000].
5. **Cadena de carácter** del preset (shelfs, peaking, exciter, imagen estéreo).
6. **Smart gate**: si la entrada ya cumple objetivos, omite corrección tonal (nunca gatea módulos de firma).
7. **M/S**: side HPF <100 Hz (off por defecto), reverb solo en side (mono-safe).
8. **Colapso mono** <120 Hz al centro.
9. **Soft clipper** 16× (knee erf) → **limiter true-peak 8×** con lookahead.
10. **Dither** TPDF + noise shaping Lipshitz 2º · resample libsoxr VHQ.
11. **Validación final**: LUFS, DR (LRA), correlación/cristal de fase.
12. **Análisis del contrato de métricas**: `band_energies_dbfs()` integra los band-power por Parseval y los reporta en **dBFS reales** (piso −120 dB). La escala del legacy `analyze_band_energies` (FFT-dB dependiente de N) **no se toca**; es la escala interna compartida con `compare_tracks`. `loudness_standard = "ITU-R BS.1770-4"` declara el medidor que el código implementa.

**El contrato de métricas reales (Fases A/B/C, PR #37 mergeado 27-oct)**:

- **A — Contrato retro-compatible**: `AnalysisResult` gana `bands_hz`, `band_energies_db`, `loudness_standard` (opcionales con defaults → payload legacy sigue validando). Endpoint `GET /api/session/{id}/metrics`.
- **B — Brik deja de adivinar**: el contexto de chat lleva un bloque `CONTRATO DE METRICAS` con las mediciones reales; `DIAGNOSIS_SYSTEM_PROMPT` exige `DIAGNOSTICO + RECETA` citando métrica/valor/punto de referencia con cláusula de honestidad numérica.
- **C — Reporte de cambios**: al completar un job de agente se mide before/after con los mismos metros y se publica `ChangeReport` (`ready|no_before|no_after|error`, **never-raise** → `dsp_jobs.result.change_report` + JSON en R2 `reports/` + espejo `SessionData.change_report`).

**Endpoints**: 63 operaciones + `GET /api/jobs/agent/{job_id}/events` (SSE). El Studio usa SSE y cae al GET de estado si el stream falla.

**Infraestructura de jobs y sesiones**:

- `services/job_store.py`: Supabase (`dsp_jobs`) con `probe()` → fallback memoria. Lease+heartbeat; job interrumpido se marca `error`, **no se reanuda**. Migración `20261005180000` añadió `meta`/`lease_expires_at`.
- **Masters durables en R2** (`master_r2_key`, `_persist_master_to_r2()` never-fail, `_resolve_master_file()` con precedencia local→R2).
- **Sesiones duraderas** (`session_backend.py`, default `auto`, write-behind con digest; archivo como fallback; un solo proceso uvicorn).
- **Estabilidad Demucs**: HTDemucs fp16 horneado (~158 MB), separación en proceso hijo (`demucs_worker.py`), tope de threads 4, timeout 1800 s.

**Limpieza y lint**: deuda de **483 errores de ruff (0 en clases F)** pagada a 0 (`9579a65`/`96a46bd`). `ruff check .` = "All checks passed!", gate bloqueante en CI. Quedan stubs dudosos (`measure_correlation → 0.0`) como deuda menor.

### 3.2 Motor 2 — Mix Engine (mezcla IA+DSP)

- **Pasos 01–08 TDD** + **Stem Balance T1–T7** (faders ±6 dB, auto-balance por género OFF por default, E2E de neutralidad) + **Character Stage** (`commercial_alt_pop`: slapback vocal, wow/flutter+chorus en `other`, saturación paralela en bass, hiss/crackle con compensación sample-level, HF-droop; solo render principal).
- **P4 Recipe Handshake**: `texture_recipe` v2 en `MixMetadata` con deltas medidos. Mastering lee la receta y adapta (match EQ ±2 dB, de-esser skip, LUFS compensation). **Invariante de neutralidad**: sin receta → master byte-idéntico a baseline (SHA-256 pinneado cross-commit).
- **P5 wiring**: `character`/`character_seed` en `POST /jobs/mix`, `MixJobOptions`, `MixPlan.character` desde `mix_intent` (proyectos).
- **Pipeline por stem**: split Demucs (4 stems) → pan → EQ → comp → dimensión → bus → comp de bus → QC informativo (nunca bloquean) → 5 versiones → modo creativo. Neutral = routing exacto; Demucs es lossy (aceptado).
- Pendientes congelados: A/B auditivo con el WAV hip_hop del productor; `build_mix()` re-separa desde el original (#P11).

### 3.3 Flujo de proyectos multitenant ("Moises") — backend completo, UI dormida

- **15 rutas** en `api/projects.py` (CRUD, assets presign/patch/list/download, `project_states`, documento V1 con OCC, jobs de proyecto mix/master/separate).
- **Auth/RLS**: `get_user_context` (Supabase JWT) → cliente scoped al token → RLS `auth.uid() = user_id`; en dev `DEV_USER_ID`.
- **4 tablas** (`projects`, `audio_assets`, `project_states`, `project_documents`) — **su carga en producción sigue sin verificar**.
- **R2-native**: presign PUT 900 s / GET 3600 s; subida del original en `/upload` → `r2:`.
- **UI dormida**: `features/projects/` sin consumidores externos. Follow-ups: `deleteTrack` no borra el objeto R2 (huérfanos), `getOriginalSignedUrl` ignora `expiresInSeconds`.
- Servicios: `compile_project.py`, `project_jobs.py`, `separate_jobs.py` (idempotente por `media_hash`). Spec: `docs/reference/specs/project_document_v1_spec.md`.

### 3.4 Capa de inteligencia: RAG local (sin cambios; backlog de prod aprobado)

- `intelligence/rag/` (13 módulos): OCR de PDF locales, chunking por capítulo, recuperación híbrida BM25+vector RRF, embeddings vía Ollama.
- `POST /api/agent/rag/search` (solo lectura; degrada a BM25 declarado en `mode_used`). En contenedor: 503 sin índice, degrada, no tumba el boot.
- El bucle agéntico **no lo consume todavía**. **Backlog aprobado (27-oct)**: mover el RAG de producción a la **Opción A (R2)**.

---

## 4. Studio — frontend y aplicaciones acompañantes

### 4.1 Studio (Next.js 16 + React 19 + TS + Tailwind 4)

**Rutas**: `/` (landing), `/mezclas`, `/upload`, `/lab`, `/login`, `/register`, `/admin`, `/voz`, `/voz/chat`, `/voz/speak`, `/voz/escuchar`, `/auth/callback`, `robots.txt`, `sitemap.xml`.

**Tabs de `/mezclas` (8)**: `Mezcla de Audio` · `Masterizar Audio` · `Splitter` · `Beats` · `Análisis` · `Estéreo` · `Álbum` · `Brik` (Productor IA).

**Tema claro/oscuro**: `data-theme` + clase `dark` + `colorScheme` en `<html>`, centralizado en `applyThemeToDocument()` (`ThemeToggle.tsx`). `FORCE_DARK_THEME = false`. El init-script de `layout.tsx` lee `waveai-theme` de `localStorage` sin borrarlo; no hay hardcodeos de `bg-[#0b0b0c]`/`text-[#f4f4f2]` fuera del tema. Light define overrides de `--color-primary/secondary/tertiary` y `--preset-ink-strength` 45 %.

**Novedad del ciclo**: `AgentPanel` y `client.ts` consumen `POST /api/agent/chat` (contrato HTTP de Brik pinneado por `96a46bd`). La consulta va por sesión y el widget renderiza diagnóstico, herramientas ejecutadas y métricas.

**UI de ChangeReport (Fase C)**: `AgentPanel` renderiza el bloque before/after junto con diagnóstico, herramientas, métricas y audio. La corrida de producción con credencial LLM real sigue pendiente.

- **Mix UI**: `MixPanel` + `MixWaveformAB` + `MixStatusStream`, labels críticos en `useTranslation()` y acción `Masterizar` post-mezcla.
- **Jobs del Productor**: SSE con polling GET de respaldo; mastering/mix mantienen sus pollers con backoff (`useProcessingProgress` y `useMasteringJob`).
- **Voz**: TTS ElevenLabs opcional (tope 400 chars, `204` → `speechSynthesis`), `useVoiceInput`, `lib/voice/decodeAgentText`.
- **i18n**: `useTranslation()` con `es.json`/`en.json` — **806 claves hoja en cada locale, paridad exacta**.
- **Estado**: React Context gobierna Auth/I18n/Mastering; Zustand acotado al chat de Brik por sesión y estado transitorio de stems.
- **Tests (6-nov)**: suite vitest 191 pasan / 3 fallan por el mock preexistente de `logTrackEvent.test.ts` (`insert` vs `.upsert()`); build exit 0; eslint 0 errores / 41 warnings. En CI, lint y build son gates bloqueantes.

**Arquitectura**: `app/` rutas · `adapters/` (api/audio) · `features/` (mastering, projects, tracks, upload, auth, admin, remastering-history) · `application/hooks/` · `presentation/components/` · `shared/` · `lib/` · `i18n/`. Motion con framer-motion/GSAP; audio cliente con `tone` y `wavesurfer.js`.

### 4.1.1 Mobile y responsive (web — sin app nativa)

**0 nativo/PWA** (no hay manifest ni service worker). `/mezclas` y `/voz` usan shell de `100dvh` con overflow local. La selección mobile usa `useIsMobile` (breakpoint 768; SSR y primer paint renderizan escritorio → flash conocido, sin script pre-hidratación). Piezas mobile: `MobileMasteringView`, `MobileDrawer`, `MobilePresetStrip`; menú mobile propio de la landing. `.pt-safe/.pb-safe` y `prefers-reduced-motion`.

### 4.2 Landing page — en producción (Vercel)

19 componentes `.tsx` en `presentation/components/landing/` (`LandingScreen`, `LandingHeader`, `LandingHero`, `LandingBrikIA`, `LandingPresets`, `LandingABPlayer`, `LandingNavigation`, `LandingPricing`, `LandingFAQ`, `LandingFooter`, `LandingFounders`, `LandingHeroModal`, `DynamicsDiagram`, `Reveal`, etc.). `page.tsx` con JSON-LD `FAQPage` desde `es.json` y `alternates.canonical`. `LandingABPlayer` con tono sintético (saw 110 Hz + sub 55 Hz → lowpass Q 0.7, anti-zipper con `setTargetAtTime`) y waveform Canvas de 96 barras. Fonts self-hosted (Syne, Plus Jakarta Sans, JetBrains Mono, Instrument Serif). GSAP con `useHeroGSAP`/`useTaglineReveal` y gates por viewport. **3 decisiones de producto abiertas**: `--font-sans` sin mapear en el hero, controles 27–36 px, precios placeholder (#P3).

### 4.3 apps/agent (`@midimastering/agent`)

Traduce lenguaje natural → `IntentProfile` (Gemini + Zod), no toca audio. `vocal_focus` re-alineado con el schema. Sigue pendiente la llamada real con credenciales.

---

## 5. Componentes removidos / documentación desactualizada

| Componente | Estado real |
|---|---|
| **Live Engine** | ❌ Removido (`ba3b4a6`, 27-Sep). Sobrevive solo `packages/contracts/live_params.schema.json` como **contrato dormido** + `liveParams.gen.ts`; `safeCloseAudioContext` en `lib/audioContext.ts`. **No regenerar ni consumir el contrato** sin reactivación explícita |
| **`apps/bridge`** (MIDI→WS) | ❌ No existe |
| **`simulator`** | ❌ No existe |
| **HumanMidi / gestos** | ❌ Removido |
| **Convex** | ❌ Repo + CI limpios (`3d9f8ae`); el login de Studio vive en Supabase (`middleware.ts` → `updateSession`), no en Convex |
| **Vocal chain / paneles educativos** | ❌ Removidos (28-Sep); los tabs ya no existen |

> **Deuda de documentación vigente**:
> 1. `docs/README.md` (índice central) **no menciona** la landing, ni el flujo de proyectos, ni R2, ni el orquestador Cloudflare (#P20).
> 2. `docs/reference/specs/` — `01`, `06` y `07` siguen describiendo el Live Engine y HumanMidi; contradicen "dos motores + flujo de proyectos + orquestador" (#P20).
> 3. `AGENTS.md` (raíz) dice "sesiones del backend en memoria (dict + SessionCache)" — **ya no es verdad** (sesiones durables en Postgres, §3.1), y no menciona el job de backend en CI ni `apps/orchestrator` (#P20).
> 4. `docs/runbooks/DEPLOY_RUNBOOK.md`, `apps/orchestrator/README.md`, los `railway.json` y varios comentarios de `apps/audiomind/Dockerfile`/scripts aún describen Railway o el spike como estado operativo; hoy son referencias legacy (#P20).

---

## 6. Entorno, CI/CD y verificación

### 6.1 CI (`.github/workflows/studio-ci.yml`) — dos jobs bloqueantes

| Job | Qué hace |
|---|---|
| `build` (Studio) | Checkout → Node 22 → bun install `--frozen-lockfile` → `bun run lint` (bloqueante) → `bun run build` |
| `backend` | Checkout → **Python 3.12** (pinnea `test_runtime_python_contract.py`) → deps de sistema **apt con `--no-install-recommends` + retries + timeout 15 min + cache de `.debs`** → `pip install -e ".[dev]"` → **`ruff check .` bloqueante** → `python scripts/generate_samples.py` → `pytest tests/ -q` con env de demo |

Triggers: PRs y push a `develop`/`main` con cambios en `apps/studio/**`, `apps/audiomind/**`, `pyproject.toml`, `requirements*.txt`, raíz de paquetes; además `workflow_dispatch`. **Sin gate de e2e ni job de deploy de Cloudflare**; `apps/orchestrator/**` no dispara un publish automático del contenedor.

### 6.2 Deploy actual (Railway ya no es el runtime activo)

- **Frontend (Studio + landing)**: Vercel. SHA `20cf2d1` publicado en Production (success, 6-nov 16:17 UTC). El cliente usa `NEXT_PUBLIC_API_URL` apuntando al Worker de Cloudflare.
- **Backend (AudioMind)**: Cloudflare Worker `waveai-orchestrator` → Cloudflare Container `waveai-orchestrator-dspcontainer`, clase `DSPContainer`, key única `dsp-smoke`, puerto 8000. Último despliegue confirmado: Worker `6de4cd8c-85ce-44e3-9c1f-b21fe4d90d35`, container app versión 3, imagen `sha256:84cd6f7858e3f42f143dfb810aede5cfe4a8d87f07c0564d8396c1e401dd6231`.
- **Brecha entre código y runtime**: `waveia/main` está en `20cf2d1`; el último container confirmado se desplegó antes de `b462cf6`. Por tanto, el SSE nuevo `/api/jobs/agent/{id}/events` y la publicación temprana de stems requieren un nuevo `npx wrangler deploy` desde `apps/orchestrator`. El usuario hará ese deploy manualmente.
- **CORS**: el código permite `https://www.brikmusic.online` y `https://brikmusic.online`. `AUDIOMIND_CORS_ORIGINS` no está definida en Cloudflare.
- **Audio**: Cloudflare R2 (originales por presigned PUT, mezclas, masters y `reports/`). **Auth/metadata/jobs/sesiones/proyectos**: Supabase Postgres.
- **Railway**: ya no se usa como destino operativo. Los manifiestos, ejemplos, runbooks y comentarios aún presentes se consideran legacy.
- **Migraciones**: `supabase/migrations/` versionadas, sin Alembic (aplicación manual; deuda #P7).

### 6.3 e2e (Playwright)

1 spec: `e2e/tests/demo_flow.spec.ts` (chromium, webServer dev). No ejecutado en este ciclo.

### 6.4 Orquestador Cloudflare Containers — Fase 1 desplegada

| Archivo | Rol |
|---|---|
| `apps/orchestrator/src/index.ts` | Worker `waveai-orchestrator`: `/__diag` (worker-only) + todo lo demás **passthrough** al container `dsp.internal` |
| `apps/orchestrator/src/container.ts` | `DSPContainer` keyed `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB) |
| `apps/orchestrator/wrangler.jsonc` | Build del Dockerfile de audiomind al managed registry de CF, migration `new_sqlite_classes` |

**Roadmap**: ① Worker + container — desplegado; ② subida/descarga directa browser↔R2 — parcialmente pendiente; ③ Cloudflare Queues y una instancia por job — pendiente; ④ Studio en Workers vía OpenNext — pendiente.

---

## 7. Pendientes y decisiones del usuario

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| **P1** | **Sincronizar `develop` antes de usarlo**: `develop` está 25 commits detrás de `main`. Cambios puntuales parten de `main`; para trabajo amplio, alinear `develop` desde `main`, trabajar allí y luego integrar a `main`. | Git | Política definida por el usuario; sincronización aún no hecha |
| **P2** | **Publicar el último código en Cloudflare**: el container v3 activo es anterior a `b462cf6`; falta el `npx wrangler deploy` manual desde `apps/orchestrator`, esperar rollout y verificar SSE + CORS. | Deploy | **Acción del usuario — pendiente** |
| **P3** | **Landing — 3 decisiones de producto**: `--font-sans` sin mapear, controles 27–36 px, precios placeholder (#P3) · deuda de jerarquía h4/h5 en `LandingDSPChain` | Landing | Decisión del usuario |
| **P4** | `ChangeReport` en `AgentPanel` | Studio | ✅ Implementado; falta una corrida real del Productor IA con credencial LLM (#P15) |
| **P5** | **Flujo de proyectos en producción**: cargar 4 tablas + env, correr `verify_prod_wiring.py`, probar `/projects/*` end-to-end · **UI dormida** de proyectos sin consumidores | Deploy/Frontend | Trabajo pendiente |
| **P6** | Revisar el copy no crítico que aún pueda quedar hardcodeado fuera del alcance i18n; decidir si exponer `character_seed` en MixPanel | Frontend | Deuda técnica / decisión |
| **P7** | **Sin Alembic** (o#25): migraciones a mano · progreso por etapa del job (o#21) · dedup de submits (o#20) · cola real (o#19, fuera de alcance v1) | Backend | Deuda técnica |
| **P8** | **Credenciales R2 a rotar** — quedaron expuestas; el token viejo es el que carga producción hoy | Deploy | **Acción del usuario** |
| **P9** | **Verificaciones de prod pendientes**: backend de sesiones `auto`, aplicación de `20261005180000`/`20261005220000`, `masters/` 4 objetos basura + aserción de cache-hit | Deploy/Backend | Acción del usuario |
| **P10** | R2 real: falta ejercitar la **descarga** · follow-ups de subida híbrida: `deleteTrack` no borra el objeto, `expiresInSeconds` ignorado | Deploy/Studio | Prueba manual + decisión |
| **P11** | `build_mix()` re-separa desde el original en cada corrida · remixes sobrescriben el mismo `r2_key` · huérfanos de R2 | Backend | Deuda técnica |
| **P12** | **RAG de producción Opción A (R2)** (backlog aprobado 27-oct) · el bucle agéntico no consume el RAG | Backend/Deploy | Trabajo pendiente |
| **P13** | **Reaper de sesiones TTL 60 min** en producción (backlog aprobado 27-oct); hoy existe el janitor de demo y `session_ttl_minutes` default `0` | Backend/Deploy | Trabajo pendiente |
| **P14** | A/B auditivo del Mix con la sesión hip_hop del productor (requiere el WAV que no está en el repo) · E2E manual de "Mezcla de Audio" con toggle Carácter | Mix Engine | Prueba del usuario |
| **P15** | `interpretIntent` real (credenciales Gemini) + corrida real del Productor IA (credencial LLM) para ver el DIAGNÓSTICO/RECETA y el ChangeReport en producción | IAM/Backend | Decisión del usuario |
| **P16** | Históricos de ingeniería: push de `feat/mix-engine/01…08` · retención de `outputs/` fuera del volume · segundo libro + autotune creativo (fuera de v1) | Mix Engine | Decisión del usuario |
| **P17** | **`DJ_LIMIT_WORKERS`**: `reset_gate()` sigue ignorándolo · stubs `measure_correlation→0.0` · golden fingerprint 1e-3 dB | Backend | Trabajo pendiente |
| **P18** | **UI three-bugs**: T1 (modal) y T2b ("Not Found") bloqueados por falta de evidencia del navegador · `manual INSERT` de jobs sigue siendo parche operativo | Frontend | Evidencia del usuario |
| **P19** | Receipt-driven development | Proceso | Clone-local OFF verificado; no se usó para la entrega `20cf2d1` |
| **P20** | **Higiene de docs/config legacy**: actualizar `docs/README.md`, `AGENTS.md`, `docs/runbooks/DEPLOY_RUNBOOK.md`, `apps/orchestrator/README.md`, env examples, CORS default del hostname Railway y comentarios/manifiestos que aún presentan Railway como activo. No borrar configs sin autorización. | Docs/Deploy | Trabajo pendiente |
| **P21** | Higiene git: cerrar/borrar la copia redundante en `waveia` de `feat/agent-metrics-contract` y el auto-close no ocurrió — **el issue #36 sigue OPEN** pese a "Closes #36" en el PR/#37 mergeado | Git/GitHub | Acción del usuario |
| **P22** | Espejo `origin` stale (`main` @ `1c0379b`, sin `develop`); el remote canónico es `waveia`. | Git | No sincronizar ni publicar a `origin` sin instrucción |
| **P23** | Confirmar Vercel `NEXT_PUBLIC_SITE_URL=https://www.brikmusic.online` y Supabase Auth URL Configuration (Site URL + Redirect URLs); código ya usa `getURL()`/callback dinámico, pero dashboard no se verificó. | Auth/Deploy | Verificación del usuario |
| **P24** | Confirmación visual de que los perfiles inferiores de Mezcla/Máster quedan libres del dock con un track cargado; geometría del canvas se midió (256 px de padding vs. dock 68.7 px), pero no se renderizó un perfil real en el navegador aislado. | Studio | Prueba manual pendiente; informar captura si aún se solapa |

---

## 8. Documentación: dónde está todo

**Canónica** (`docs/reference/`, `docs/runbooks/`, `docs/manual/`, `docs/evidence/`): índice central `docs/README.md` (**stale — ver #P20**) · specs de implementación (`08_implementacion_llm.md` prompt exacto de implementación) · `COMPLIANCE_PHASE1.md` · `DSP_INDUSTRY_REVIEW.md` · `DESIGN` · SETUP/DOCKER/DEPLOY · `project_document_v1_spec.md`.

**Histórica** (`docs/archive/`): integración, workplan, plan original. `05_live_engine_gestos_a_master.md` es **histórico** del engine removido; `INTEGRATION_REPORT.md` archivado.

**Local-only (excluida de git)**:

- `docs/proposals/` — 4 PDF de libros de mezcla (materia prima del RAG) + propuestas.
- `docs/postmortems/` — `inc-2026-04-22-checkout-5xx.md`.
- `odd/` — documentos de tareas excluidos de Git.
- `.atl/` — skill registry local.

**Memoria Engram** (`brikmaster2027`): topología de ramas y entrega del PR #37 registradas.

---

## 9. 🧭 Cómo funciona el sistema (de extremo a extremo)

> Esta sección es la guía arquitectónica del producto: qué pasa cuando algo entra, qué lo procesa y qué queda persistido. Los estados de cada pieza están en §1–§6; acá está el **funcionamiento**.

### 9.1 Topología general

```text
┌─ Browser (Studio / landing) ────────────────────────────────────────────────┐
│ Next.js 16 + React 19 (Vercel)                                             │
│  Contexts (I18n/Auth/Mastering) · SSE/poll fallback · Web Audio (leer)      │
└──────┬──────────────────┬───────────────────────────┬──────────────────────┘
       │ HTTP REST        │ Supabase JS (auth)        │ (futuro: R2 presign directo)
       ▼                  ▼                           ▼
┌─ Cloudflare Worker: waveai-orchestrator ────────────────────────────────────┐
│ /__diag en Worker · /api/* passthrough al DSPContainer                       │
└───────────────────────────────────────┬───────────────────────────────────┘
                                        ▼
┌─ DSPContainer: AudioMind FastAPI (Python 3.12, uvicorn 1 worker, port 8000) ┐
│ mastering · Mix Engine · agentic_loop · RAG · boto3→R2 · Supabase→Postgres │
└───────────────┬───────────────────┬──────────────────────────┬────────────┘
                ▼                   ▼                          ▼
           Cloudflare R2      Supabase Postgres           LLM externo
          (originales, mix,    (sessions, dsp_jobs,       (transporte model-
          masters, reports)    projects y metadata)       agnostic)
```

El browser llama al Worker vía `NEXT_PUBLIC_API_URL`. El Worker enruta el API al container `dsp-smoke`; el browser todavía no sube audio directamente a R2 y el orquestador no usa Queues ni una instancia por job.

### 9.2 Vida de una sesión de mastering (el flujo canónico)

1. **Subida** — `POST /api/upload` (multipart): valida tamaño/max, guarda el WAV en disco local y devuelve `SessionData` (el contrato central, pydantic, config `extra="ignore"` + persistencia auto de espejos como `change_report`). La sesión vive en un **dict en proceso** (fuente de lectura) con *write-behind*: digest por sesión hacia Postgres (backend `auto`: Supabase → archivo como fallback). Invariante documentada: **un solo proceso uvicorn** — el backend no soporta múltiples workers contra el mismo store.
2. **Análisis** — `analyze_audio` (librosa) produce `AnalysisResult`: LUFS integrado, crest, género, y con el contrato de métricas (Fase A) las **bandas en dBFS reales** (`band_energies_dbfs` por Parseval, piso −120) + `bands_hz` + `loudness_standard="ITU-R BS.1770-4"`. Todo eso queda en la sesión y es visible por `GET /api/session/{id}/metrics`.
3. **Elección de preset** — presets del catálogo (o prerender por preset, que pre-computa el master de una variante), con `platform_target` (spotify/apple_music/youtube/tidal/custom: floors UI + recorte de true peak del limiter).
4. **Proceso** — `POST /api/session/{id}/process` ejecuta el **engine** (§3.1, 12 pasos: QC 422 → gain staging → de-esser → match EQ → carácter → smart gate → M/S → mono <120 Hz → soft clip + limiter TP 8× → dither/resample → validación LUFS/DR/fase). Neutral (todo a defaults) = **bypass bit-exacto**. El master resultante se **persiste a R2** fuera del event loop (nunca falla la request) y la sesión guarda `master_r2_key`.
5. **Descarga** — `GET /api/session/{id}/download/{format}` resuelve el archivo con precedencia **local → R2** (`_resolve_master_file`, 4 consumidores centralizados); objeto ausente → 404 nombrando la clave, jamás un fallback silencioso al original.
6. **Detalle de UI** — el Studio consulta progreso de sesión con backoff. Los jobs del Productor IA tienen SSE `GET /api/jobs/agent/{id}/events` con fallback al GET de estado; el runtime Cloudflare debe recibir el código `b462cf6` en adelante para que ese endpoint exista en producción.

**Cadena de referencia externa** (opcional): subir *reference track* y `compare-reference` compara tu master contra ella en la escala FFT-dB interna (`compare_tracks`); es otra cosa que el `ChangeReport` del agente, que mide before/after en dBFS de contrato.

### 9.3 Los dos modelos de trabajo: sync y async

| Modelo | Rutas | Cómo corre |
|---|---|---|
| **Sync (en request)** | `POST /api/session/{id}/process`, `POST /api/session/{id}/mix` | DSP en el ciclo de la request; el pool `DSP_THREAD_POOL` y `max_concurrent_dsp` protegen el container AudioMind |
| **Async (jobs)** | `POST /api/jobs/mix/{id}`, `POST /api/jobs/agent/{session_id}`, jobs de proyecto (`/projects/{id}/jobs/mix|master`) | Registro en `dsp_jobs` (Supabase si está configurado y la tabla pasa probe; si no, memoria), `BackgroundTasks` en proceso, **lease + heartbeat**. Estados reales: `processing → completed | error`; job interrumpido se marca error y **no se reanuda**. El Productor IA puede seguirse por SSE; el resto conserva su mecanismo de estado/polling. |

### 9.4 Brik: cómo piensa el agente (Fases A/B/C en acción)

`processing/agentic_loop.py` corre un bucle de **4 fases** con transporte **model-agnostic** (sólo pide *messages + tools* al proveedor):

| Fase | Qué hace | Herramientas típicas |
|---|---|---|
| 1 — Diagnóstico | Recorre el audio | `analyze_original_audio` |
| 2 — Separación | Demucs para despegar stems | `trigger_stem_separation` |
| 3 — Mezcla/ajuste | Renderiza el mix, ajusta parámetros por stem | `render_mix`, `analyze_mix_bus`, `adjust_stem_parameters`, `search_knowledge` |
| 4 — Entrega | Manda el resultado a masterización | `send_to_master` |

- **Contexto honesto (Fase B)**: el snapshot de sesión se serializa con un bloque `CONTRATO DE METRICAS` (mediciones reales en dBFS/LUFS del medidor declarado), y el system prompt de diagnóstico exige **DIAGNÓSTICO + RECETA** citando métrica/valor/referencia con cláusula de honestidad numérica.
- Si el trabajo es pesado, `should_escalate_to_job` manda la operación a un **job async**. `GET /api/jobs/agent/{id}/events` transmite snapshots durables; al terminar Demucs publica los cuatro `stem_names` y la UI los muestra mientras continúan mezcla/master. SSE solo transporta estado/nombres, no audio; si el stream termina antes de un estado terminal, `AgentPanel` vuelve al GET de estado.
- **Al completar (Fase C)**: hook de job completado → `ChangeReport` **before/after con los mismos metros en ambos lados** (nunca raise: `ready|no_before|no_after|error`) → `dsp_jobs.result.change_report` + JSON en R2 `reports/` + espejo en la sesión. `AgentPanel` lo renderiza; la corrida real con LLM permanece pendiente (#P15).

### 9.5 RAG (libro de mezcla como memoria) — cómo trabaja

Ingesta (CLI): OCR de los PDF de `docs/proposals/` → limpieza → chunking por capítulo → embeddings (Ollama local) → índice. Consulta: `POST /api/agent/rag/search` recibe la query, recupera **BM25 + vector fusionados por RRF** (o degrada a BM25 si no hay índice, declarando `mode_used`), y responde passages + fuentes. En contenedor sin índice: **503 honesto**, no tumba el boot (import perezoso + rutas acotadas). El bucle tiene la herramienta `search_knowledge` cableada pero todavía no se le pasa `RAGQuery` desde la API (#P12: producción "Opción A" sobre R2).

### 9.6 Mix Engine — cómo se mezcla

`build_mix()` comando por corrida: separa **Demucs (4 stems)** del original → por stem: pan por rol → EQ mágico → compresor → dimensión (sends) → suma al bus → compresor de bus → **QC informativo** (mono/fase, sibilancia 4–7 kHz, muddy/honky: reportan, nunca bloquean) → **render de 5 versiones** (principal 0 dB, vocal ±0.75, instrumental, TV mix) → **modo creativo** (espacio continuo 0..1, semilla reproducible, rejection sampling contra QC). El progreso real se reporta por **callback de etapas** (`pct`, `stage` — un callback jamás rompe el DSP; la UI no lo consume a stage todavía, #P7). Con `character` conocido (P4), el handshake `texture_recipe` v2 lleva **deltas medidos** que el mastering atasca al adaptar su propia cadena (la invariante: sin receta → byte-idéntico).

### 9.7 Frontend: cómo está construido y cómo razona

**Capas** (regla del repo: componentes limpios, sin barrels de compatibilidad):

| Capa | Cómo funciona |
|---|---|
| `app/` (App Router) | Rutas/servicios de Next: `page.tsx` = landing (JSON-LD, canonical, `viewport` con safe-areas), `mezclas/` el estudio, `/voz/*` chat/TTS, `/auth/callback` |
| `adapters/` | La única capa que habla HTTP y Web Audio pesado: `api/client.ts` (todos los endpoints + `submitAgentChat`, `presignAsset`…), `audio/AudioProcessor.ts` y `engine.ts` |
| `features/` | 7 módulos con su estado (mastering, projects, tracks, upload, auth, admin, remastering-history). En mastering vive `AgentPanel` (UI del Productor IA) |
| `application/hooks/` | Lógica de app: `useAudioProcessor` (preview/estado local), `useStereoField` (análisis Web Audio de **sólo lectura**), backoff de polls |
| `presentation/components/` | Componentes de UI: dock/tiles de etapas, player, waveforms, mix, chat, landing (19 archivos), mobile |
| `shared/` + `lib/` | `useIsMobile` (768 px), motion (framer-motion + GSAP), `audioContext.ts`, Supabase client, i18n (`useTranslation()`; es/en 806/806 claves) |

**Reglas y estado**: (a) Web Audio usa `setTargetAtTime(value, ctx.currentTime, 0.02)` para cambios de parámetros; (b) `useTranslation()` con locale ES/EN; (c) SSR y primer paint conservan el flash de breakpoint ya conocido; (d) Context sigue gobernando Auth/I18n/Mastering, pero Zustand ahora persiste el chat de Brik por sesión y mantiene el estado transitorio de stems; no es el store global de toda la aplicación. `/mezclas` y `/voz` limitan su shell a `100dvh`; la landing conserva scroll normal.

**El flujo del Studio en el ciclo de una masterización**: `/upload` (DropZone) → `useMasteringWorkflow` decide storage (flujo proyecto: presign R2; sesión simple: `POST /api/upload`) → workspace responsive (`ModuleDock` + `PaintedModule`) → presets por género → **Masterizar Audio** (progreso con backoff) → reporte y descargas. Si el usuario escribe en Productor IA, `AgentPanel` encola el job y sigue SSE con GET de respaldo; después de Demucs muestra los cuatro stems antes de que finalicen mix/master. El historial de mensajes de Brik persiste por sesión en localStorage; el estado de stems del job no se persiste. `MixPanel` incluye labels y tooltips críticos en ES/EN y conserva `Masterizar` para navegar al máster.

### 9.8 Auth y multi-usuario

- **Studio**: Supabase Auth (`middleware.ts` → `updateSession`, `features/auth/`, `/auth/callback` intercambia código y filtra `next` a rutas relativas). `getURL()` toma `NEXT_PUBLIC_SITE_URL` primero y soporta dominio de producción; la configuración efectiva de Vercel y el allowlist de URL en Supabase no se verificaron en este corte (#P23). El layout monta `AuthProvider`.
- **Backend**: `get_user_context` valida `Authorization: Bearer` (JWT de Supabase) y usa un cliente **scoped al token** → **RLS** (`auth.uid() = user_id`) aplica en Postgres para `sessions`, `projects`, `audio_assets`, `project_documents`. En dev/tests existe `DEV_USER_ID` como identidad de fallback. Los endpoints de sesión anónima (`/api/session/*`) siguen existiendo para el flujo demo.
- **Espera**: audiomind jobs y artifacts no se "firman" por usuario — la protección real de propiedad la dan RLS en las tablas (`sessions` es del usuario que creó) y las claves R2. Es una decisión documentada, parece una brecha en la primera vista: lo cubre `project_document_v1_spec.md`.

### 9.9 Almacenamiento: qué queda dónde

| Data | Dónde | Cómo |
|---|---|---|
| WAV originales, mix, masters | **R2** (`uploads/`, `outputs/`, claves `{sid}_{preset}_mastered…`) | Desde el backend con boto3 (S3-API de R2); la sesión siempre guarda **claves, nunca URLs prefirmadas** (PUT 900 s / GET 3600 s caducan) |
| JSON de `ChangeReport` | R2 `reports/` | Fase C; el job en Postgres guarda igual el espejo — si R2 falla, degrada a no-fail |
| Estado de sesión | Supabase `sessions` (write-behind con digest; archivo como fallback) | Un solo proceso; restore al arranque |
| Jobs | Supabase `dsp_jobs` (+`meta`/`lease_expires_at`; `result` jsonb guarda `change_report`) | Lease+heartbeat |
| Documento de proyecto V1 (OCC) + assets + project_states | `project_documents` / `audio_assets` / `project_states` / `projects` | RLS por usuario |
| Índice RAG / Ollama / libros PDF | **local-only (`docs/proposals/` excluido de git)** | Backlog: mover a R2 |

### 9.10 Deploy y ciclo de release actual

- **Flujo de cambios acordado por el usuario**: cambios puntuales parten de `main`; si el alcance requiere integración, primero sincronizar `develop` desde `main`, trabajar allí y luego integrar a `main`. Hoy `develop` está 25 commits detrás, así que no usarlo hasta sincronizarlo. No dejar trabajo funcional solo en ramas locales; `waveia` es el remoto canónico y `origin` está stale.
- **Release / CI**: GitHub Actions verifica build Studio + backend pytest/ruff; no hay gate e2e ni deploy automático del container. Push a main no sustituye `npx wrangler deploy`.
- **Nube actual**: Vercel (frontend) · Cloudflare Worker + Containers (AudioMind API) · Cloudflare R2 + Supabase (datos). Railway no se usa. El container activo v3 antecede a `b462cf6`; el usuario hará el deploy de esa versión manualmente.
- **Contratos estables**: `packages/contracts/live_params.schema.json` **dormido** (sólo reactivar si el engine Live vuelve) · `intent_profile.schema.json` · `project_document_v1_spec.md` · el **contrato de métricas** (dBFS/Parseval del medidor BS.1770-4).

---

*Relevamiento actualizado el 2026-11-06 desde `main` (`20cf2d1`). Método: estado Git local (sin fetch), revisión de código/configuración Cloudflare y del historial de suites; suites ejecutadas localmente (AudioMind 1634 passed, Studio 191 passed / 3 pre-existing, build OK, lint 0 errores / 41 warnings). No se leyeron secretos ni se consultó el dashboard de Vercel/Supabase. Pendientes explícitos: publicar `b462cf6` en adelante en Cloudflare, validar perfiles con un track real y confirmar configuración productiva de Auth/sesiones/migraciones.*
