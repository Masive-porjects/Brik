# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha del relevamiento**: 2026-11-04 · **Base verificada**: `waveia/main` @ `b462cf6`.
> **Novedades (30-oct→4-nov)**: CORS de `www.brikmusic.online` y `brikmusic.online` desplegado y comprobado en Cloudflare; el API productivo dejó de estar en Railway y hoy entra por el Worker `waveai-orchestrator` hacia AudioMind en Cloudflare Containers. El contenedor desplegado es la versión 3 (imagen `sha256:84cd6f7858e3f42f143dfb810aede5cfe4a8d87f07c0564d8396c1e401dd6231`); la versión Worker confirmada es `6de4cd8c-85ce-44e3-9c1f-b21fe4d90d35`. El commit `b462cf6` añadió SSE de jobs/agentes, stems tempranos, persistencia de chat con Zustand y ajustes UI; **ese código todavía necesita el próximo `wrangler deploy` manual del usuario para llegar al contenedor**.
> **Operación de ramas acordada**: cambios puntuales empiezan en `main`; si el alcance requiere integración, se trabaja primero en `develop` y luego se integra a `main`. No dejar trabajo funcional únicamente en ramas locales.
> **Alcance**: repositorio completo — los dos motores DSP vivos (Mastering, Mix), el flujo de proyectos multitenant, landing, Studio, agentes de IA, capa de inteligencia, contratos, orquestador Cloudflare, entorno, CI/CD, ramas y pendientes — más la **guía de cómo funciona el sistema de extremo a extremo (§9)**: topología, vida de una sesión, jobs, agente, mix, frontend, auth, almacenamiento y release. El Live Engine, Convex, `apps/bridge` y `simulator/` ya no existen; ver §5.
> **Fuentes**: código (`apps/`, `packages/`, `supabase/`, `e2e/`), documentos ODD (`odd/tasks/`, excluidos de git), estado git real verificado hoy, workflow de CI leído en el árbol y suites de verificación ejecutadas (fechas citadas en cada cifra).

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | 🟡 Código en `main`, API productiva en Cloudflare Containers · cadena proporcional + Character Stage + métricas reales (`band_energies_dbfs`, `GET /api/session/{id}/metrics`, `ChangeReport`) · **SSE `GET /api/jobs/agent/{id}/events` está en `b462cf6`, pendiente de publicar en la imagen** · suite **1,633 passed / 0 failed** (4-nov; 1 warning preexistente de Starlette) · último ruff confirmado: 0 errores (29-oct), gate bloqueante en CI |
| **Motor de Mezcla (Mix Engine)** | ✅ Pasos 01–08 (TDD estricto) + Stem Balance T1–T7 + Character Stage P3/P4 (`texture_recipe` v2 con deltas medidos) + P5 wiring async/proyecto · defecto del camino async corregido y commiteado (`a3fd00c`) · queda el A/B auditivo con la sesión hip_hop del productor (su WAV no está en el repo) |
| **Flujo de proyectos multitenant ("Moises")** | 🟡 Backend completo (WU1–WU5) + subida directa de originales a R2 verificada · **UI dormida**: `ProjectContext`/`useProject` y los stores siguen sin consumidores · falta cargar las 4 tablas y env en producción |
| **Orquestador / API Cloudflare Containers** | ✅ **En producción**: Worker `waveai-orchestrator` enruta a `DSPContainer` `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB) con imagen v3 · `GET /api/license/status` con ACAO 200 para `www` y apex; preflight `OPTIONS /api/upload` 200 para `www` (apex preflight no medido) el 4-nov · **pendiente** redeploy del código `b462cf6` para activar SSE en el contenedor · fases 2–4 (R2 browser direct, Queues, OpenNext) siguen como roadmap |
| **Motor en vivo (Live Engine)** | ❌ **Removido del producto** (`ba3b4a6`, 27-Sep). Queda el schema como contrato dormido |
| **Landing page** | ✅ Nueva, en producción (Vercel) — GSAP, i18n completo, A/B demo local, SEO/JSON-LD · 3 decisiones de producto abiertas (#P3) |
| **Frontend y Mobile (web)** | ✅ Studio + landing · sin app nativa/PWA · `AgentPanel` persiste mensajes por sesión en Zustand/localStorage y consume SSE con fallback al GET de estado; `AgentStemStack` aparece tras separación · `ChangeReport` sí se renderiza · `/mezclas` y `/voz` usan shell `100dvh`; validación visual de perfiles inferiores sigue pendiente con track cargado |
| **Agent de interpretación (IA)** | 🟡 Compila · `vocal_focus` en el contrato · **llamada real sin probar** (faltan credenciales Gemini) |
| **Productor IA (bucle agéntico, Python)** | 🟡 Bucle de 4 fases + tool calling + transporte model-agnostic · submit `POST /api/jobs/agent/{session_id}` + SSE `GET /api/jobs/agent/{id}/events` · publica stems luego de Demucs antes de mix/master · métricas reales y `ChangeReport` · corrida real con LLM todavía no verificada por credenciales |
| **Capa de inteligencia (RAG)** | 🟡 CLI local sobre los libros de mezcla (OCR, BM25+vector RRF, Ollama) · expuesto por `POST /api/agent/rag/search` (en el contenedor responde 503 sin índice) · el bucle agéntico **todavía no lo consume** · **aprobado como backlog**: RAG de producción "Opción A" (R2) |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | ❌ **Eliminado** (repo + CI) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** |
| **Deploy (Vercel + Cloudflare + R2 + Supabase)** | ✅ Frontend en Vercel · API AudioMind en Cloudflare Worker + Container · R2 para audio, Supabase para auth/metadata/jobs · Railway ya no es destino operativo (sus archivos/configs restantes son legacy) |
| **Sesiones del backend** | ✅ Durables en Postgres (`sessions`, backend `auto`) con fallback a archivo · **aplicación en prod sin verificar** |
| **Suites de verificación** | AudioMind **1,633 passed / 0 failed** (4-nov) · Studio full: **168 passed, 3 fallos preexistentes** en el mock de `logTrackEvent.test.ts` (`insert` vs `.upsert()`, misma discrepancia en base `bbe4774`) · build exit 0 · ESLint 0 errores / 41 warnings · i18n ES/EN 934/934 · e2e no ejecutado |

---

## 2. Estado del repositorio (git, verificado 2026-11-04)

### 2.1 Ramas y remotes

Los remotes cambiaron respecto de la versión anterior de este documento: ya **no existen** `brik`, `masive`, `team`. Quedan dos:

| Remote | URL | Rol |
|---|---|---|
| `waveia` | `https://github.com/Masive-porjects/Brik.git` | **Producción/staging**: `main` y `develop` viven aquí |
| `origin` | `https://github.com/brikpaul569-cmd/BrikMaster2027.git` | Espejo de trabajo local (**stale**: `main` @ `1c0379b`, sin `develop`)|

