# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha del relevamiento**: 2026-10-29 · **Actualización previa**: 2026-10-19 (reconciliación `develop` → `main`, fix del boot del API en contenedor, suites re-medidas 1,410/134).
> **Novedades de este ciclo (20→27-oct)**: gate de backend en CI (pytest + ruff **bloqueante**, deuda de 483 errores de ruff pagada a **0**), despliegue del backend de Railway desde su **Dockerfile** con healthcheck `/health`, correcciones de backend (import del módulo demucs del wheel, acento silencioso del beat, suite en verde + contrato HTTP del chat de Brik), y el **contrato de métricas reales para el agente adaptativo** (Fases A/B/C) mergeado a `develop` por el PR #37. **Nueva área**: orquestador en **Cloudflare Containers** (spike local, Fase 1 pendiente de deploy).
> **Alcance**: repositorio completo — los dos motores DSP vivos (Mastering, Mix), el flujo de proyectos multitenant, landing, Studio, agentes de IA, capa de inteligencia, contratos, orquestador Cloudflare, entorno, CI/CD, ramas y pendientes — más la **guía de cómo funciona el sistema de extremo a extremo (§9)**: topología, vida de una sesión, jobs, agente, mix, frontend, auth, almacenamiento y release. El Live Engine, Convex, `apps/bridge` y `simulator/` ya no existen; ver §5.
> **Fuentes**: código (`apps/`, `packages/`, `supabase/`, `e2e/`), documentos ODD (`odd/tasks/`, excluidos de git), estado git real verificado hoy, workflow de CI leído en el árbol y suites de verificación ejecutadas (fechas citadas en cada cifra).

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | ✅ Operativo · cadena proporcional + cohesión textura (P4) + Character Stage (P5, `main`) + **contrato de métricas reales**: `band_energies_dbfs` (Parseval, dBFS, piso −120), `GET /api/session/{id}/metrics`, `ChangeReport` before/after al terminar un job de agente (`dsp_jobs.result.change_report` + JSON en R2 bajo `reports/` + espejo en la sesión) · suite **1,591 passed, 0 failed** (re-medida hoy 29-oct: 204 s, 1 warning preexistente de Starlette; idéntico al 27-oct sobre el head limpio `a31a09c` — el árbol de `apps/audiomind` en `develop` es el mismo) · **ruff 0 errores, gate en CI** |
| **Motor de Mezcla (Mix Engine)** | ✅ Pasos 01–08 (TDD estricto) + Stem Balance T1–T7 + Character Stage P3/P4 (`texture_recipe` v2 con deltas medidos) + P5 wiring async/proyecto · defecto del camino async corregido y commiteado (`a3fd00c`) · queda el A/B auditivo con la sesión hip_hop del productor (su WAV no está en el repo) |
| **Flujo de proyectos multitenant ("Moises")** | 🟡 Backend completo (WU1–WU5) + subida directa de originales a R2 verificada · **UI dormida**: `ProjectContext`/`useProject` y los stores siguen sin consumidores · falta cargar las 4 tablas y env en producción |
| **Orquestador Cloudflare Containers** | 🆕🟡 **Spike completo y local** (`feat/cf-orchestrator-spike` @ `dc22418`, rebased sobre `develop`): Worker `waveai-orchestrator` + `DSPContainer` keyed `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB) sobre `apps/audiomind/Dockerfile` · **deploy bloqueado**: falta Workers **Paid** (compra en curso) y Docker Desktop (instalación en curso) · plan de fases 1–4 en §6.7 |
| **Motor en vivo (Live Engine)** | ❌ **Removido del producto** (`ba3b4a6`, 27-Sep). Queda el schema como contrato dormido |
| **Landing page** | ✅ Nueva, en producción (Vercel) — GSAP, i18n completo, A/B demo local, SEO/JSON-LD · 3 decisiones de producto abiertas (#P3) |
| **Frontend y Mobile (web)** | ✅ Studio + landing con variantes mobile propias · sin app nativa, sin PWA · estado por React Context + `useState` · chats de Brik (`POST /api/agent/chat`) consumidos por `AgentPanel`/`ChatPanel` · **la UI aún no renderiza el `change_report`** (Fase C lo entrega en backend; consumidor frontend pendiente) |
| **Agent de interpretación (IA)** | 🟡 Compila · `vocal_focus` en el contrato · **llamada real sin probar** (faltan credenciales Gemini) |
| **Productor IA (bucle agéntico, Python)** | 🟡 Bucle de 4 fases + tool calling + transporte model-agnostic · `POST /api/jobs/agent/{session_id}` + polling · **ahora diagnostica con métricas reales citadas y publica el ChangeReport del job** (Fases B/C) · corrida real sin probar (falta credencial LLM válida) |
| **Capa de inteligencia (RAG)** | 🟡 CLI local sobre los libros de mezcla (OCR, BM25+vector RRF, Ollama) · expuesto por `POST /api/agent/rag/search` (en el contenedor responde 503 sin índice) · el bucle agéntico **todavía no lo consume** · **aprobado como backlog**: RAG de producción "Opción A" (R2) |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | ❌ **Eliminado** (repo + CI) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** |
| **Deploy (Vercel + Railway + R2 + Supabase)** | ✅ Backend de Railway ahora se construye desde `apps/audiomind/Dockerfile` (Python 3.12-slim) con healthcheck `/health` y `uvicorn` en `$PORT` (`a7264d1`, 24-oct) · migración a Cloudflare en Fase 1 (§6.7) |
| **Sesiones del backend** | ✅ Durables en Postgres (`sessions`, backend `auto`) con fallback a archivo · **aplicación en prod sin verificar** |
| **Suites de verificación** | Backend **1,591 passed / 0 failed** (re-medida 29-oct, 204 s; 84 archivos `test_*.py`) · vitest **11 archivos / 134 tests** (19-oct) · eslint **0 errores / 37 warnings** (19-oct) · build Next **exit 0** (19-oct; 27-oct en CI, con warnings pre-existentes de Studio) · **ruff 0** (verificado 29-oct con ruff 0.16.10; gate bloqueante en CI desde 22-oct) · e2e no ejecutado (1 spec `demo_flow`) |

---

## 2. Estado del repositorio (git, verificado 2026-10-29)

### 2.1 Ramas y remotes

Los remotes cambiaron respecto de la versión anterior de este documento: ya **no existen** `brik`, `masive`, `team`. Quedan dos:

| Remote | URL | Rol |
|---|---|---|
| `waveia` | `https://github.com/Masive-porjects/Brik.git` | **Producción/staging**: `main` y `develop` viven aquí |
| `origin` | `https://github.com/brikpaul569-cmd/BrikMaster2027.git` | Espejo de trabajo local (**stale**: `main` @ `1c0379b`, sin `develop`)|