| Rama | Tip | Estado |
|---|---|---|
| `main` | `b462cf6` | **== `waveia/main`** · rama activa del relevamiento · working tree limpio antes de editar este documento |
| `develop` | `2b34004` | **== `waveia/develop`** · según los refs locales está 14 commits detrás de `main` y 0 adelante; no usar para cambios nuevos hasta sincronizarlo desde `main` |
| `feat/ui-sse-stems-chat-layout` | `b462cf6` | Ref local redundante: mismo commit que `main`, ya publicado; no contiene trabajo exclusivo |
| `origin/main` | `1c0379b` | Espejo **stale**; no se recalculó su divergencia exacta frente a `waveia/main` y no es fuente de trabajo |
| `feat/cf-orchestrator-spike` | `2219d2b` | Ref local histórica; el orquestador ya está en `main` y desplegado, no continuar el trabajo desde este spike |

El remoto canónico es `waveia`; `origin` queda solo como espejo histórico. El usuario establece esta pauta: **cambios puntuales desde `main`; si una tarea necesita integración amplia, primero sincronizar `develop` desde `main`, trabajar allí y luego integrar a `main`**. No dejar cambios funcionales únicamente en ramas locales. Los conteos de divergencia se calcularon con refs locales; este relevamiento no hizo `fetch`.

### 2.2 Cambios recientes en `main` (30-oct→4-nov)

| Commit | Qué trajo |
|---|---|
| `b462cf6` | SSE de jobs/agentes, publicación de stems antes de mix/master, persistencia del chat con Zustand, layout `100dvh` e i18n de MixPanel |
| `bbe4774` | CORS de `brikmusic.online` + errores de transporte del upload |
| `8759077` | Redirects de Supabase Auth para `www.brikmusic.online` |
| `65b5ef2` | Normalización del `onConflict` de `track_events` |
| `06c19ae` | Ajustes de layout/i18n para upload, mezclas y sidebar |

El último push confirmó `bbe4774..b462cf6` en `waveia/main`. El tree estaba limpio antes del cambio de este documento. Siguen excluidos de git por `.git/info/exclude`: `odd/`, `.atl/`, `docs/proposals/` y `docs/postmortems/`.

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
- Suite: el histórico de Fases A/B/C subió la cuenta de 1,546 a 1,591 (medición 29-oct). **Última suite completa: 1,633 passed, 0 failed (4-nov)**; 84 archivos `test_*.py` en la medición anterior.

**Endpoints**: inventario anterior (63 operaciones, 29-oct) ya no es exacto porque `jobs` sumó **`GET /api/jobs/agent/{job_id}/events`** en `b462cf6`. No se recontó el OpenAPI en este relevamiento. El endpoint SSE emite snapshots de `JobStore`, incluyendo `result.stem_names` después de que Demucs termina y antes del mix/master; Demucs devuelve el conjunto de cuatro stems como una sola inferencia, no hay progreso por stem individual. El Studio usa SSE y cae al GET de estado si el stream falla.

**Infraestructura de jobs y sesiones** (sin cambios de fondo):