| Rama | Tip | Estado |
|---|---|---|
| `develop` | `e12f65e` | **== `waveia/develop`** · trackea `waveia/develop` · = main + PR #37 mergeado |
| `main` | `0372037` | **== `waveia/main`** · el 29-oct se le aplicó un fast-forward (`61c9d5d` → `0372037`): estaba 8 commits atrás de producción por trabajo previo; quedó alineada (ff puro, sin riesgo) |
| `feat/cf-orchestrator-spike` | `dc22418` | **Local-only** (decisión del usuario): orquestador Cloudflare, rebased sobre `develop` (`e12f65e`) — la imagen del container llevará el contrato de métricas adentro · **única rama local sin mergear** |
| `feat/agent-metrics-contract` | `a31a09c` | Ya **mergeada** al PR #37; su copia en `waveia` es redundante (higiene opcional: borrarla) |

**Todas las demás ramas locales están mergeadas a `develop`** (verificado con `git branch --merged`): `feature/moises-architecture-migration`, `fix/deploy-backend-config-and-lint`, `fix/ci-samples-rhythm-chat-contract`, `feat/texture-modulation-dsp`, `feat/brik-chat-router`, `feat/brik-decision-layer`, `feat/brik-ghost-toggle`, `feat/brik-sidebar-branding`, `feat/agent-sidebar`, `feat/agent-character-tool`, `feat/ia-asistente-mezcla`, `feat/landing-gsap-microinteractions`, `feat/mix-async-infra` (confirmado mergeado: antes figuraba "sin merge explícito"), `chore/landing-visual-cleanup`, `fix/backend-suite-green-docs-sync`, `fix/studio-three-bugs`, `feature/remove-deprecated-modules`.

### 2.2 Historial reciente de `develop` (delta real del ciclo 24→27-oct)

| Commit | Qué trajo |
|---|---|
| `e12f65e` | Merge PR #37 (contrato de métricas, Fases A/B/C) |
| `a31a09c` | Phase C: `ChangeReport` + hook de job completado |
| `633a392` | Phase B: métricas al contexto de diagnóstico de Brik |
| `2f2e9ac` | Phase A: campos de contrato + `GET /api/session/{id}/metrics` |
| `0372037` | fix(studio): el poller de progreso no gira tras un fallo |
| `9ba3a2f` | build(backend): imagen, CI y piso de paquete en Python 3.12 |
| `877f768` | fix(deploy): importa el módulo demucs que el wheel distribuye |
| `350928f` | ci(backend): recorta el costo de apt y falla rápido ante mirror trabado |
| `86ee1e8` | fix(analysis): stop inventing a silent accent for the beat past the end |
| `96a46bd` | fix(backend): suite de CI en verde + contrato HTTP del chat de Brik pinneado |
| `9579a65` | chore(backend): lint gate reproducible y verde (deuda de ruff a 0) |
| `a7264d1` | fix(deploy): servicio de Railway desde el Dockerfile, sirve en `$PORT` |

El diff `0372037..develop` = **12 archivos, todos en `apps/audiomind`** (7 src + 4 tests + `change_report.py`).

**Working tree**: limpio en lo versionado. Sigue **excluido localmente** (`.git/info/exclude`): `odd/`, `.atl/`, `docs/proposals/`, `docs/postmortems/`. Untracked permanente acordado: `commit_msg.txt` en la raíz (no tocar).