- `services/job_store.py`: Supabase (`dsp_jobs`) con `probe()` → fallback memoria. Lease+heartbeat; job interrumpido se marca `error`, **no se reanuda** (BackgroundTasks in-proceso). Migración de reparación `20261005180000` añadió `meta`/`lease_expires_at`.
- **Masters durables en R2** (`master_r2_key`, `_persist_master_to_r2()` never-fail, `_resolve_master_file()` con precedencia local→R2). Hueco: paths de cache-hit sin aserción directa (#P10).
- **Sesiones durables** (`session_backend.py`, default `auto`, write-behind con digest; archivo como fallback; un solo proceso). Verificar en prod: backend activo + migraciones (#P9).
- **Estabilidad Demucs**: HTDemucs fp16 horneado (~158 MB), separación en proceso hijo (`demucs_worker.py`), tope de threads 4, timeout 1800 s. `877f768` (26-oct) corrigió el import del módulo demucs que el wheel distribuye — ese fix es parte de lo que puso verde la suite de CI.

**Limpieza y lint**: la deuda de **483 errores de ruff (0 en clases F)** quedó **pagada a 0** (`9579a65`/`96a46bd`, 24-26-oct) — `ruff check .` verificado **"All checks passed!"** hoy con ruff 0.16.10 y ahora es **gate bloqueante en CI**. El saneamiento del `engine.py` del 16-oct (código muerto, `generate_report()`, helper inalcanzable) sigue vigente; quedan stubs dudosos (`measure_correlation → 0.0`) como deuda menor.

> **Cambios de Studio desde el relevamiento previo**: redirects de Auth por `getURL()`, errores de transporte, widget de Brik persistente entre abrir/cerrar y, en `b462cf6`, SSE con fallback, Zustand para chat/stems, shells `100dvh`, `pb-64` desktop y copy crítico de MixPanel en ES/EN.

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

**UI de ChangeReport (Fase C)**: `AgentPanel` renderiza el bloque before/after junto con diagnóstico, herramientas, métricas y audio. La corrida de producción con credencial LLM real sigue pendiente.

- **Mix UI**: `MixPanel` + `MixWaveformAB` + `MixStatusStream`, labels críticos en `useTranslation()` y acción `Masterizar` post-mezcla; el `doneLabel` ya usa `mezcla.jobDone`.
- **Jobs del Productor**: SSE con polling GET de respaldo; mastering/mix mantienen sus pollers con backoff (`useProcessingProgress` y `useMasteringJob`).
- **Voz**: TTS ElevenLabs opcional (tope 400 chars, `204` → `speechSynthesis`), `useVoiceInput`, `lib/voice/decodeAgentText`.
- **i18n**: `useTranslation()` con `es.json`/`en.json` — **934 claves hoja en cada locale, paridad exacta** (4-nov). MixPanel tiene sus labels, hints y tooltips críticos localizados; el botón de navegación conserva `Masterizar`.
- **Estado**: React Context sigue gobernando Auth/I18n/Mastering; Zustand se usa específicamente para historial de chat por sesión (localStorage, hidratación post-mount) y estado transitorio de stems.
- **Tests (4-nov)**: suite vitest 168 pasan / 3 fallan por el mock preexistente de `logTrackEvent.test.ts` (`insert` vs `.upsert()`, igual en `bbe4774`); build exit 0; eslint 0 errores / 41 warnings. En CI, lint y build son gates bloqueantes.

**Arquitectura**: `app/` rutas · `adapters/` (api/audio) · `features/` (mastering, projects, tracks, upload, auth, admin, remastering-history) · `application/hooks/` · `presentation/components/` · `shared/` · `lib/` · `i18n/`. Estado de aplicación por React Context + `useState`; Zustand queda acotado al chat de Brik y stems de jobs de agente. Motion con framer-motion/GSAP; audio cliente con `tone` y `wavesurfer.js`.

### 4.1.1 Mobile y responsive (web — sin app nativa)

**0 nativo/PWA** (no hay manifest ni service worker). `/mezclas` y `/voz` usan shell de `100dvh` con overflow local; `/mezclas` conserva scroll en el canvas y deja espacio bajo el dock. La selección mobile usa `useIsMobile` (breakpoint 768; SSR y primer paint renderizan escritorio → flash conocido, sin script pre-hidratación); landing y headers usan breakpoints Tailwind. Piezas mobile: `MobileMasteringView`, `MobileDrawer`, `MobilePresetStrip`; menú mobile propio de la landing. Siguen `.pt-safe/.pb-safe` y `prefers-reduced-motion`; la comprobación del solapamiento de perfiles requiere un track cargado (#P2).

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

> **Deuda de documentación vigente** (verificada 4-nov):
> 1. `docs/README.md` (índice central) **no menciona** la landing, ni el flujo de proyectos, ni R2, ni el orquestador Cloudflare — describe el pipeline sin nada de esto.
> 2. `docs/reference/specs/` — `01`, `06` y `07` siguen describiendo el Live Engine y HumanMidi; contradicen "dos motores + flujo de proyectos + orquestador".
> 3. `AGENTS.md` (raíz) dice "sesiones del backend en memoria (dict + SessionCache)" — **ya no es verdad** (sesiones durables en Postgres, §3.1), y no menciona el job de backend en CI ni `apps/orchestrator`.
> 4. `docs/runbooks/DEPLOY_RUNBOOK.md`, `apps/orchestrator/README.md`, los `railway.json` y varios comentarios de `apps/audiomind/Dockerfile`/scripts aún describen Railway o el spike como estado operativo; hoy son referencias legacy y no el destino de producción.

---

## 6. Entorno, CI/CD y verificación

### 6.1 CI (`.github/workflows/studio-ci.yml`) — dos jobs bloqueantes

| Job | Qué hace |
|---|---|
| `build` (Studio) | Checkout → Node 22 → bun install `--frozen-lockfile` → `bun run lint` (bloqueante) → `bun run build` |
| `backend` (nuevo, `b9dc5e8` 22-oct) | Checkout → **Python 3.12** (must match `Dockerfile`; lo pinnea `test_runtime_python_contract.py`) → deps de sistema **apt con `--no-install-recommends` + retries + timeout de 15 min + cache de `.debs`** (`350928f`: el mismo paquete tomó 273 s en una corrida y 37.7 min en otra por mirrors trabados) → `pip install -e ".[dev]"` → **`ruff check .` bloqueante** → `python scripts/generate_samples.py` (los samples son gitignored; esto resuelve los 4 fallos de songstarter de un clone limpio **en CI**) → `pytest tests/ -q` con env de demo (`SESSION_TTL 60`, `MAX_CONCURRENT_DSP 1`, Demucs fp16 aislado, etc.) |

Triggers: PRs y push a `develop`/`main` con cambios en `apps/studio/**`, `apps/audiomind/**`, `pyproject.toml`, `requirements*.txt`, raíz de paquetes; además `workflow_dispatch` para correrlo a mano. **Sin gate de e2e ni job de deploy de Cloudflare**; `apps/orchestrator/**` no dispara un publish automático del contenedor.

> El backend pasó de "nada en CI" (hallazgo del 19-oct) a **job completo con gates**. La decisión que queda: supervisar el flake residual de apt (mitigado, no eliminado — las colas del índice no se cachean).

### 6.2 Deploy actual (Railway ya no es el runtime activo)

- **Frontend (Studio + landing)**: Vercel. El cliente usa `NEXT_PUBLIC_API_URL`; `apps/studio/.env.local` apunta al Worker de Cloudflare. El valor efectivo de Vercel y la revisión frontend actualmente publicada no se inspeccionaron en este relevamiento.
- **Backend (AudioMind)**: Cloudflare Worker `waveai-orchestrator` → Cloudflare Container `waveai-orchestrator-dspcontainer`, clase `DSPContainer`, key única `dsp-smoke`, puerto 8000. Último despliegue confirmado el 4-nov: Worker `6de4cd8c-85ce-44e3-9c1f-b21fe4d90d35`, container app versión 3, imagen `sha256:84cd6f7858e3f42f143dfb810aede5cfe4a8d87f07c0564d8396c1e401dd6231`; estado medido tras rollout: 7 healthy, 0 starting.
- **Brecha entre código y runtime**: `waveia/main` está en `b462cf6`; el último container confirmado se desplegó antes de ese commit. Por tanto, el SSE nuevo `/api/jobs/agent/{id}/events` y la publicación temprana de stems requieren un nuevo `npx wrangler deploy` desde `apps/orchestrator`. El usuario indicó que hará ese deploy manualmente; no se ejecutó en este relevamiento.
- **CORS**: el código permite `https://www.brikmusic.online` y `https://brikmusic.online`. En el container v3 se comprobó `GET /api/license/status` con `Access-Control-Allow-Origin` exacto para ambos; preflight `OPTIONS /api/upload` → 200 se comprobó para `www` (4-nov; preflight del apex no medido). El usuario confirmó que `AUDIOMIND_CORS_ORIGINS` no está definida en Cloudflare.
- **Audio**: Cloudflare R2 (originales por presigned PUT, mezclas, masters y `reports/`). **Auth/metadata/jobs/sesiones/proyectos**: Supabase Postgres con fallbacks en algunos stores; las migraciones/tablas de proyecto y el selector de almacenamiento de producción siguen pendientes de verificación (#P5/#P9).
- **Railway**: ya no se usa como destino operativo. Los manifiestos, ejemplos, runbooks y comentarios aún presentes se consideran legacy; el default CORS de `apps/audiomind/config.py` todavía conserva el hostname viejo y puede retirarse en una limpieza puntual (#P20).
- **Migraciones**: `supabase/migrations/` versionadas, sin Alembic (aplicación manual; deuda #P7).

### 6.3 e2e (Playwright)

Sigue en 1 spec:`e2e/tests/demo_flow.spec.ts` (chromium, webServer dev). No ejecutado en este ciclo.

### 6.4 Capacidad operativa

El API productivo corre en Cloudflare Containers Paid (`standard-4`: 4 vCPU, 12 GiB, 20 GB); el container duerme tras 10 min y el Worker enruta al instance key `dsp-smoke`. Railway ya no es parte del dimensionamiento activo. Se mantienen como riesgos operativos las sesiones en memoria por instancia y el hecho de que el spike usa una sola key; revisar la persistencia/sesiones antes de pasar a instancias por job (#P9 y roadmap de §6.5).

### 6.5 Orquestador Cloudflare Containers — Fase 1 desplegada

**Estado**: Worker y container están desplegados en Cloudflare; `apps/orchestrator/` forma parte de la base de trabajo actual. El código mantiene el routing del spike de una sola key `dsp-smoke`; no es todavía una arquitectura multi-container por job. Contenido:

| Archivo | Rol |
|---|---|
| `apps/orchestrator/src/index.ts` | Worker `waveai-orchestrator`: `/__diag` (worker-only, nunca toca el container) + todo lo demás **passthrough** al container `dsp.internal` |
| `apps/orchestrator/src/container.ts` | `DSPContainer` keyed `dsp-smoke` (standard-4: 4 vCPU / 12 GiB / 20 GB, dimensionado con margen sobre el pico RSS de htdemucs y `AUDIOMIND_MAX_CONCURRENT_DSP=1`) |
| `apps/orchestrator/wrangler.jsonc` | Build del Dockerfile de audiomind al managed registry de CF, migration `new_sqlite_classes` (fallback documentado a `new_classes`) |

**Roadmap**: ① Worker + container — desplegado y smokes históricos completados; ② subida/descarga directa browser↔R2 — parcialmente pendiente; ③ Cloudflare Queues y una instancia por job — pendiente; ④ Studio en Workers vía OpenNext — pendiente. El deploy del commit `b462cf6` y sus smokes de SSE son la siguiente acción del usuario.

---

## 7. Pendientes y decisiones del usuario

> Estado al 4-nov. Los pendientes siguientes reflejan el código y las verificaciones conocidas; P3, P5, P8–P18 y P21 conservan notas del relevamiento del 29-oct y no todos se revalidaron en este corte. Railway queda solo como referencia histórica. El trabajo de ayer se integró en `waveia/main` (`b462cf6`).

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| **P1** | **Sincronizar `develop` antes de usarlo**: refs locales indican `develop` 14 commits detrás de `main`. Cambios puntuales parten de `main`; para trabajo amplio, alinear `develop` desde `main`, trabajar allí y luego integrar a `main`. No crear trabajo local-only. | Git | Política definida por el usuario; sincronización aún no hecha |
| **P2** | **Publicar el último código en Cloudflare**: el container v3 activo es anterior a `b462cf6`; falta el `npx wrangler deploy` manual desde `apps/orchestrator`, esperar rollout y verificar SSE + CORS. | Deploy | **Acción del usuario — pendiente** |
| **P3** | **Landing — 3 decisiones de producto**: `--font-sans` sin mapear, controles 27–36 px, precios placeholder (o#37) · deuda de jerarquía h4/h5 en `LandingDSPChain` (o#39, T6–T8 abiertos) | Landing | Decisión del usuario |
| **P4** | `ChangeReport` en `AgentPanel` | Studio | ✅ Implementado; falta una corrida real del Productor IA con credencial LLM para validar el recorrido completo (#P15) |
| **P5** | **Flujo de proyectos en producción**: cargar 4 tablas + env, correr `verify_prod_wiring.py`, probar `/projects/*` end-to-end (o#42) · **UI dormida** de proyectos sin consumidores (o#44, #51) | Deploy/Frontend | Trabajo pendiente |
| **P6** | Revisar el copy no crítico que aún pueda quedar hardcodeado fuera del alcance i18n de `b462cf6`; decidir si exponer `character_seed` en MixPanel (o#52) | Frontend | Deuda técnica / decisión |
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
| **P19** | Receipt-driven development | Proceso | Clone-local OFF verificado el 4-nov; no se usó para la entrega `b462cf6` |
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
- `odd/` — documentos de tareas excluidos de Git. El recuento no se actualizó en este corte; destacados:

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
2. **Análisis** — `analyze_audio` (librosa) produce `AnalysisResult`: LUFS integrado, crest, género, y con el contrato de métricas (Fase A) las **bandas en dBFS reales** (`band_energies_dbfs` por Parseval, piso −120) + `bands_hz` + `loudness_standard="ITU-R BS.1770-4"`. Todo eso queda en la sesión y desde el 27-oct es visible por `GET /api/session/{id}/metrics`.
3. **Elección de preset** — presets del catálogo (o prerender por preset, que pre-computa el master de una variante), con `platform_target` (spotify/apple_music/youtube/tidal/custom: floors UI + recorte de true peak del limiter).
4. **Proceso** — `POST /api/session/{id}/process` ejecuta el **engine** (§3.1, 12 pasos: QC 422 → gain staging → de-esser → match EQ → carácter → smart gate → M/S → mono <120 Hz → soft clip + limiter TP 8× → dither/resample → validación LUFS/DR/fase). Neutral (todo a defaults) = **bypass bit-exacto**. El master resultante se **persiste a R2** fuera del event loop (nunca falla la request) y la sesión guarda `master_r2_key`.
5. **Descarga** — `GET /api/session/{id}/download/{format}` resuelve el archivo con precedencia **local → R2** (`_resolve_master_file`, 4 consumidores centralizados); objeto ausente → 404 nombrando la clave, jamás un fallback silencioso al original.
6. **Detalle de UI** — el Studio consulta progreso de sesión con backoff. Los jobs del Productor IA tienen SSE `GET /api/jobs/agent/{id}/events` con fallback al GET de estado; el runtime Cloudflare debe recibir `b462cf6` para que ese endpoint exista en producción.

**Cadena de referencia externa** (opcional): subir *reference track* y `compare-reference` compara tu master contra ella en la escala FFT-dB interna (`compare_tracks` — la misma que usa el veredicto); es otra cosa que el `ChangeReport` del agente, que mide before/after en dBFS de contrato.

### 9.3 Los dos modelos de trabajo: sync y async

| Modelo | Rutas | Cómo corre |
|---|---|---|
| **Sync (en request)** | `POST /api/session/{id}/process`, `POST /api/session/{id}/mix` | DSP en el ciclo de la request; el pool `DSP_THREAD_POOL` y `max_concurrent_dsp` protegen el container AudioMind |
| **Async (jobs)** | `POST /api/jobs/mix/{id}`, `POST /api/jobs/agent/{session_id}`, jobs de proyecto (`/projects/{id}/jobs/mix|master`) | Registro en `dsp_jobs` (Supabase si está configurado y la tabla pasa probe; si no, memoria), `BackgroundTasks` en proceso, **lease + heartbeat**. Estados reales: `processing → completed | error`; job interrumpido se marca error y **no se reanuda**. El Productor IA puede seguirse por SSE; el resto conserva su mecanismo de estado/polling. |

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
| `presentation/components/` | ~ componentes de UI: dock/tiles de etapas, player, waveforms, mix, chat, landing (21 archivos), mobile |
| `shared/` + `lib/` | `useIsMobile` (768 px), motion (framer-motion + GSAP), `audioContext.ts`, Supabase client, i18n (`useTranslation()`; es/en 934/934 claves, 4-nov) |

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

- **Flujo de cambios acordado por el usuario (4-nov)**: cambios puntuales parten de `main`; si el alcance requiere integración, primero sincronizar `develop` desde `main`, trabajar allí y luego integrar a `main`. Hoy `develop` está 14 commits detrás, así que no usarlo hasta sincronizarlo. No dejar trabajo funcional solo en ramas locales; `waveia` es el remoto canónico y `origin` está stale.
- **Release / CI**: GitHub Actions verifica build Studio + backend pytest/ruff; no hay gate e2e ni deploy automático del container. Push a main no sustituye `npx wrangler deploy`.
- **Nube actual**: Vercel (frontend) · Cloudflare Worker + Containers (AudioMind API) · Cloudflare R2 + Supabase (datos). Railway no se usa. El container activo v3 antecede a `b462cf6`; el usuario hará el deploy de esa versión manualmente.
- **Contratos estables**: `packages/contracts/live_params.schema.json` **dormido** (sólo reactivar si el engine Live vuelve) · `intent_profile.schema.json` · `project_document_v1_spec.md` · el **contrato de métricas** (dBFS/Pisval del medidor BS.1770-4).

---

*Relevamiento actualizado el 2026-11-04 desde `main` (`b462cf6`). Método: estado Git local (sin fetch), revisión de código/configuración Cloudflare y del historial de suites; se incorporó la salida del deploy/smoke test confirmada el 4-nov. No se leyeron secretos ni se consultó el dashboard de Vercel/Supabase. Pendientes explícitos: publicar `b462cf6` en Cloudflare, validar perfiles con un track real y confirmar configuración productiva de Auth/sesiones/migraciones.*