`develop` va **4 commits adelante de `main`** (los 3 del contrato de métricas + su merge) — el merge a `main` sigue pendiente de validar staging (#P1).

---

## 3. Los motores

### 3.1 Motor 1 — Mastering (AudioMind, backend FastAPI)

**Ubicación**: `apps/audiomind/src/audiomind/` · Python 3.12 · FastAPI, librosa, pedalboard, numpy, demucs-onnx. **Dockerfile**: `python:3.12-slim`, `pip install -e .` con `src/` copiada antes, escucha en `${PORT:-8000}` (hay `tests/test_runtime_python_contract.py` que pinnea el contraste CI↔imagen).

**Pipeline del engine** (`processing/engine.py`, **2,093 líneas** al 29-oct):

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
12. *(nuevo)* **Análisis del contrato de métricas**: `band_energies_dbfs()` integra los band-power por Parseval y los reporta en **dBFS reales** (piso −120 dB) — la escala del legacy `analyze_band_energies` (FFT-dB dependiente de N) **no se toca**: es la escala interna compartida con `compare_tracks`. `loudness_standard = "ITU-R BS.1770-4"` declara honestamente el medidor que el código implementa (`processing/loudness.py`).

**El contrato de métricas reales (Fases A/B/C, PR #37 mergeado 27-oct)**:

- **A — Contrato retro-compatible**: `AnalysisResult` gana `bands_hz`, `band_energies_db`, `loudness_standard` (todos opcionales con defaults → payload legacy sigue validando). Endpoint **`GET /api/session/{id}/metrics`** con bloques ensamblados y perfil de inspector on-demand con degradación honesta.
- **B — Brik deja de adivinar**: el contexto de chat lleva un bloque **`CONTRATO DE METRICAS`** con las mediciones reales; `DIAGNOSIS_SYSTEM_PROMPT` exige `DIAGNOSTICO + RECETA` citando métrica/valor/punto de referencia con cláusula de honestidad numérica (sin inventar dB). El "prohibido hablar de dB" del tail quedó scoping a lo que corresponde.
- **C — Reporte de cambios**: al completar un job de agente se mide before/after con los **mismos metros** y se publica `ChangeReport` (`ready|no_before|no_after|error`, **never-raise**: un informe que falla nunca tumba el job de DSP → `dsp_jobs.result.change_report` jsonb + JSON en **R2 bajo `reports/`** (degradación no destructiva con `StorageError`) + espejo `SessionData.change_report` para turnos de chat posteriores). El legacy re-mide su lado "before" desde disk. Reutiliza convenciones de `reference_compare` pero mide en la escala nueva; `compare_tracks` queda intocado (master vs. referencia, escala interna).
- Suite: 4 tests nuevos de A RED→GREEN en su commit, 4 de B, 6 unit + 2 integration de C — ganancia neta al pasar de 1,546 a **1,591** (84 archivos `test_*.py` hoy; 77 al 19-oct).

**Endpoints** (recontados hoy por decoradores, 29-oct): **63 operaciones** — 61 en 10 routers (`agent` **2** ← *nuevo* `POST /api/agent/chat`; `mastering` 16, incluye `GET /session/{id}/metrics`; `jobs` 9; `projects` 15; `songstarter` 7; `upload` 3; `splitter` 3; `batch` 2; `license` 2; `mix` 2) + 2 de nivel app (`/health`, `/api/demo/stats`). Montados en `main.py:73-86`. Nota: ese corte por router **no es** el corte por prefijo de URL (`mastering`/`mix`/`songstarter` publican bajo `/api/session`, `/api/beat`, `/api/album`; `jobs` bajo `/api/jobs` con `poll_url` de mix y agent). No se re-medidió el inventario vía OpenAPI (no se boot-eó el app en este ciclo).

**Infraestructura de jobs y sesiones** (sin cambios de fondo):

- `services/job_store.py`: Supabase (`dsp_jobs`) con `probe()` → fallback memoria. Lease+heartbeat; job interrumpido se marca `error`, **no se reanuda** (BackgroundTasks in-proceso). Migración de reparación `20261005180000` añadió `meta`/`lease_expires_at`.
- **Masters durables en R2** (`master_r2_key`, `_persist_master_to_r2()` never-fail, `_resolve_master_file()` con precedencia local→R2). Hueco: paths de cache-hit sin aserción directa (#P10).
- **Sesiones durables** (`session_backend.py`, default `auto`, write-behind con digest; archivo como fallback; un solo proceso). Verificar en prod: backend activo + migraciones (#P9).
- **Estabilidad Demucs**: HTDemucs fp16 horneado (~158 MB), separación en proceso hijo (`demucs_worker.py`), tope de threads 4, timeout 1800 s. `877f768` (26-oct) corrigió el import del módulo demucs que el wheel distribuye — ese fix es parte de lo que puso verde la suite de CI.

**Limpieza y lint**: la deuda de **483 errores de ruff (0 en clases F)** quedó **pagada a 0** (`9579a65`/`96a46bd`, 24-26-oct) — `ruff check .` verificado **"All checks passed!"** hoy con ruff 0.16.10 y ahora es **gate bloqueante en CI**. El saneamiento del `engine.py` del 16-oct (código muerto, `generate_report()`, helper inalcanzable) sigue vigente; quedan stubs dudosos (`measure_correlation → 0.0`) como deuda menor.

> **Único fix de Studio en el ciclo**: `0372037` — el poller de progreso dejaba de girar tras un fallo (y es el tip de `main`).

### 3.2 Motor 2 — Mix Engine (mezcla IA+DSP)

Sin cambios de código en este ciclo. Vigente lo del 19-oct, en resumen:

- **Pasos 01–08 TDD** + **Stem Balance T1–T7** (faders ±6 dB, auto-balance por género OFF por default, E2E de neutralidad) + **Character Stage** (`commercial_alt_pop`: slapback vocal, wow/flutter+chorus en `other`, saturación paralela en bass, hiss/crackle con compensación sample-level, HF-droop; solo render principal).
- **P4 Recipe Handshake**: `texture_recipe` v2 en `MixMetadata` con deltas medidos (`loudness_delta_lu`, `hf_excess_db`, `crest_delta_db`, `centroid_delta_hz`, …). Mastering lee la receta y adapta (match EQ ±2 dB, de-esser skip, LUFS compensation). **Invariante de neutralidad**: sin receta → master byte-idéntico a baseline (SHA-256 pinneado cross-commit).
- **P5 wiring**: `character`/`character_seed` en `POST /jobs/mix`, `MixJobOptions`, `MixPlan.character` desde `mix_intent` (proyectos).
- **Pipeline por stem**: split Demucs → pan → EQ → comp → dimensión → bus → comp de bus → QC (informativos, nunca bloquean) → 5 versiones → modo creativo. Neutral = routing exacto; Demucs es lossy (aceptado).
- Pendientes congelados: A/B auditivo con el WAV hip_hop del productor; `build_mix()` re-separa desde el original (#P11); EOL churn en `mix_engine.py` resuelto (`2aa40b6`).

### 3.3 Flujo de proyectos multitenant ("Moises") — backend completo, UI dormida

Igual que el 19-oct (sin cambios de código; el ciclo no lo tocó):

- **15 rutas** en `api/projects.py` (CRUD, assets presign/patch/list/download, `project_states`, documento V1 con OCC, jobs de proyecto mix/master/separate).
- **Auth/RLS**: `get_user_context` (Supabase JWT) → cliente scoped al token → RLS `auth.uid() = user_id`; en dev `DEV_USER_ID`.
- **4 tablas** (`projects`, `audio_assets`, `project_states`, `project_documents`) — **su carga en producción sigue sin verificar**.
- **R2-native**: presign PUT 900 s / GET 3600 s; la subida del original en `/upload` → `r2:` (S1–S9 MET por verificador independiente).
- **UI dormida**: `features/projects/` (context, stores, `audioEngine`) sin consumidores externos. Follow-ups: `deleteTrack` no borra el objeto R2 (huérfanos), `getOriginalSignedUrl` ignora `expiresInSeconds`.
- Servicios: `compile_project.py`, `project_jobs.py`, `separate_jobs.py` (idempotente por `media_hash`). Spec: `docs/reference/specs/project_document_v1_spec.md`.

### 3.4 Capa de inteligencia: RAG local (sin cambios; backlog de prod aprobado)

- `intelligence/rag/` (13 módulos): OCR de los PDF locales, chunking por capítulo, recuperación híbrida BM25+vector RRF, embeddings vía Ollama (`http://localhost:11434`), extra opcional `rag`.
- `POST /api/agent/rag/search` (solo lectura; degrada a BM25 declarado en `mode_used`). En contenedor: 503 sin índice (degrada, no tumba el boot — el config del 19-oct ya importa perezoso y tiene cota de resolución de rutas).
- El bucle agéntico **no lo consume todavía** (`search_knowledge` no se le ofrece al modelo). **Backlog aprobado por el usuario (27-oct)**: mover el RAG de producción a la **Opción A (R2)**.
- `intelligence/` además tiene los schemas de conocimiento (genre/preset/experiment/plugin/idea) como scaffolding sin consumidores.

---

## 4. Studio — frontend y aplicaciones acompañantes

### 4.1 Studio (Next.js 16 + React 19 + TS + Tailwind 4)

**Rutas** (sin cambios confirmados en el ciclo): `/` (landing), `/mezclas`, `/upload`, `/lab`, `/login`, `/register`, `/admin`, `/voz`, `/voz/chat`, `/voz/speak`, `/voz/escuchar`, `/auth/callback`, `robots.txt`, `sitemap.xml`.

**Tabs de `/mezclas` (8)**: `Mezcla de Audio` · `Masterizar Audio` · `Splitter` · `Beats` · `Análisis` · `Estéreo` · `Álbum` · `Productor IA`. (Los paneles educativos y la Vocal chain ya no existen.)

**Novedad del ciclo (Brik chat ya vivo en Studio)**: `AgentPanel` y `client.ts` consumen **`POST /api/agent/chat`** (contrato HTTP de Brik pinneado por `96a46bd`). La consulta va por sesión (`chat` con historial en SnapshotSession) y el widget renderiza diagnóstico, herramientas ejecutadas y métricas.

**Pendiente de UI nueva (Fase C)**: el `ChangeReport` existe en `dsp_jobs.result.change_report` y en la sesión, pero **ningún componente de Studio lo renderiza aún** (0 hits de `change_report` en `apps/studio`).

- **Mix UI**: `MixPanel` + `MixWaveformAB` + `MixStatusStream` con acción "masterize" post-mezcla (`doneLabel` hardcodeado sigue siendo deuda #P6).
- **Polling con backoff** (`useProcessingProgress` 500 ms, `useMasteringJob` 2500 ms) y el fix `0372037` del poller tras fallo.
- **Voz**: TTS ElevenLabs opcional (tope 400 chars, `204` → `speechSynthesis`), `useVoiceInput`, `lib/voice/decodeAgentText`.
- **i18n**: `useTranslation()` con `es.json`/`en.json` — **850 claves hoja cada uno, paridad exacta** (recuento verificado hoy; eran 765 el 16-oct).
- **Tests**: vitest 11 archivos/134 (19-oct) · eslint 0 err/37 warn (19-oct) · build exit 0. En CI, `bun run lint` es bloqueante (la deuda previa está pagada).

**Arquitectura** (capas, sin cambios): `app/` rutas · `adapters/` (api/audio) · `features/` (7 módulos con barrel: mastering, projects, tracks, upload, auth, admin, remastering-history) · `application/hooks/` (incl. `useStereoField` de solo lectura) · `presentation/components/` (~42 en raíz + dock/audio/chat/landing (21)/ui) · `shared/` · `lib/` · `i18n/`. Estado por React Context (`I18nProvider → AuthProvider → MasteringProvider`) + `useState`; motion con framer-motion 12 + GSAP 3.15 (hero, tagline, escala del player); audio cliente con `tone` y `wavesurfer.js`.

### 4.1.1 Mobile y responsive (web — sin app nativa)

Vigente del 16-oct, inalterado: **0 nativo/PWA** (no hay manifest ni service worker). `/mezclas` decide con `useIsMobile` (breakpoint 768; SSR y primer paint renderizan escritorio → flash conocido, sin script pre-hidratación); landing y headers con breakpoints Tailwind. Piezas mobile: `MobileMasteringView`, `MobileDrawer` (estudio, desliza desde la izquierda), `MobilePresetStrip` (carrusel snap-x), menú mobile **propio** de la landing (`MobileMenuContext` + drawer derecho con focus trap). Viewport `cover` con `--vh` fallback y `.pt-safe/.pb-safe`; objetivos táctiles 44 px en piezas nuevas (la deuda de 27–36 px sigue abierta, #P3); `prefers-reduced-motion` respetado globalmente.

### 4.2 Landing page — en producción (sin cambios confirmados en el ciclo)

Vigente del 16-oct: 18 componentes `.tsx` + data/types/index en `presentation/components/landing/`; `page.tsx` con JSON-LD `FAQPage` desde `es.json` y `alternates.canonical`; `LandingABPlayer` con tono sintético (saw 110 Hz + sub 55 Hz → lowpass Q 0.7, anti-zipper con `setTargetAtTime`) y waveform Canvas de 96 barras; fonts self-hosted (Syne, Plus Jakarta Sans, JetBrains Mono, Instrument Serif); `next/image` en footer real; GSAP con `useHeroGSAP`/`useTaglineReveal` y gates por viewport. **3 decisiones de producto abiertas**: `--font-sans` sin mapear en el hero, controles 27–36 px, precios placeholder.

### 4.3 apps/agent (`@midimastering/agent`)

Sin cambios: traduce lenguaje natural → `IntentProfile` (Gemini + Zod), no toca audio. `vocal_focus` re-alineado con el schema (13-oct). Sigue pendiente la llamada real con credenciales.

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

> **Deuda de documentación vigente y afirmada hoy** (verificada 29-oct):
> 1. `docs/README.md` (índice central) **no menciona** la landing, ni el flujo de proyectos, ni R2, ni el orquestador Cloudflare — describe el pipeline sin nada de esto.
> 2. `docs/reference/specs/` — `01`, `06` y `07` siguen describiendo el Live Engine y HumanMidi; contradicen "dos motores + flujo de proyectos + orquestador".
> 3. `AGENTS.md` (raíz) dice "sesiones del backend en memoria (dict + SessionCache)" — **ya no es verdad** (sesiones durables en Postgres, §3.1), y no menciona el job de backend en CI ni `apps/orchestrator`.

---

## 6. Entorno, CI/CD y verificación

### 6.1 CI (`.github/workflows/studio-ci.yml`) — dos jobs bloqueantes

| Job | Qué hace |
|---|---|
| `build` (Studio) | Checkout → Node 22 → bun install `--frozen-lockfile` → `bun run lint` (bloqueante) → `bun run build` |
| `backend` (nuevo, `b9dc5e8` 22-oct) | Checkout → **Python 3.12** (must match `Dockerfile`; lo pinnea `test_runtime_python_contract.py`) → deps de sistema **apt con `--no-install-recommends` + retries + timeout de 15 min + cache de `.debs`** (`350928f`: el mismo paquete tomó 273 s en una corrida y 37.7 min en otra por mirrors trabados) → `pip install -e ".[dev]"` → **`ruff check .` bloqueante** → `python scripts/generate_samples.py` (los samples son gitignored; esto resuelve los 4 fallos de songstarter de un clone limpio **en CI**) → `pytest tests/ -q` con env de demo (`SESSION_TTL 60`, `MAX_CONCURRENT_DSP 1`, Demucs fp16 aislado, etc.) |

Triggers: PRs y push a `develop`/`main` con cambios en `apps/studio/**`, `apps/audiomind/**`, `pyproject.toml`, `requirements*.txt`, raíz de paquetes; además `workflow_dispatch` para correrlo a mano. **Sin gate de e2e.**

> El backend pasó de "nada en CI" (hallazgo del 19-oct) a **job completo con gates**. La decisión que queda: supervisar el flake residual de apt (mitigado, no eliminado — las colas del índice no se cachean).

### 6.2 Deploy actual

- **Frontend (Studio + landing)**: Vercel ✅ (`NEXT_PUBLIC_API_URL` → Railway).
- **Backend (AudioMind)**: Railway — el servicio se construye desde **`apps/audiomind/Dockerfile`** (`railway.json` de la carpeta con builder DOCKERFILE, healthcheck `/health` 300 s, `uvicorn … --port $PORT --workers 1`; `a7264d1` 24-oct, y se borró `apps/audiomind/nixpacks.json`). Los `railway.json`/`nixpacks.json` de la **raíz** son la config del **Studio** (bun/NIXPACKS) — no del backend.
- **Audio**: Cloudflare R2 ✅ (originales por presigned PUT, mezcla y masters persistentes, JSON de `ChangeReport` bajo `reports/` desde 27-oct).
- **Auth/metadata/jobs/sesiones/proyectos**: Supabase (Postgres) ✅ — con `dsp_jobs`, `sessions`, reparaciones y `masters.status` aplicadas según registro; **las 4 de proyecto y las verificaciones de prod siguen sin confirmar** (#P9, #P5).
- **Migraciones**: `supabase/migrations/` versionadas, **sin Alembic** (se aplican a mano; #P7).

### 6.3 e2e (Playwright)

Sigue en 1 spec:`e2e/tests/demo_flow.spec.ts` (chromium, webServer dev). No ejecutado en este ciclo.

### 6.4 Camino a infraestructura de pago (además de Cloudflare)

Los límites actuales son de plan: Railway ≥1 GB (hay OOM histórico, mitigado con Demucs fp16 + proceso hijo + `DJ_LIMIT_WORKERS` cuyo caveat `reset_gate()` sigue en pie), volume persistente para `outputs/`/`uploads/`, Supabase Pro. Nada de esto bloquea desarrollo.

### 6.5 🆕 Orquestador Cloudflare Containers — Fase 1 (spike listo, deploy bloqueado)

**Estado**: el spike existe **solo localmente** en `feat/cf-orchestrator-spike` @ `dc22418` (rebased sobre `develop`; **no está en ningún remote ni en `develop`/`main`**). Contenido:

| Archivo | Rol |
|---|---|
| `apps/orchestrator/src/index.ts` | Worker `waveai-orchestrator`: `/__diag` (worker-only, nunca toca el container) + todo lo demás **passthrough** al container `dsp.internal` |
| `apps/orchestrator/src/container.ts` | `DSPContainer` keyed `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB, dimensionado con margen sobre el pico RSS de htdemucs y `AUDIOMIND_MAX_CONCURRENT_DSP=1`) |
| `apps/orchestrator/wrangler.jsonc` | Build del Dockerfile de audiomind al managed registry de CF, migration `new_sqlite_classes` (fallback documentado a `new_classes`) |

**Plan de fases aprobado** (del README del spike): ① worker + container con smoke de `/health` y `/process` · ② subida/descarga R2 presignada browser↔R2 (endpoint ya existe) · ③ Cloudflare Queues (producer/consumer, un job por container, DLQ) · ④ Studio en Workers vía OpenNext.

**Bloqueos vigentes (acción del usuario, avanzando)**: comprar **Workers Paid** (Containers no está en Free) + instalar **Docker Desktop** (el build de la imagen es local). Al tener ambos: `npx wrangler login` → `npx wrangler deploy` → smokes en orden `/__diag` → `/health` → `POST /api/upload` + `POST /api/session/{id}/process` con fixture de 6 s (`scripts/generate_samples.py`), esperando `completed` con `progress=1.0`. Reporte de RSS/cold start con honestidad total si algo falla.

---

## 7. Pendientes y decisiones del usuario

> Renumerados para este relevamiento. **Cerrados desde el 19-oct** (referencia de integridad): #34 (gate backend+ruff en CI, deuda pagada a 0), #45 (Railway desde Dockerfile), #48-parte (samples generados en CI), #22-flake apt mitigado, #2/#3/#4/#6/#7/#9/#14/#17/#22/#27/#30/#31/#33 siguen cerrados como el 19-oct. Los números del 19-oct se citan como (o#n).

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| **P1** | **Promoción `develop` → `main`**: staging validado → merge a `main` (trae el contrato de métricas a producción del repo) | Git/Deploy | Decisión del usuario |
| **P2** | **Deploy Fase 1 del orquestador Cloudflare**: comprar Workers Paid + instalar Docker + `wrangler login` → deploy → smokes `/__diag`, `/health`, `/process` con fixture de 6 s | Deploy | **Acción del usuario, bloqueante — en curso** |
| **P3** | **Landing — 3 decisiones de producto**: `--font-sans` sin mapear, controles 27–36 px, precios placeholder (o#37) · deuda de jerarquía h4/h5 en `LandingDSPChain` (o#39, T6–T8 abiertos) | Landing | Decisión del usuario |
| **P4** | **UI del `ChangeReport`**: consumir `change_report` (job polling o espejo de sesión) y renderarlo con microcopy i18n + tokens del design system | Studio | Trabajo pendiente |
| **P5** | **Flujo de proyectos en producción**: cargar 4 tablas + env, correr `verify_prod_wiring.py`, probar `/projects/*` end-to-end (o#42) · **UI dormida** de proyectos sin consumidores (o#44, #51) | Deploy/Frontend | Trabajo pendiente |
| **P6** | `MixStatusStream.doneLabel` hardcodeado en español (o#24); `character_seed` expuesto en MixPanel (o#52, decisión) | Frontend | Deuda técnica |
| **P7** | **Sin Alembic** (o#25): migraciones a mano · progreso por etapa del job (o#21) · dedup de submits (o#20) · cola real (o#19, fuera de alcance v1) | Backend | Deuda técnica |
| **P8** | **Credenciales R2 a rotar** — quedaron expuestas; el token viejo es el que carga producción hoy (o#13) | Deploy | **Acción del usuario** |
| **P9** | **Verificaciones de prod pendientes**: backend de sesiones `auto`, aplicacion de `20261005180000`/`20261005220000`, `masters/` 4 objetos basura + aserción de cache-hit (o#32/#46/#47) | Deploy/Backend | Acción del usuario |
| **P10** | R2 real: falta ejercitar la **descarga** (o#15) · follow-ups de subida híbrida: `deleteTrack` no borra el objeto, `expiresInSeconds` ignorado (o#41) | Deploy/Studio | Prueba manual + decisión |
| **P11** | `build_mix()` re-separa desde el original en cada corrida (o#43) · remixes sobrescriben el mismo `r2_key` (o#23) · huérfanos de R2 (o#41-parcial) | Backend | Deuda técnica |
| **P12** | **RAG de producción Opción A (R2)** (backlog aprobado 27-oct) · el bucle agéntico no consume el RAG · `search_knowledge` no se ofrece al modelo | Backend/Deploy | Trabajo pendiente |
| **P13** | **Reaper de sesiones TTL 60 min** en producción (backlog aprobado 27-oct); hoy existe el janitor de demo y `session_ttl_minutes` default `0` | Backend/Deploy | Trabajo pendiente |
| **P14** | A/B auditivo del Mix con la sesión hip_hop del productor (o#5/#12-parte; requiere el WAV que no está en el repo) · E2E manual de "Mezcla de Audio" con toggle Carácter (o#5) | Mix Engine | Prueba del usuario |
| **P15** | `interpretIntent` real (credenciales Gemini) + corrida real del Productor IA (credencial LLM) para ver el DIAGNÓSTICO/RECETA y el ChangeReport en producción (o#8 extendido) | IAM/Backend | Decisión del usuario |
| **P16** | Históricos de ingeniería: push de `feat/mix-engine/01…08` (o#1) · retención de `outputs/` fuera del volume (o#10) · segundo libro + autotune creativo (fuera de v1, o#11) | Mix Engine | Decisión del usuario |
| **P17** | **`DJ_LIMIT_WORKERS`**: `reset_gate()` sigue ignorándolo y la descripción en `AGENTS.md` sigue laxa (o#28) · stubs `measure_correlation→0.0` (o#35-parte) · golden fingerprint 1e-3 dB (o#50) | Backend | Trabajo pendiente |
| **P18** | **UI three-bugs**: T1 (modal) y T2b ("Not Found") bloqueados por falta de evidencia del navegador (o#40) · `manual INSERT` de jobs sigue siendo parche operativo (o#29) | Frontend | Evidencia del usuario |
| **P19** | **RDD no ejecutable en este runtime** (`review assess` → `unassessable`; requiere 1.x estable sin relay o 2.x con plugin V2): desactivarlo clone-local o correr el review en un runtime elegible (o#49) · gate RDD de `landing-motion` y estrategia de PR (~450 líneas) (o#38) | Proceso | Decisión del usuario |
| **P20** | **Higiene de docs (afirmada hoy)**: actualizar `docs/README.md` (landing, proyectos, R2, orquestador), specs `01/06/07` (Live Engine/HumanMidi stale) y `AGENTS.md` (sesiones durables, job de backend en CI, `apps/orchestrator`) | Docs | Trabajo pendiente |
| **P21** | Higiene git: cerrar/borrar la copia redundante en `waveia` de `feat/agent-metrics-contract` y el auto-close no ocurrió — **el issue #36 sigue OPEN** pese a "Closes #36" en el PR/#37 mergeado | Git/GitHub | Acción del usuario |
| **P22** | `develop` sin sincronizar con el espejo `origin` (`main` @ `1c0379b`, sin `develop`): decidir si `origin` sigue vivo o se abandona | Git | Decisión del usuario |

---

## 8. Documentación: dónde está todo

**Canónica** (`docs/reference/`, `docs/runbooks/`, `docs/manual/`, `docs/evidence/`): índice central `docs/README.md` (**stale — ver #P20**) · specs de implementación (`08_implementacion_llm.md` prompt exacto de implementación) · `COMPLIANCE_PHASE1.md` · `DSP_INDUSTRY_REVIEW.md` · `DESIGN` · SETUP/DOCKER/DEPLOY · `project_document_v1_spec.md`.

**Histórica** (`docs/archive/`): integración, workplan, plan original. `05_live_engine_gestos_a_master.md` es **histórico** del engine removido; `INTEGRATION_REPORT.md` archivado.

**Local-only (excluida de git)**:

- `docs/proposals/` — 4 PDF de libros de mezcla (materia prima del RAG) + propuestas.
- `docs/postmortems/` — `inc-2026-04-22-checkout-5xx.md`.
- `odd/` — **37 documentos de tareas** (29-oct). Destacados del ciclo y su estado:

| Documento | Estado |
|---|---|
| `agent-metrics-contract.md` | **Cerrado y mergeado** (PR #37, Fases A/B/C) · Log L1–L5b con la corrección del reanclaje del PR (leak del spike detectado pre-merge) |
| `saneamiento-develop-16-oct.md` | Cerrado (T1–T9 ✔) |
| `subida-original-r2-hibrida.md` | T1–T5 ✔; follow-ups (#P10) |
| `moises-multitenant-project.md` | WU1–WU5 ✔; prod pendiente (#P5) |
| `landing-awwwards-elite.md` / `landing-motion.md` / `landing-tipscale-cascade-fix.md` | Feature completo; decisiones de producto + gate RDD pendientes (#P3/#P19) |
| `backend-suite-green-docs-sync.md` | Cerrado |
| `ui-three-bugs.md` | T1/T2b bloqueados por evidencia (#P18) |
| `deploy-backend-config-and-lint.md` | Consumido (commits 24–26-oct; CI + deploy + lint a 0) |
| `brik-chat-router.md` / `brik-decision-layer.md` / `agent-sidebar` / `agent-character-tool` | Consumidos (Brik chat vivo) |
| `operational-hardening.md` | Follow-up continuo (#P13 reaper, etc.) |

- `.atl/` — skill registry local.

**Memoria Engram** (`brikmaster2027`): topología de ramas (29-oct) y entrega del PR #37 registradas; mirrors de tareas siguen mejorables varias features atrás.

---

## 9. 🧭 Cómo funciona el sistema (de extremo a extremo)

> Esta sección es la guía arquitectónica del producto pedido en el relevamiento: qué pasa cuando algo entra, qué lo procesa y qué queda persistido. Los estados de cada pieza están en §1–§6; acá está el **funcionamiento**.

### 9.1 Topología general

```text
┌─ Browser (Studio / landing) ────────────────────────────────────────────────┐
│ Next.js 16 + React 19 (Vercel)                                             │
│  Contexts (I18n/Auth/Mastering) · hooks de polling · Web Audio (leer)        │
└──────┬──────────────────┬───────────────────────────┬──────────────────────┘
       │ HTTP REST        │ Supabase JS (auth)        │ (futuro: R2 presign directo)
       ▼                  ▼                           ▼
┌─ AudioMind (FastAPI, uvicorn 1 worker) ── Railway, Docker (python:3.12-slim)─┐
│  10 routers · engine DSP (Mastering) · Mix Engine · agentic_loop · RAG       │
│  boto3→R2 · Supabase client → Postgres                                       │
└──────┬──────────────┬───────────────────────────┬────────────────────────────┘
       ▼              ▼                           ▼
  Cloudflare R2   Supabase Postgres          LLM externo (transporte
  (WAV originales, (sessions, dsp_jobs,       model-agnostic del bucle;
   mezcla, masters, projects, masters)        Gemini en apps/agent)
   reports/*)
```

Futuro (Fase 1 del orquestador Cloudflare, §6.5): ese HTTP del browser apunta a un **Worker de Cloudflare** que enruta a `DSPContainer` (misma imagen de audiomind); R2 pasa a ser primera clase con presign browser↔R2.

### 9.2 Vida de una sesión de mastering (el flujo canónico)

1. **Subida** — `POST /api/upload` (multipart): valida tamaño/max, guarda el WAV en disco local y devuelve `SessionData` (el contrato central, pydantic, config `extra="ignore"` + persistencia auto de espejos como `change_report`). La sesión vive en un **dict en proceso** (fuente de lectura) con *write-behind*: digest por sesión hacia Postgres (backend `auto`: Supabase → archivo como fallback). Invariante documentada: **un solo proceso uvicorn** — el backend no soporta múltiples workers contra el mismo store.
2. **Análisis** — `analyze_audio` (librosa) produce `AnalysisResult`: LUFS integrado, crest, género, y con el contrato de métricas (Fase A) las **bandas en dBFS reales** (`band_energies_dbfs` por Parseval, piso −120) + `bands_hz` + `loudness_standard="ITU-R BS.1770-4"`. Todo eso queda en la sesión y desde el 27-oct es visible por `GET /api/session/{id}/metrics`.
3. **Elección de preset** — presets del catálogo (o prerender por preset, que pre-computa el master de una variante), con `platform_target` (spotify/apple_music/youtube/tidal/custom: floors UI + recorte de true peak del limiter).
4. **Proceso** — `POST /api/session/{id}/process` ejecuta el **engine** (§3.1, 12 pasos: QC 422 → gain staging → de-esser → match EQ → carácter → smart gate → M/S → mono <120 Hz → soft clip + limiter TP 8× → dither/resample → validación LUFS/DR/fase). Neutral (todo a defaults) = **bypass bit-exacto**. El master resultante se **persiste a R2** fuera del event loop (nunca falla la request) y la sesión guarda `master_r2_key`.
5. **Descarga** — `GET /api/session/{id}/download/{format}` resuelve el archivo con precedencia **local → R2** (`_resolve_master_file`, 4 consumidores centralizados); objeto ausente → 404 nombrando la clave, jamás un fallback silencioso al original.
6. **Detalle de UI** — el Studio poll-ea `GET /api/session/{id}` con backoff exponencial (fix `0372037`: si el job falló, el poller deja de girar).

**Cadena de referencia externa** (opcional): subir *reference track* y `compare-reference` compara tu master contra ella en la escala FFT-dB interna (`compare_tracks` — la misma que usa el veredicto); es otra cosa que el `ChangeReport` del agente, que mide before/after en dBFS de contrato.

### 9.3 Los dos modelos de trabajo: sync y async

| Modelo | Rutas | Cómo corre |
|---|---|---|
| **Sync (en request)** | `POST /api/session/{id}/process`, `POST /api/session/{id}/mix` | DSP directo en el ciclo de la request; el pool `DSP_THREAD_POOL` (limitado por `DJ_LIMIT_WORKERS`/`max_concurrent_dsp`) protege el contenedor único de Railway |
| **Async (jobs)** | `POST /api/jobs/mix/{id}`, `POST /api/jobs/agent/{session_id}`, jobs de proyecto (`/projects/{id}/jobs/mix|master`) | Registro **antes** de encolar en `dsp_jobs` (Supabase o memoria), `BackgroundTasks` in-proceso, **lease + heartbeat** (worker muerto → la fila queda `error`, no `processing` para siempre). Polling por `poll_url`. Estados: `queued → running → completed \| error`. Job interrumpido **no se reanuda** |

**Frontend → sesión**: el camino async del mix ya escribe `mix_r2_key` en la sesión (fix §3.2.1: si el mix no es entregable pero R2 falla, la masterización responde **400, no masteriza el original**).

### 9.4 Brik: cómo piensa el agente (Fases A/B/C en acción)

`processing/agentic_loop.py` corre un bucle de **4 fases** con transporte **model-agnostic** (sólo pide *messages + tools* al proveedor):

| Fase | Qué hace | Herramientas típicas |
|---|---|---|
| 1 — Diagnóstico | Recorre el audio | `analyze_original_audio` |
| 2 — Separación | Demucs para despegar stems | `trigger_stem_separation` |
| 3 — Mezcla/ajuste | Renderiza el mix, ajusta parámetros por stem | `render_mix`, `analyze_mix_bus`, `adjust_stem_parameters`, `search_knowledge` |
| 4 — Entrega | Manda el resultado a masterización | `send_to_master` |

- **Contexto honesto (Fase B)**: el snapshot de sesión se serializa con un bloque **`CONTRATO DE METRICAS`** (mediciones reales en dBFS/LUFS del medidor declarado), y el system prompt de diagnóstico exige **DIAGNÓSTICO + RECETA** citando métrica/valor/referencia con cláusula de honestidad numérica (si el DSP midió X y el modelo dice otra cosa, el usuario lo detecta).
- Si el trabajo es pesado, `should_escalate_to_job` manda la operación a un **job async**; el polling `GET /api/jobs/agent/{id}` entrega el resultado.
- **Al completar (Fase C)**: hook de job completado → `ChangeReport` **before/after con los mismos metros en ambos lados** (nunca raise: `ready|no_before|no_after|error`) → se cuelga en `dsp_jobs.result.change_report` + JSON en R2 `reports/` + espejo en la sesión para los próximos turnos de chat. El Studio todavía no lo renderiza (#P4).

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
| `presentation/components/` | ~ componentes de UI: dock/tiles de etapas, player, waveforms, mix, chat, landing (21 archivos), mobile |
| `shared/` + `lib/` | `useIsMobile` (768 px, `matchMedia`), motion (framer-motion 12 + GSAP 3.15), `audioContext.ts` (`safeCloseAudioContext`), supabase client, i18n (`useTranslation()`; es/en paridad exacta, 850/850 claves hoy) |

**Reglas de comportamiento que el código respeta**: (a) **todo parámetro Web Audio con `setTargetAtTime(value, ctx.currentTime, 0.02)`** — jamás asignación directa (anti-zipper; aplica al análisis estéreo y al A/B player de la landing); (b) **i18n obligatorio**: nada hardcodeado en TSX (deuda viva: el `doneLabel` default del `MixStatusStream`); (c) SSR/primer paint siempre escritorio y luego la variante mobile via `useIsMobile` (flash conocido: no hay script pre-hidratación); (d) el estado global es **React Context chain** (`I18nProvider → AuthProvider → MasteringProvider` en `layout.tsx`) + `useState` local — no hay zustand/redux; los "stores" del flujo proyectos (`projectDocumentStore`, `mixStateStore`) existen testeados y **dormidos** hasta que una vista los consuma (#P5).

**El flujo del Studio en el ciclo de una masterización**: `/upload` (DropZone) → `useMasteringWorkflow` decide storage: si es flujo proyecto → presign R2 (`trackStorageService.uploadOriginalToR2`: presign → PUT → PATCH → path `r2:`), si no → sube a la sesión en AudioMind → workspace mobile o desktop (`ModuleDock` + `PaintedModule` de la cadena DSP) → presets con perfil por género (`PlatformSelector` si hace falta) → **Masterizar Audio** (poll con backoff) → `MasteringReportCard`/`FloatingDeliveryPanel` con métricas + descargas WAV/MP3. Si escribiste texto (Productor IA), `AgentPanel` corre el ciclo §9.4 y muestra diagnóstico/herramientas/métricas; para el mix, `MixPanel` + toggle "Carácter analógico" y acción masterize post-mezcla.

### 9.8 Auth y multi-usuario

- **Studio**: Supabase Auth (`middleware.ts` → `updateSession`, `features/auth/`, `/auth/callback` intercambia código). El layout monta `AuthProvider`.
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

- **Release**: PRs → `develop` (checks: build Studio + backend pytest/ruff) → **merge a `main` tras validar** (la política del repo; futura promoción del contrato de métricas = #P1). CI: 2 jobs bloqueantes; `workflow_dispatch` manual; sin gate e2e.
- **Nube actual**: Vercel (frontend) · Railway (backend, Dockerfile propio) · Cloudflare R2 + Supabase (datos). **Destino probable**: Cloudflare Containers (orquestador listo localmente, §6.5) con R2 presign y CF Queues para jobs — la Fase 1 del spike ya mapea esa transición sin codear nada del backend: el container es el mismo Dockerfile de audiomind.
- **Contratos estables**: `packages/contracts/live_params.schema.json` **dormido** (sólo reactivar si el engine Live vuelve) · `intent_profile.schema.json` · `project_document_v1_spec.md` · el **contrato de métricas** (dBFS/Pisval del medidor BS.1770-4).

---

*Documento re-escrito el 2026-10-29. Método: lectura de código y ODD desde este checkout; números de CI/suites citados con fecha de su ejecución (backend 1,591 re-medido el 29-oct (204 s, 1 warning, 0 failed) sobre este checkout cuyo árbol de `apps/audiomind` == tip de `develop`; ruff, remotes, endpoints, i18n y Dockerfile verificados hoy; vitest/eslint/build por medición del 19-oct, su ciclo no tocó Studio). Pendiente marcado explícito: verificaciones de prod (backends/migraciones/objetos R2), corridas reales con credenciales, deploy del orquestador.*
