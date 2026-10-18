# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha de relevamiento**: 2026-09-21 · **Última actualización**: 2026-10-16 (relevamiento completo sobre `develop` @ `95a90c8`: flujo de proyectos multitenant, landing, frontend y mobile, sesiones durables en Postgres, estabilidad Demucs, RAG local y suites medidas en vivo; ver §3.2.1, §3.4, §4.1.1, §4.2, §6.5 y §6.6).
> **Alcance**: repositorio completo — los dos motores vivos (Mastering, Mix), el flujo de proyectos multitenant, landing, Studio, agent de voz/IA, capa de inteligencia, contratos, entorno, ramas y pendientes. El Live Engine se retiró; ver §3.3.
> **Fuentes**: código (`apps/`, `packages/`, `supabase/`, `e2e/`), documentos ODD (`odd/tasks/`), documentación (`docs/`), estado git real y suites de verificación **ejecutadas el 2026-10-16**.

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | ✅ Operativo · cadena DSP proporcional completa · **975 passed, 0 failed** (medido 16-Oct: 206.6 s, 3 warnings) |
| **Motor de Mezcla (Mix Engine)** | ✅ Pasos 01–08 (TDD estricto) + Stem Balance T1–T7 · el defecto del camino async está **corregido y commiteado** (`a3fd00c`) · UI "Mezcla de Audio" cerrada · falta prueba manual en la UI |
| **Flujo de proyectos multitenant ("Moises")** | 🟡 **Backend completo** (WU1–WU5, cerrado 09-Oct) + subida directa a R2 verificada · **UI dormida**: `ProjectContext`/`useProject` y los stores no tienen consumidores · falta cargar tablas y env en producción |
| **Motor en vivo (Live Engine)** | ❌ **Removido del producto** (`ba3b4a6`, 27-Sep). Queda el schema como contrato dormido |
| **Landing page** | ✅ Nueva, en producción (Vercel) — GSAP, i18n completo, A/B demo local, SEO/JSON-LD · 3 decisiones de producto abiertas (§7 #37) · ver §4.2 |
| **Frontend y Mobile (web)** | ✅ Studio + landing con variantes mobile propias (`MobileMasteringView`, `MobileDrawer`, strip de presets, menú mobile de la landing) · **sin app nativa, sin PWA** (0 manifest / 0 service worker) · estado por React Context + `useState` (sin zustand/redux) · ver §4.1 y §4.1.1 |
| **Agent de interpretación (IA)** | 🟡 Compila · `vocal_focus` añadido al contrato (13-Oct) · **llamada real sin probar** (faltan credenciales) |
| **Productor IA (bucle agéntico, Python)** | 🟡 Bucle de 4 fases + tool calling + transporte model-agnostic · disparable por HTTP en `POST /api/jobs/agent/{session_id}` (polling `GET /api/jobs/agent/{id}`) · **corrida real sin probar** (falta credencial LLM válida) |
| **Capa de inteligencia (RAG)** | 🟡 Implementada como **CLI local** sobre los libros de mezcla (OCR, chunks, búsqueda híbrida BM25+vector RRF, Ollama) · expuesta por `POST /api/agent/rag/search` (rama `feat/agentic-mix-loop`) · el bucle agéntico todavía **no la consume** |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | ❌ **Eliminado** — el scaffold `convex/` ya no existe (0 archivos trackeados, 0 deps, 0 referencias). El job `deploy-convex` de la CI también fue removido (`3d9f8ae`) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** del repositorio |
| **Deploy (Vercel + Railway + R2 + Supabase)** | 🚀 **Ejecutado y verificado** (02-Oct), con trabajo posterior: originales subidos a R2 por presigned URL (14-Oct). Ver §6.6 |
| **Sesiones del backend** | ✅ **Durables en Postgres** (`sessions`, backend `auto`) con fallback a archivo — reemplaza el "dict en memoria + espejo best-effort" de la versión anterior de este documento |
| **Suites de verificación (16-Oct)** | Backend **975 passed / 0 failed** (206 s) → **977 passed / 0 failed** tras el saneamiento · Studio vitest **11 archivos / 126 tests** · eslint **0 errores / 37 warnings** · build Next **✓ Compiled successfully (exit 0)** · ruff backend **524 → 483** (clases `F401`/`F811`/`F821` en 0, **sin gate en CI**: §7 #34) · e2e no ejecutado |

---

## 2. Estado del repositorio (git)

### 2.1 Rama actual y remotes

- **Rama actual**: `develop` @ `95a90c8` (14-Oct), **trackea `brik/develop`** y está **sincronizada (0 ahead / 0 behind)**. Working tree **limpio** (0 cambios sin commitear).
- **`main`** @ `927a090` (06-Oct, *release: sync develop into main*), trackea `brik/main`, sincronizada.
- **Remotes** (se sumaron `brik` y `masive` respecto de la versión anterior de este documento):

| Remote | URL |
|---|---|
| `brik` / `masive` | `https://github.com/Masive-porjects/Brik.git` |
| `origin` | `https://github.com/brikpaul569-cmd/BrikMaster2027.git` |
| `team` / `waveia` | `https://github.com/Masive-porjects/WaveIA.git` |

- **Working tree**: limpio en lo versionado. Siguen **excluidas localmente** (`.git/info/exclude`, no en git): `odd/`, `.atl/`, `docs/proposals/`, `docs/postmortems/`.

> ⚠️ **Aviso de medición**: los refs de `team/dev` (tip 2026-09-25) y `origin/main` (tip 2026-09-07) están **stale** (no hubo `fetch` en este relevamiento). Contra esos refs, `develop` aparece 123 commits adelante y `main` 237 — números **no fiables** hasta hacer `git fetch`. Lo que sí es fiable: `develop` == `brik/develop` y `main` == `brik/main` por igualdad de refs.

### 2.2 Ramas locales relevantes

| Rama | Tip | Estado |
|---|---|---|
| `develop` | `95a90c8` | En sync con `brik/develop` |
| `main` | `927a090` | En sync con `brik/main` (release del 06-Oct) |
| `feature/moises-architecture-migration` | `8efe2a2` | **Absorbida por `develop`** (`95a90c8` merge R2-native project flow) |
| `chore/landing-visual-cleanup` | `8c8cd72` | Absorbida por `develop` |
| `fix/backend-suite-green-docs-sync` | `f3d3085` | Absorbida por `develop` |
| `feat/ia-asistente-mezcla` | `43cafe9` | Absorbida por `develop` (`cb7b267`) |
| `fix/studio-three-bugs` | `371afb3` | Absorbida por `develop` (`9169143`) |
| `feat/mix-async-infra` | `6ac10b5` | **Sin merge explícito en el historial de `develop`** — verificar si es trabajo descartado o superseded |
| `feat/landing-gsap-microinteractions` | `ff8758b` | **Sin merge explícito** — ídem |
| `feature/remove-deprecated-modules` | `f293c73` | Absorbida por `develop` |
| `feat/mix-engine/01…08` | — | Ramas históricas del Mix Engine, locales |

### 2.3 Historial reciente (develop, 14 últimos)

```
95a90c8 2026-10-14 feat(architecture): merge moises R2-native project flow into develop
8efe2a2 2026-10-14 fix(audiomind): raise original_filename limit to 1024 (A5)
c2862ca 2026-10-14 feat(studio): upload originals to R2 via presigned URLs
654079e 2026-10-14 feat(studio): add project asset API client for direct-to-R2 upload
03c4388 2026-10-14 feat(audiomind): add presigned asset download endpoint
8c8cd72 2026-10-14 feat(landing): theme-aware colors, SEO metadata and structured data
f3d3085 2026-10-14 perf(frontend): add exponential backoff to polling hooks (useProcessingProgress, useMasteringJob)
2aa40b6 2026-10-14 chore(mix_engine): restore correct version from develop (LF + UTF-8, fix EOL churn)
001cc26 2026-10-13 docs: purge phantom HUMANMIDI_REMOVAL_REPORT references and stale engine claims
34651bb 2026-10-13 docs: correct false auth claims, dead archive links, and specs/08 staleness
ae4a202 2026-10-13 docs: sync documentation with verified project state
4e95f50 2026-10-13 fix(audiomind): add vocal_focus axis to IntentProfile to match contract schema
256027e 2026-10-09 fix(studio): sync latest-ref callbacks in an effect, not during render
24145a6 2026-10-09 feat(landing): ship real footer links and next/image assets
```

> Entre el 02-Oct (última verificación real del documento) y el 16-Oct hay **73 commits** en `develop`. Los bloques temáticos fueron: landing (04→14-Oct), estabilidad DSP/Demucs (05-Oct), sesiones durables + R2 (02-Oct), RAG local (05-Oct), flujo multitenant (08→14-Oct) y sync de documentación (13-Oct).

---

## 3. Los motores

### 3.1 Motor 1 — Mastering (AudioMind, backend FastAPI)

**Ubicación**: `apps/audiomind/src/audiomind/` · Python 3.11+ · FastAPI, librosa, pedalboard, numpy, demucs-onnx.

**Módulos**: `analysis`, `api`, `intelligence`, `models`, `processing`, `services`, `storage`.

**Pipeline del engine** (`processing/engine.py`, **1 640 líneas totales**): cadena **proporcional y dinámica** (no presets fijos):

1. **QC de entrada** (`strict_mode`) → rechaza HTTP 422 si clipping duro o true peak ≥ −0.3 dBTP (InputQcError).
2. **Gain staging** a −6 dBFS.
3. **De-esser dinámico** 3–8 kHz (neutral = bit-exacto).
4. **Match EQ por género** contra `TARGET_BANDS_HZ` [60,150,400,1000,2500,6000,10000,15000].
5. **Cadena de carácter** del preset (low/high shelf, peaking, exciter, imagen estéreo).
6. **Smart gate** (`smart_gate.py`): si la entrada ya cumple objetivos, omite corrección tonal (tier `full`/`conservative` — nunca gatea módulos de firma).
7. **Bloque M/S**: side HPF <100 Hz (off por defecto), reverb solo en el canal side (mono-safe).
8. **Colapso mono** <120 Hz al centro.
9. **Soft clipper** 16× (knee erf) → **limiter true-peak** 8× con lookahead.
10. **Dither** TPDF + noise shaping Lipshitz 2º (16-bit) · resample libsoxr VHQ.
11. **Validación final**: LUFS, DR (LRA), correlación/phase del crest.

**Revisión contra práctica profesional** (`docs/reference/DSP_INDUSTRY_REVIEW.md`): 17 recomendaciones — 16 cumplen, 1 parcial (preservar carácter tonal; diseño aceptado).

**Compliance Phase 1** (`docs/reference/COMPLIANCE_PHASE1.md`): `processing_mode: transparent` = passthrough bit-exacto; `platform_target` (spotify −14/−1.0, apple_music −16/−1.0, youtube, tidal, custom); `output_sr`/`output_bit_depth`; `strict_mode` 422.

**Features adicionales**: demo mode (pool gated + TTL + janitor + `/api/demo/stats`), prerender por preset, referencia externa (upload + `compare-reference`), álbum (`negotiate` + `process`), splitter Demucs, SongStarter/Beats, `LicenseGuard`.

**Endpoints — inventario corregido (16-Oct)**: **59 rutas** = 57 decoradores en 10 routers (`api/`: `auth`, `batch`, `jobs`, `license`, `mastering`, `mix`, `projects`, `songstarter`, `splitter`, `upload`) + 2 rutas de app (`/health`, `/api/demo/stats`). Reparto: mastering 17, **projects 15**, songstarter 7, jobs 6, upload 3, splitter 3, mix 2, license 2, batch 2.

> ⚠️ **Correcciones respecto de la versión anterior de este documento**: (a) ya **no existe `api/vocal.py`** — la "Vocal chain" se removió (`remove-educational-panels-and-vocal-chain.md`, 28-Sep), así que el conteo de 38 endpoints y las entradas "vocal (2)" estaban stale; (b) existían **rutas duplicadas**: `POST /api/session/new` estaba registrada en `upload.py` **y** en `mastering.py`, igual que `GET /api/session/{id}` — FastAPI emitía `Duplicate Operation ID` al construir el OpenAPI · **corregido el 16-Oct** (`3f5c758`), ver §7 #36.

**Tests**: `apps/audiomind/tests/` — **58 archivos `test_*.py`** (61 `.py` contando `conftest.py`, `__init__.py`, `create_test_wav.py`) · suite **975 passed, 0 failed** (medida 16-Oct).

#### 3.1.1 Estado de jobs: `JobStore` compartido (30-Sep)

El estado de los jobs async ya no vive en un dict del proceso: `services/job_store.py` guarda en Supabase (tabla `dsp_jobs`) si está disponible, y en memoria si no. El endpoint **registra antes de encolar**; el worker sólo actualiza. Lease con heartbeat → un worker muerto se lee `error`, no `processing` para siempre. `GET /api/jobs/master/{id}` conserva el shape legacy.

`SupabaseJobStore.probe()` hace un `SELECT ... LIMIT 1` al elegir store y cae a memoria con warning si la tabla no existe o la key está revocada.

**Limitación honesta**: un job interrumpido se marca `error` ("interrupted"), **no se reanuda** (`BackgroundTasks` sigue siendo en-proceso). Ver §7 #19.

**Drift de esquema corregido (05-Oct)**: la migración `20261005180000_repair_job_and_session_schema.sql` añade a `dsp_jobs` las columnas `meta` y `lease_expires_at`. Antes faltaban y el insert fallaba silenciosamente → primer poll 404.

#### 3.1.2 Persistencia de los MASTERS en R2 (#30, 02-Oct, ya commiteado)

- Estado durable: `SessionData.master_r2_key` y `PresetMasterEntry.r2_key`.
- Escritura: `_persist_master_to_r2()` sube el WAV fuera del event loop y **nunca falla la request** (el master ya existe en disco; R2 es el seguro contra el redeploy).
- Lectura: `_resolve_master_file()` centraliza los 4 consumidores con precedencia local → R2 (`{sid}_{preset}_mastered_from_r2.wav`). Objeto vacío o descarga fallida → **404 nombrando la clave**.
- Cobertura: **6 rutas productoras** y **4 consumidoras**; `api/batch.py` tiene su helper propio.
- Tests: `tests/test_master_r2_durability.py` (15) en 5 clases.

**Hueco de cobertura honesto**: los paths de *cache hit* (preset prebuilt y prerender) están cableados pero **sin aserción directa** (ver §7 #46).

#### 3.1.3 Sesiones durables en Postgres (02-Oct, `e64d093` — reemplaza la advertencia anterior)

La versión previa de este documento decía "sesiones en memoria (`session_store`) — se pierden al reiniciar salvo espejo best-effort a `uploads/sessions.json`". **Eso ya no describe el sistema**:

- `services/session_backend.py` define `FileSessionBackend` y `SupabaseSessionBackend` (tabla `sessions`), con `get_session_backend()` eligiendo por `settings.session_store_backend` (**default `auto`**).
- El dict en memoria sigue siendo la fuente de lectura; la escritura es *write-behind* con digest por sesión hacia Postgres, y el archivo (`uploads/sessions.json`) queda como **fallback**.
- Distinción deliberada: `load_all()` devuelve `None` ("ilegible") vs `{}` ("vacío") para no podar estado ante un error de lectura.
- **Invariante documentada**: un solo proceso (el backend no soporta múltiples workers contra el mismo store).
- Migraciones: `20261002230400_create_sessions.sql` (que hizo **no-op silencioso** por una tabla `sessions` preexistente con otra forma) + reparación en `20261005180000_repair_job_and_session_schema.sql`.

> ⚠️ **No verificado en este relevamiento**: si `AUDIOMIND_SESSION_STORE_BACKEND` está en `auto` en producción y si la migración de reparación fue aplicada allí. Sin eso, el fallback a archivo sigue siendo el camino real en prod (ver §7 #47).

#### 3.1.4 Estabilidad / OOM: Demucs aislado (05-Oct)

El contenedor free tier ya había registrado OOM (#16). Se aplicaron cuatro cambios concretos:

| Cambio | Evidencia |
|---|---|
| Pesos **HTDemucs fp16** horneados en la imagen (~158 MiB vs ~302 MiB) | `config.py` (`demucs_precision = "fp16weights"`), commit `0496a48` |
| Separación **aislada en proceso hijo** para no envenenar el contenedor | `processing/demucs_worker.py` + `processing/splitter.py`, commit `dca53cb` |
| **Tope de threads hijos** (`demucs_threads = 4`) | commit `6121704` |
| Timeout de separación a **1800 s** | `config.py`, commit `cbdf356` |

También se reparó `masters.status`, columna faltante que **bloqueaba la persistencia del master** (`20261005220000_add_masters_status_column.sql`).

#### 3.1.5 Higiene de código: deuda de lint y código muerto en `engine.py` (hallazgo nuevo, 16-Oct)

`ruff check` en `apps/audiomind` reportaba **524 errores**. **Saneado el 16-Oct** (`079d38a`, `211b9fb`): quedan **483** — se corrigieron las 35 de las clases `F401` (23), `F811` (7) y `F821` (5), más 6 de `E402` (imports eliminados de `engine.py`). Desglose actual: 331 `E501`, 69 `I001`, 37 `E402`, 14 `F841`, 11 `B904`, 3 `B008`, 3 `B007`, 3 `B905`, 2 `E741`, 2 `UP017`, 2 `UP045`, 2 `UP042`, 1 `F541`, 1 `E401`, 1 `E701`, 1 `N806`. No es un artefacto de CRLF: las líneas medidas tienen 89 caracteres reales.

El caso material era `processing/engine.py`:

- `generate_report()` (líneas 1573–1600) **no se llamaba desde ningún archivo** (0 referencias en `src/` y `tests/`), referenciaba un nombre **indefinido** (`target_dbtp`, F821 — es un parámetro de `validation_loop`, no un global) y comparaba contra el **objeto función** `target_lufs` en lugar de un valor numérico.
- Después de su `return report` (línea 1600) quedó **código inalcanzable**: el docstring y el cuerpo de un helper de gain-match huérfano (líneas 1601–1613), que es el origen de `reference`/`processed` veces indefinidas.

**Resuelto el 16-Oct** (`079d38a`): se eliminó el bloque completo (banner, `import json`, `generate_report()` y el helper inalcanzable) más los imports duplicados (`numpy` ×2, `true_peak_limit`, `true_peak_db`) y el `measure_true_peak` sin usar. `engine.py` queda con **0 errores `F`**, `−56` líneas netas y **cero** cambios de lógica — verificado por AST: ninguna sentencia ejecutable después de un `return`, y la superficie pública intacta (pinneada en `tests/test_cleanup_invariants.py`). Quedan los stubs dudosos (`measure_correlation` → `0.0`), fuera de este saneamiento: §7 #35.

### 3.2 Motor 2 — Mix Engine (mezcla IA+DSP)

**Ubicación**: `apps/audiomind/src/audiomind/processing/` (`mix_engine.py` + módulos) · API en `api/mix.py`.

**Pasos 01–08 implementados en TDD estricto** + **Stem Balance T1–T7** (faders ±6 dB, auto-balance por género con default OFF, `balance_report`, API y Studio, E2E de neutralidad). Queda sólo el **A/B auditivo** con la sesión hip_hop del productor (requiere su WAV, que no está en el repo).

**Pipeline final por stem**: `split Demucs (4 stems) → pan por rol → EQ mágico → compresor por stem → dimensión (sends) → suma al bus → compresor de bus → QC → render de 5 versiones → modo creativo`.

- **Neutralidad**: perfiles `{}` = routing exacto del paso previo; `creativity=0` → principal byte-idéntico con/sin bloque creativo. La suma 1:1 no es bit-exacta al original (Demucs es lossy — pitfall aceptado).
- **QC** (`quality_checks.py`): mono/fase, sibilancia 4–7 kHz, muddy 200–300 Hz, honky 450–600 Hz — informativos, **nunca bloquean**.
- **Versiones** (`render_versions.py`): principal 0 dB, vocal ±0.75 dB, instrumental, TV mix.
- **Creativo** (`creative.py`): espacio continuo 0..1, semilla reproducible, rejection sampling contra QC.
- **EOL churn resuelto (14-Oct)**: `2776bd1` + `2aa40b6` normalizan `mix_engine.py` a LF/UTF-8 y restauran la versión correcta (era el pendiente #3 de la versión anterior).
- **Dependencia abierta**: `build_mix()` **re-separa desde el original** en cada corrida; el reuso de stems ya separados quedó como follow-up (§7 #43).

**API**: `POST /api/session/{id}/mix` (WAV + `X-Mix-Result`) · `GET /api/session/{id}/audio/mix` (WAV persistido).

### 3.2.1 ✅ Defecto corregido y **commiteado**: el camino async de mezcla no registraba la mezcla en la sesión

> **Estado**: corregido el 02-Oct y **ya en git** (`a3fd00c` *fix(audiomind): persistir mezclas y masters en R2 con rehidratación*). La versión anterior de este documento lo describía como "sin commit": eso ya no aplica.

Síntoma en producción: el job de mezcla terminaba `completed` al 100 %, pero el gate del frontend respondía *"Termina tu mezcla antes de masterizar."*

**Causa raíz** — asimetría entre los dos caminos: el síncrono escribía `mix_path`/`mix_metadata`/`mix_analysis`/`mix_status` en la sesión; el async (`services/mix_jobs.py`) sólo actualizaba la fila de `dsp_jobs` y **borraba `mix_path` del payload a propósito** (path local efímero en Railway).

**Consecuencias verificadas entonces**: (1) gate trabado; (2) `GET /api/session/{id}/audio/mix` → 404; (3) **fallo silencioso grave**: `api/mastering.py` caía a `source="original"` y masterizaba el **original** en vez de la mezcla; (4) sin endpoint para corregir el estado a mano.

**Fix aplicado**: `SessionData.mix_r2_key`; `_record_mix_on_session()` (escribe sólo si el path local existe → en Railway persiste la clave R2, nunca un path muerto); `_mark_mix_failed()`; `_hydrate_mix_from_r2()`; `_mix_is_deliverable()`; escritura **atómica** de `sessions.json` (`tmp` + `Path.replace()` bajo lock).

**Decisión de diseño deliberada**: si la resolución inteligente ya eligió un mix entregable y la descarga desde R2 falla, el endpoint devuelve **400, no el original** — reintroducir el fallback silencioso sería reintroducir el bug. Cubierto por `test_unreachable_r2_refuses_instead_of_silently_mastering_the_original`.

### 3.3 Motor 3 — Live Engine — REMOVIDO (27-Sep, `ba3b4a6`)

Sigue vigente lo documentado antes: el tab sólo renderizaba un `ComingSoonNotice`, `LiveView` no tenía importadores y nunca existió una ruta `/live`. Los 17 archivos del cluster se importaban entre sí.

**Sobrevive**: `packages/contracts/live_params.schema.json` (contrato **dormido**, 9 campos) + `liveParams.gen.ts`, y `safeCloseAudioContext` movido a `apps/studio/src/lib/audioContext.ts` (lo usa `useStereoField.ts`).

**Eliminado**: `LiveView`, `FxSlotPanel`, `Knob3D`, `LiveMeterDeck`, `LiveRecorderBar`, `PresetHeader`, `useLiveEngine`, `audioGraph`, `fxPresets`, `impulseResponse`, `recorder`, `meterMath`, `liveMeterBus`, `liveDefaults`, el `simulator/Dockerfile` huérfano y las entradas `live` de los docks/features.

**WaveAI queda con dos motores: Mastering y Mix** (más el flujo de proyectos, que es orquestación, no un motor DSP).

### 3.4 Flujo de proyectos multitenant ("Moises") — NUEVO (08→14-Oct)

Migración desde sesiones anónimas en memoria a un modelo **por usuario** con "project document", más almacenamiento **R2-native** de los originales. Backend **completo**; la UI del Studio está **dormida**.

**Superficie HTTP**: `api/projects.py`, prefijo `/projects` (**15 rutas**), con docstring de endpoints (`projects.py:6-18`). Incluye CRUD de proyectos, assets (presign, patch, list, download), estado (`project_states`), documento V1 (`project_documents`, con OCC) y los tres jobs de proyecto (separate/mix/master).

**Auth y aislamiento**: `api/auth.py::get_user_context` valida el access token de Supabase desde `Authorization: Bearer` y escribe con un cliente scoped al token → **RLS** (`auth.uid() = user_id`) aplica en Postgres. En dev/test hay una identidad de fallback (`DEV_USER_ID`).

**Modelo de datos** (`supabase/migrations/`, 4 tablas nuevas):

| Migración | Tablas / cambios |
|---|---|
| `20261008120000_create_project_document.sql` | `projects`, `audio_assets`, `project_states` (+ RLS) |
| `20261008140000_create_project_documents.sql` | `project_documents` (V1 + OCC) |

**Servicios nuevos**: `compile_project.py` (`load_inputs`, `compile`), `project_jobs.py` (mix/master de proyecto), `separate_jobs.py` (separación **idempotente por `media_hash`**). El estado de los jobs de proyecto reutiliza `dsp_jobs` vía su `meta` jsonb.

**Almacenamiento R2-native**: presigned **PUT** de 900 s (`_PRESIGN_EXPIRES_SECONDS`) y presigned **GET** de 3600 s (`_DOWNLOAD_EXPIRES_SECONDS`). En Studio, la subida del original en `/upload` usa presign → PUT → PATCH y devuelve un path con prefijo `r2:`, **sin tocar** `tracks`/biblioteca/player (flujo híbrido, verificado por un verificador independiente: S1–S9 MET, cero blockers).

**Estado de la UI (honesto)**: existen `features/projects/` (`ProjectContext` con `useProject()`, `store/projectDocumentStore.ts`, `store/mixStateStore.ts`, `audioEngine.ts`) pero **ningún archivo fuera de esa carpeta los consume** → no hay vista de proyectos ni listado/detalle. Lo único vivo del flujo en la UI es la subida directa a R2 desde el workflow de mastering.

**Pendiente de producción**: cargar las 4 tablas nuevas + env vars en producción, correr `apps/audiomind/scripts/verify_prod_wiring.py` y probar `/projects/*` end-to-end (§7 #42).

**Especificación**: `docs/reference/specs/project_document_v1_spec.md`.

### 3.5 Capa de inteligencia: RAG local sobre los libros de mezcla (05-Oct) — NUEVO

**Ubicación**: `apps/audiomind/src/audiomind/intelligence/rag/` (13 módulos: `books`, `extract`, `clean`, `chapters`, `chunk`, `embed`, `index`, `evaluate`, `config`, `__main__`).

- Ingesta con **OCR** para los PDF de `docs/proposals/` (local-only), chunking por capítulo y limpieza.
- Recuperación **híbrida BM25 + vectores fusionados por RRF** (`SearchMode = bm25 | vector | hybrid`).
- Embeddings vía **Ollama** local (`http://localhost:11434` por defecto); dependencias pesadas en un extra opcional (`rag`).
- **CLI + endpoint de lectura**: `python -m audiomind.intelligence.rag <comando>` y `POST /api/agent/rag/search` (sólo consulta: degrada a BM25 y lo declara en `mode_used`). El bucle agéntico **no** lo consume todavía — `run()` no recibe un `RAGQuery` desde la API, así que la herramienta `search_knowledge` no se le ofrece al modelo. Tests: `tests/test_rag_pipeline.py`.
- Además, `intelligence/` contiene los **schemas de conocimiento** (genre/preset/experiment/plugin/idea) y plantillas Markdown, que hoy son scaffolding sin consumidores.

---

## 4. Studio — frontend y aplicaciones acompañantes

### 4.1 Studio (Next.js 16 + React 19 + TS + Tailwind 4)

**Rutas reales** (manifest del build, 16-Oct): `/` (landing), `/mezclas` (estudio), `/upload`, `/lab`, `/login`, `/register`, `/admin`, `/voz`, `/voz/chat`, `/voz/speak`, `/voz/escuchar`, `/auth/callback`, `robots.txt`, `sitemap.xml`.

**Tabs de `/mezclas` — inventario corregido (7, no 10)**: `Mezcla de Audio` · `Masterizar Audio` · `Splitter` · `Beats` · `Análisis` · `Estéreo` · `Álbum`.

> **Corrección**: "Vocal", "Guía de Géneros" y "Cadena de Master" **ya no son tabs** (remoción de paneles educativos + vocal chain, 28-Sep). La versión anterior de este documento los listaba.

- **Mix UI**: `MixPanel` + `MixWaveformAB` + `MixStatusStream`, con acción "masterize" post-mezcla.
- **Polling con backoff exponencial (14-Oct)**: `useProcessingProgress` (base 500 ms) y `useMasteringJob` (base 2500 ms), con reset al progresar y backoff ante error.
- **Chat/agente**: `ChatPanel` → `/voz/chat` → `interpretIntent` → perfil → preset cards.
- **Voz**: `/voz/speak` (TTS ElevenLabs opcional, cache `.tts-cache`, tope 400 chars, `204` = fallback a `speechSynthesis`) · `/voz/escuchar` + `useVoiceInput` · `lib/voice/decodeAgentText`.
- **i18n**: hook `useTranslation()` con `apps/studio/src/i18n/locales/es.json` + `en.json` — **765 claves hoja cada uno, paridad exacta** (recuento recursivo verificado el 16-Oct). Sin microcopy hardcodeado en la UI nueva.
- **Tests**: vitest **11 archivos / 126 tests passed** · eslint **0 errores / 37 warnings** · build de producción **✓ Compiled successfully, exit 0**.
- **Tabs/file de estado de mezcla**: `MixStatusStream` todavía tiene un `doneLabel` por defecto en español hardcodeado (deuda #24).

**Arquitectura del frontend** (capas y responsabilidades):

| Capa | Rol | Contenido |
|---|---|---|
| `app/` | Rutas (Next App Router) | `page.tsx` (landing), `mezclas/`, `upload/`, `lab/`, `login/`, `register/`, `admin/`, `voz/*`, `auth/callback/`, `layout.tsx`, `globals.css`, `sitemap`/`robots` |
| `adapters/` | HTTP y audio | `api/` (`client.ts`, `album.ts`, `config.ts`) · `audio/` (`AudioProcessor.ts`, `engine.ts`) |
| `features/` | 7 módulos, cada uno con barrel | `mastering`, `projects`, `tracks`, `upload`, `auth`, `admin`, `remastering-history` |
| `application/hooks/` | Hooks de aplicación | `useAudioProcessor`, `useFocusMode`, `useStereoField` (análisis Web Audio de sólo lectura) |
| `presentation/components/` | 42 archivos en la raíz + subdirs | `dock/` (7: ModuleDock, tiles), `audio/` (7), `chat/` (4), `landing/` (21), `ui/` (2), MixPanel, reproductores |
| `shared/` | Base compartida | `motion.ts`, `useIsMobile.ts`, `useCrossfade.ts`, `config/`, `lib/animations.ts`, `types/` |
| `lib/` | Utilidades y clientes | `api.ts`, `audioUtils.ts`, `audioContext.ts`, `mastering-stages.ts`, `supabase/`, `voice/` |
| `i18n/` | Traducciones | `I18nContext.tsx`, `useTranslation.ts`, `locales/es.json`, `locales/en.json` |

- **Estado**: no hay zustand/redux/jotai ni `useReducer` (0 dependencias de ese tipo). El patrón es **React Context** —`I18nProvider` → `AuthProvider` → `MasteringProvider` en `layout.tsx`— más `useState` local; los stores viven en `features/*/context/` y `features/projects/store/`.
- **Motion**: `framer-motion` 12 (declarativo) en todo el producto + **GSAP 3.15 / @gsap/react** imperativo donde hace falta (escala del player en `mezclas/page.tsx`, `useHeroGSAP`, `useTaglineReveal`). Presets compartidos en `shared/motion.ts` (`fadeUp`, `VIEW_TRANSITION`) y `shared/lib/animations.ts`.
- **Estilo**: Tailwind 4 + tokens en `app/globals.css` (`--bg-app` #0b0b0c, `--bg-glass*`, `--surface-*`, `--border*`, `--text-primary/-secondary/-muted`, `--accent-primary` #627e84, `--accent-secondary` #829ca1, `--shadow-*`), con overrides `[data-theme="light"]`.
- **Audio en cliente**: `tone` 15 (secuenciadores) y `wavesurfer.js` 7 (waveforms), más `AudioProcessor`/`engine` propios en `adapters/audio/`.

**Inventario de componentes principales** (`presentation/components/`, 42 archivos en la raíz + 5 subdirectorios):

| Grupo | Componentes |
|---|---|
| Flujo de mastering | `DropZone`, `PresetSelector`, `PresetTooltip`, `PlatformSelector`, `ModuleDock`, `ModulePanel`, `ModuleSheet`, `PaintedModule`, `Player`, `ProcessingOverlay`, `MasteringReportCard`, `FloatingReportCard`, `FloatingDeliveryPanel`, `DeliveryPanel`, `OverMasterWarning`, `MixGateNotice`, `ErrorModal`, `WelcomeGate`, `LicenseGuard` |
| Mezcla | `MixPanel`, `MixWaveformAB`, `MixStatusStream`, `mixI18n.ts` |
| Análisis y visualización | `AnalysisPanel`, `AudioSpectrum`, `StereoField`, `TrackChip`, `AlbumMastering` |
| Secuenciadores (Beats) | `SongStarter` + `audio/`: `GrooveSequencer`, `InteractiveSequencer`, `StepGrid`, `useSequencerEngine`, `genrePresets` |
| Splitter | `StemSplitter` |
| Chat y voz | `chat/`: `ChatPanel`, `MicButton`, `PresetCards`, `TrackBadge` |
| Identidad de marca | `BigGhostWithNotes`, `FloatingGhosts`, `FloatingNotes`, `AmbientLayer`, `WavePodTeaser`, `ShareCard`, `ComingSoonNotice` |
| Shell / UI base | `ui/`: `IconButton`, `Pagination` · `LanguageSwitcher`, `ThemeToggle`, `MobileDrawer`, `MobilePresetStrip` (estos dos últimos, mobile: ver §4.1.1) |

### 4.1.1 Mobile y responsive (web — **no hay app nativa**)

**No existe target nativo**: 0 coincidencias de `react-native`, `expo`, `capacitor`, `next-pwa`, `workbox`, `manifest` o `serviceWorker`, y no hay `public/manifest` ni service worker. Todo lo "mobile" es **web responsive**.

**Mecanismo de decisión** — conviven dos estrategias:

| Zona | Mecanismo | Evidencia |
|---|---|---|
| `/mezclas` (estudio) | **Render condicional por JS** con el hook `useIsMobile` | `shared/useIsMobile.ts` (`MOBILE_BREAKPOINT = 768`, `matchMedia('(max-width: 767px)')`, listener de `change`); consumido en `app/mezclas/page.tsx` |
| Landing y headers | **Breakpoints Tailwind** (`sm:`, `lg:`) | `LandingNavigation` (`hidden lg:flex` / `lg:hidden`), `HeroGSAP` (`hidden lg:block`), `LandingHeader` (`hidden sm:flex`), `MasteringHeader` (chips `sm:`/`md:` + hamburguesa `lg:hidden`) |

> ⚠️ **Caveat conocido**: `useIsMobile` arranca en `useState(false)`, así que el SSR y el **primer paint renderizan la variante de escritorio** y recién tras la hidratación cambia a mobile. No hay script pre-hidratación de `matchMedia` (sólo los de tema y `--vh`), así que el flash existe.

**Piezas mobile vivas**:

- **`features/mastering/components/MobileMasteringView.tsx`** — workspace mobile de mastering: `Player` arriba (oculto sólo en el tab `mezcla`), `MobilePresetStrip`, botón "Procesar" a ancho completo, descargas WAV/MP3, grilla de análisis compacta de 3 columnas y "← Volver al flujo principal" flotante. Se elige en `mezclas/page.tsx` (`isMobile ? <MobileMasteringView/> : <vista escritorio>`); en mobile se oculta `AnalysisSidebar` y el escritorio usa `ModuleDock` + `PaintedModule`.
- **`presentation/components/MobileDrawer.tsx`** — panel deslizante **izquierdo** del estudio (`w-72 max-w-[85vw]`, z-130/140) con chip de sesión (LUFS / flag de masterizado), `LanguageSwitcher`, `ThemeToggle` y "Subir nuevo track" (`min-h-[44px]`); cierra con ESC. Lo abre el hamburger de `MasteringHeader`.
- **`presentation/components/MobilePresetStrip.tsx`** — carrusel horizontal de 8 presets con `snap-x` y `WebkitOverflowScrolling: touch`.
- **Menú mobile de la landing** — vive **dentro de la landing, no en `shared/`**: `LandingNavigation.tsx` define `MobileMenuContext` / `useMobileMenu`, `MobileMenuButton` (`lg:hidden min-w-[44px]`) y su propio drawer (desliza **desde la derecha**, z-100, con bloqueo de scroll del body y focus trap). Es una pieza **distinta** del `MobileDrawer` del estudio.
- `shared/useIsMobile.ts` se re-exporta desde `shared/hooks/`.

**Viewport y áreas seguras**:

- `app/layout.tsx` declara `export const viewport` con `width=device-width`, `initialScale: 1`, `maximumScale: 1`, `viewportFit: "cover"` y `themeColor: "#0b0b0c"`.
- `globals.css`: `.h-dvh` (100dvh con fallback `--vh` vía `@supports`) y utilidades `.pt-safe` / `.pb-safe` / `.pl-safe` / `.pr-safe` basadas en `env(safe-area-inset-*)`; `.scrollbar-hide` para scroll horizontal limpio.
- No hay `touch-action` global en CSS: se aplica por componente con utilidades Tailwind (`touch-none`).

**Accesibilidad táctil y motion**:

- Objetivos táctiles de 44 px en las piezas nuevas: `MobileDrawer`, `MobileMenuButton`, controles del A/B player y botones de cierre de la landing.
- `focus-visible` global en `globals.css` + anillos por componente.
- `prefers-reduced-motion`: guarda global en `globals.css` y respeto explícito en los componentes de motion, incluidos `useHeroGSAP`/`useTaglineReveal` vía `gsap.matchMedia` y `useReducedMotion` de framer.
- Deuda asociada: controles de 27–36 px que no llegan a 44 px (§7 #37) y la jerarquía tipográfica de `LandingDSPChain` (§7 #39).

### 4.2 Landing page — NUEVA (04→14-Oct), en producción

- **Es la ruta raíz**: `app/page.tsx` renderiza `LandingScreen` y además inyecta JSON-LD `FAQPage` construido desde `es.json` (`landing.faq`). `alternates.canonical: "/"`.
- **Tamaño real de la carpeta**: **18 componentes `.tsx`** + `data.ts`, `types.ts` e `index.ts` = 21 archivos en `presentation/components/landing/`.

| Componente | Qué renderiza | Detalle mobile / a11y |
|---|---|---|
| `LandingScreen.tsx` | Compone todas las secciones + `FloatingGhosts` + `LandingScrollToTop` | — |
| `LandingHeader.tsx` | Header sticky con nav y CTA | El CTA de escritorio queda `hidden sm:flex` |
| `LandingNavigation.tsx` | `DesktopNav` + `MobileMenuButton` + drawer, vía `MobileMenuContext` | Pieza mobile propia: `hidden lg:flex` / `lg:hidden`, focus trap y bloqueo de scroll |
| `HeroGSAP.tsx` | Hero (`id="hero"`) con SplitText/ScrollTrigger (`useHeroGSAP`) | La tarjeta lateral de escritorio está `hidden lg:block` |
| `LandingTagline.tsx` | Manifiesto (`id="manifiesto"`) con reveal scrubbed | Respeta reduced motion |
| `LandingPresets.tsx` | Tarjetas de presets (`id="presets-fantasmagoricos"`) | — |
| `LandingPhilosophy.tsx` | Pilares del producto | — |
| `LandingDSPChain.tsx` | Cadena DSP de 13 etapas (`id="arquitectura-dsp"`) | Deuda de jerarquía h4/h5 (§7 #39) |
| `LandingEngineSpecs.tsx` | Especificaciones del motor (`id="especificaciones-motor"`) | No se exporta desde `index.ts` |
| `LandingABPlayer.tsx` | Comparador A/B (detalle abajo) | Teclas `A`/`B`, controles de 44 px, `useReducedMotion` |
| `LandingPricing.tsx` | Planes (`id="precios"`) | Precios placeholder (§7 #37) |
| `LandingFounders.tsx` | Equipo fundador (`id="equipo-fundador"`) | — |
| `LandingFAQ.tsx` | Acordeón de preguntas (`id="faq"`) | Alimenta el JSON-LD `FAQPage` del `page.tsx` |
| `LandingCTA.tsx` | CTA final | Parallax **sólo** con `pointer:fine` |
| `LandingFooter.tsx` | Footer con links reales y `next/image` | — |
| `LandingScrollToTop.tsx` | Fantasma flotante "volver arriba" | Aparece con `scrollY > 320` |
| `Reveal.tsx` | Wrapper de scroll-reveal por `IntersectionObserver` | Seguro con reduced motion |
| `InteractiveCard.tsx` | Tarjeta con stagger/glow de framer-motion | Prop `disableHoverOnMobile` |

- **Motion**: `hooks/useHeroGSAP.ts` (SplitText, ScrollTrigger, Observer, `gsap.matchMedia`) y `hooks/useTaglineReveal.ts` (scrub por viewport), con curva unificada y reveals gated por viewport.
- **A/B demo local (`LandingABPlayer.tsx`)**: el tono es **sintético, no un archivo** — oscilador saw de 110 Hz + sub sine de 55 Hz → `BiquadFilter` lowpass con Q 0.7 → gain → destination. La waveform es un **Canvas 2D con 96 barras deterministas** que morfean de "Original" (picos) a "Mastered" (denso), con cap de DPR y playhead en un loop de `requestAnimationFrame`. Las métricas mostradas (`AB_METRICS`) son LUFS −18.6→−14.0, True Peak −0.3→−1.0 dBTP y LRA 11.4→6.5, interpoladas por el morph. Cumple la regla anti-zipper del repo: `filter.frequency` y `gain.gain` se mueven con `setTargetAtTime`.
- **Fonts y SEO**: `next/font` self-hosted (Syne, Plus Jakarta Sans, JetBrains Mono, Instrument Serif) montadas en `html` para que resuelvan los tokens de `@theme`; `sitemap.ts`, `robots.ts` y structured data.
- **i18n**: bloques `landing`, `pricing` y `faq` con estructura idéntica en `es.json`/`en.json` (mismas líneas de inicio).
- **Decisiones abiertas** en el doc ODD `landing-awwwards-elite.md`: `--font-sans` sin mapear (el `h1` del hero calcula fuente de sistema), controles de 27–36 px (AA pero no 44 px) y precios placeholder. Ver §7 #37.

### 4.3 apps/agent (`@midimastering/agent`)

Sin cambios de fondo: traduce lenguaje natural → `IntentProfile` con Gemini + Zod, **no toca audio**. **Novedad (13-Oct, `4e95f50`)**: se **añadió el eje `vocal_focus` a `IntentProfile`** para volver a alinearlo con `intent_profile.schema.json` (se había quitado del mapper por error en `43cafe9`). Sigue pendiente: probar la llamada real (credenciales) y los tipos Python del mapper.

### 4.4 UI de proyectos y subida directa a R2 (estado real)

- **Vivo**: en `/upload`, `useMasteringWorkflow` → `trackStorageService.uploadOriginalToR2()` hace presign → PUT → PATCH y devuelve un path `r2:`; el cliente de API expone `presignAsset`, `completeAsset`, `listAssets`, `getAssetDownloadUrl` y el CRUD de proyectos (cubierto por `client.test.ts`).
- **Dormido**: `ProjectContext`/`useProject`, `projectDocumentStore`, `mixStateStore` y el `audioEngine` multi-stem. Existen, están testeados y **no los consume ninguna ruta**.
- **Follow-ups**: `deleteTrack` **no borra el objeto en R2** (deja huérfanos) y `getOriginalSignedUrl` ignora `expiresInSeconds` en la rama R2 (§7 #41).

### 4.5 Convex — eliminado

**Ya no existe en el repo**: 0 archivos trackeados, 0 dependencias, 0 referencias en el studio, y el job `deploy-convex` + env placeholder fueron removidos de la CI (`3d9f8ae`). **El flujo de login NO se removió**: el studio tiene auth propio con Supabase (`src/middleware.ts` → `updateSession`, `features/auth/`, `app/auth/callback/route.ts`).

---

## 5. Componentes removidos / documentación desactualizada

| Componente | Estado real | Evidencia |
|---|---|---|
| **`apps/bridge`** (MIDI → LiveParams → WS :8765) | ❌ **No existe** (ni en árbol ni en git) | Commits `92c79bf` y `38c1246` |
| **`simulator` (Python)** | ❌ **No existe**: el directorio ni el `Dockerfile` huérfano siguen en el repo | `git ls-files simulator` → vacío |
| **HumanMidi / gestos** | ❌ Removido | `92c79bf` (*remove vision/gesture/MIDI stack*), `38c1246` (*remove legacy HumanMidi gesture stack*) |
| **Convex** | ❌ Removido del repo y de la CI | `3d9f8ae`, verificación de referencias en `apps/studio/src` |

> **Consecuencia**: `README.md`, `AGENTS.md`, `docs/README.md` y los runbooks ya no listan bridge ni simulator. Con la remoción del Live Engine no queda ningún flujo MIDI→WS en el producto.

---

## 6. Entorno, CI/CD y verificación

### 6.1 Scripts y entorno local

- `scripts/` (`.bat` + `.ps1`): `setup` (venv + deps Python + bun install + build agent + `.env.local`), `start` (health checks), `stop`, `verify`. Docker Compose disponible (`docs/runbooks/DOCKER.md`).
- **`apps/audiomind/scripts/verify_prod_wiring.py`** — script de verificación del wiring de producción (recorrido de sesión, esquema de proyecto y RLS).
- Workspaces bun: `apps/*`; el script raíz `build` filtra por `studio`.

### 6.2 CI (`.github/workflows/studio-ci.yml`) — único workflow

- Repo **bun**: `oven-sh/setup-bun` + `bun install --frozen-lockfile` en la raíz + `bun run lint` + `bun run build` (nodo 22 como runtime de `next build`). Job bloqueante: `build`.
- Dispara en PRs con cambios en `apps/studio/**` y en push a `develop`/`main`.
- Sin job de Convex (removido).

> ⚠️ **Hallazgo**: la CI **no ejecuta nada del backend** — ni `pytest` ni `ruff`. Eso explica que el backend haya acumulado 524 errores de ruff (§3.1.5) sin que nada se ponga rojo: **no hay gate de lint ni de tests del backend en CI**. El saneamiento del 16-Oct bajó el conteo a **483**, pero sin gate la deriva vuelve: la decisión sigue abierta en §7 #34.

### 6.3 Deploy demo

- `docs/runbooks/DEMO_DEPLOYMENT_PLAN.md` — **LOCKED** (Vercel → studio UI; Railway → audiomind; envs exactas).
- `docs/runbooks/DEPLOY_RUNBOOK.md` — **EJECUTADO** (02-Oct); detalle del estado en §6.6.
- ⚠️ **Inconsistencia a resolver**: en la raíz del repo, `railway.json` y `nixpacks.json` definen `buildCommand: bun install --frozen-lockfile && bun run build` y `startCommand: bun run start`, que por el `package.json` raíz construyen y arrancan **el Studio**, no el backend FastAPI. Si el servicio backend de Railway usa el root del repo, esa config lo haría desplegar el frontend (ver §7 #45).

### 6.4 e2e (Playwright)

- `e2e/playwright.config.ts`: chromium, `baseURL localhost:3000`, webServer `npm run dev --workspace=apps/studio`, fixtures generadas.
- Specs: **sólo** `e2e/tests/demo_flow.spec.ts`. `master_to_live.spec.ts` fue eliminado con el Live Engine (27-Sep).
- **e2e no ejecutado** en este relevamiento (requiere stack levantado).

### 6.5 Verificación ejecutada (2026-10-16, sobre `develop` @ `95a90c8`)

| Comando | Resultado |
|---|---|
| `pytest tests/ -q` (audiomind) | **975 passed, 0 failed** · 206.6 s · 3 warnings · tras el saneamiento **977 passed, 0 failed** (125.1 s) |
| `python -m ruff check` (audiomind) | ⚠️ **483 errores** (eran 524; tras el saneamiento `F401`/`F811`/`F821` en 0 y `E402` 43→37) |
| `npm run test` (studio, vitest) | **11 archivos / 126 tests passed** (47.75 s) |
| `npm run lint` (studio, eslint) | **0 errores / 37 warnings** |
| `npm run build` (studio) | **✓ Compiled successfully, 17.6 s, exit 0** |

Comparación con la verificación del 23-Sep que declaraba este documento: backend 887 → **975**; vitest 8/72 → **11/126**; eslint 0 err/33 warn → 0 err/**37 warn**; build OK → OK; **ruff: ahora se mide y no está limpio** (antes declarado "0 errores").

**Re-verificación post-saneamiento** (mismo 16-Oct, sobre `211b9fb`): `pytest tests/ -q` → **977 passed, 0 failed** (125.1 s; +2 tests nuevos) · Studio `npm run test` → **11 archivos / 126 tests** · `npm run build` → **✓ Compiled successfully, 15.0 s, exit 0** · ruff `F401`/`F811`/`F821` → **0**. Verificación independiente delegada sobre la base `95a90c8`: **S1–S7 PASS, 0 blockers**. Detalle en §3.1.5 y §7 #34–#36.

### 6.6 Infraestructura realmente desplegada

| Pieza | Servicio | Estado | Nota |
|---|---|---|---|
| **Frontend (Studio + landing)** | Vercel | ✅ En pie | `NEXT_PUBLIC_API_URL` → Railway |
| **Backend (AudioMind)** | Railway — **free tier** | ✅ En pie | **Un solo contenedor, un solo worker de uvicorn** |
| **Audio (originales, mezcla, masters)** | Cloudflare R2 | ✅ Operativo | Upload 200 + `download_url` prefirmada; desde el 14-Oct también **originales** por presigned PUT |
| **Auth + metadata + `dsp_jobs` + `sessions` + proyectos** | Supabase (Postgres) | ✅ Operativo (parcial) | `dsp_jobs` aplicada (02-Oct) + sesiones durables (02-Oct); **las 4 tablas de proyecto están en migraciones locales, su carga en prod no fue verificada** |
| **Migraciones versionadas** | `supabase/migrations/` (6 archivos) | 🟡 Sin Alembic | `dsp_jobs`, `sessions`, `repair_job_and_session_schema`, `masters.status`, `project_document`, `project_documents` |

**Lo que la infraestructura de hoy NO resuelve** (documentado para no volver a descubrirlo):

1. **Sin worker de cola**: `BackgroundTasks` corre en proceso; un job interrumpido se marca `error`, no se reanuda (#19).
2. **Memoria y CPU ajustadas**: hubo OOM (#16); mitigado con Demucs fp16 + proceso hijo + `DJ_LIMIT_WORKERS`.
3. **La URL prefirmada caduca** (900 s PUT / 3600 s GET): hay que persistir la clave, no la URL.
4. **Estado del job ≠ estado de la sesión**: que el job devuelva `200 completed` no implica que la sesión sepa dónde está el audio — esa desconexión fue §3.2.1.
5. **La sesión durable depende del backend configurado y de la migración aplicada**; sin eso, en prod sigue mandando el archivo efímero (§3.1.3).

**`DJ_LIMIT_WORKERS` (ya commiteado, caveat vigente)**: el pool `DSP_THREAD_POOL` limita a `min(valor, 4)` con la variable presente y usa `settings.max_concurrent_dsp` si falta (`services/demo_guard.py`). **Caveat**: `reset_gate()` sigue reconstruyendo el pool desde `settings.max_concurrent_dsp` e **ignora `DJ_LIMIT_WORKERS`** — inocuo en producción (corre al importar), riesgoso en tests que monkeypatcheen settings (§7 #28).

### 6.7 Camino a infraestructura de pago (decisión diferida)

Los límites actuales son de **plan**, no de código. Orden propuesto cuando haga falta: (1) **Railway ≥1 GB** para que pipeline y mix entren sin OOM; (2) **volume persistente** para `outputs/`/`uploads/`; (3) **Supabase Pro** para proyección de filas/bandwidth. Nada de esto bloquea el desarrollo.

---

## 7. Pendientes y decisiones del usuario

> Se conservan los números 1–33 de la versión anterior para trazabilidad; los nuevos entran a partir de #34.

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| 1 | Push/PR de las ramas históricas `feat/mix-engine/01…08` | Mix Engine | Decisión del usuario |
| 2 | ~~Push de `develop` y `main`~~ **RESUELTO**: `develop` == `brik/develop` y `main` == `brik/main` (0/0). Queda `git fetch` para refrescar `team`/`origin` (refs stale) | git | Resuelto |
| 3 | ~~Limpiar churn de EOL en `mix_engine.py`~~ **HECHO 14-Oct** (`2776bd1` + `2aa40b6`) | Mix Engine | **Resuelto** |
| 4 | Mypy — **RESUELTO 23-Sep** (`66c4fdb`) | audiomind | Hecho |
| 5 | Prueba **manual** de "Mezcla de Audio" en la UI (backend + studio levantados) | Frontend | Decisión del usuario |
| 6 | ~~Deploy demo Vercel + Railway~~ **EJECUTADO 02-Oct** (ver §6.6) | Deploy | **Resuelto** |
| 7 | Convex — **RESUELTO**: eliminado del repo y de la CI | Studio | Resuelto |
| 8 | Probar `interpretIntent` real (credenciales Gemini) + tipos Python del mapper | apps/agent | Decisión usuario |
| 9 | Docs stale de bridge/simulator — **HECHO** (23-Sep y 27-Sep) | Docs | Hecho |
| 10 | Historial/retención de sesiones: `outputs/` fuera del volume de Railway | Backend/Deploy | Decisión de producto |
| 11 | Segundo libro del Mix Engine + autotune creativo — fuera de alcance v1 | Mix Engine | Documentado |
| 12 | Stem Balance T5–T7 — **HECHOS 23-Sep**; queda el A/B auditivo con el WAV hip_hop del productor | Mix Engine | Trabajo en curso |
| 13 | **Rotar credenciales R2** (quedaron expuestas; el token viejo es el que carga producción hoy) | Deploy | **Acción del usuario, bloqueante** — sin cambios |
| 14 | ~~Cargar 6 vars R2 en Railway~~ **HECHO 02-Oct** | Deploy | Cerrado |
| 15 | Validar R2 real: upload ✔, prefirmada ✔; falta ejercitar la **descarga** | Deploy | Prueba manual parcial |
| 16 | **Railway 512 MB → ≥1 GB** (hay OOM registrado; mitigado por Demucs fp16/aislado + `DJ_LIMIT_WORKERS`) | Deploy | Acción del usuario |
| 17 | ~~Tabla `dsp_jobs`~~ **APLICADA 02-Oct**; además se reparó el drift (`20261005180000`) y se añadió `masters.status` (`20261005220000`) | Backend | Cerrado (verificar aplicación en prod: #47) |
| 18 | **Flag explícito `AUDIOMIND_DSP_JOBS_USE_SUPABASE`** (hoy el `probe()` hace 1 `SELECT` con credenciales puestas) | Backend | Decisión del usuario |
| 19 | **Cola real de jobs**: requiere un worker que polee `dsp_jobs` buscando `queued` | Backend | Fuera de alcance v1 |
| 20 | **Deduplicación de submits**: la clave real del flight es `job:{job_id}` → no deduplica por sesión ni por `track_id` | Backend | Deuda técnica |
| 21 | **Progreso por etapa**: ni `build_mix()` ni `process_audio()` exponen progreso real (la UI va 0→100 indeterminado) | Backend/Frontend | Deuda técnica |
| 22 | ~~Camino async de mezcla no persistía el estado~~ **CORREGIDO Y COMMITEADO** (`a3fd00c`; ver §3.2.1) | Backend | **Resuelto** |
| 23 | Los remixes sobrescriben el mismo `r2_key` de la sesión → sin historial de mezclas | Backend | Decisión de producto |
| 24 | `MixStatusStream` con `doneLabel` por defecto hardcodeado en español (contra la regla i18n) | Frontend | Deuda técnica |
| 25 | **Sin Alembic**: las migraciones se aplican a mano; `test_dsp_jobs_migration.py` protege el drift del código, no el estado de la DB | Backend | Deuda técnica |
| 26 | Workstreams paralelos: `vocal_focus` (**ya mergeado** `cb7b267` + `4e95f50`), chips legacy en `LibraryView.tsx`, `odd/tasks/operational-hardening.md`, Engram `#825` | Varios | Fuera de alcance |
| 27 | ~~¿El master consume disco local o clave R2?~~ **RESUELTO 02-Oct**: rehidratación desde R2 | Backend/Deploy | Resuelto |
| 28 | **`DJ_LIMIT_WORKERS`**: ahora **commiteado**, pero (a) `reset_gate()` lo ignora y (b) la afirmación de `AGENTS.md` sobre "no bloquear el event loop" describe el síntoma de forma laxa (lo que agota el contenedor es CPU/RAM del pipeline en paralelo en el mismo worker) | Backend/Docs | Trabajo pendiente + doc por corregir |
| 29 | ~~Candidatos sin commit: `mastering-stages.ts` (untracked) e INSERT manual en `dsp_jobs`~~ **PARCIAL**: `mastering-stages.ts` ya está trackeado (`cbdf356`); el INSERT manual en prod es parche operativo, no migración | Deploy/Frontend | Parcialmente resuelto |
| 30 | ~~Persistir los MASTERS en R2~~ **RESUELTO y commiteado** (ver §3.1.2) | Backend | Resuelto |
| 31 | ~~Dos tests preexistentes en rojo~~ **RESUELTO**: la suite corre **975 passed, 0 failed** (16-Oct) | Tests | Resuelto |
| 32 | **La sesión no sobrevivía al redeploy**: primera mitad resuelta (sesiones durables en Postgres, §3.1.3); falta **verificar en prod** que el backend `auto` y la migración de reparación están aplicados | Backend/Deploy | Parcial — verificar en prod |
| 33 | ~~La suite escribía WAVs reales en el bucket de producción~~ **RESUELTO** con `tests/conftest.py` (degradación del cliente S3 + redirección de `SESSION_FILE`) | Tests/Infra | Resuelto — falta decidir el borrado de los 4 objetos de prueba (#46) |
| **34** | **Backend sin gate de lint/tests en CI**: sigue sin gate y quedan **483 errores** de ruff (eran 524; el saneamiento del 16-Oct puso `F401`/`F811`/`F821` en 0). Decisión: agregar job de backend (pytest + ruff) o fijar/suprimir la deuda restante | CI/Backend | **Acción del usuario** |
| **35** | ~~**Código muerto y roto en `engine.py`**~~ **RESUELTO** (`079d38a`): `generate_report()` y el helper de gain-match inalcanzable eliminados; `engine.py` con 0 errores `F` y superficie pública intacta. **Queda**: los stubs dudosos (`measure_correlation` → `0.0`) | Backend | Resuelto (parcial: stubs) |
| **36** | ~~**Rutas duplicadas**~~ **RESUELTO** (`3f5c758`): se conservaron los handlers de `upload.py` (los efectivos por orden de registro) y se borraron los sombreados de `mastering.py`; invariantes pinneadas en `tests/test_session_routes.py` y `tests/test_cleanup_invariants.py` | Backend | Resuelto |
| **37** | **Landing — 3 decisiones de producto**: `--font-sans` sin mapear (hero en fuente de sistema), controles de 27–36 px (<44 px), precios placeholder | Landing | **Decisión del usuario** |
| **38** | **`landing-motion`**: gate RDD pendiente (el envelope quedó obsoleto → hay que correr el preflight STATUS) y **decisión de estrategia de PR** (~450 líneas sobre un budget de ~400) | Landing/Proceso | **Decisión del usuario** |
| **39** | **`landing-tipscale-cascade-fix`**: T6 (jerarquía h4/h5 en `LandingDSPChain`), T7 (diferencia de 2.69 px entre CTAs), T8 (span de 8.5 px en `LanguageSwitcher`) abiertos; Fase 2 de art direction **sin autorizar** | Landing | Trabajo pendiente + autorización |
| **40** | **`ui-three-bugs`**: T1 (modal) y T2b ("Not Found") **bloqueados por falta de evidencia del navegador** del usuario | Frontend | **Decisión del usuario** |
| **41** | **Subida híbrida a R2 — follow-ups**: `deleteTrack` no borra el objeto en R2 (**huérfanos**, Fase 2 por decisión del usuario) y `getOriginalSignedUrl` ignora `expiresInSeconds` en la rama R2 | Backend/Studio | Decisión + trabajo |
| **42** | **Flujo de proyectos en producción**: cargar las 4 tablas nuevas + env vars, correr `verify_prod_wiring.py` y probar `/projects/*` end-to-end | Deploy/Backend | Trabajo pendiente |
| **43** | **`build_mix()` re-separa desde el original** en cada corrida: el reuso de stems ya separados es follow-up (costo de CPU serio en free tier) | Backend | Deuda técnica |
| **44** | **UI de proyectos dormida**: `ProjectContext`/`useProject`, `projectDocumentStore`, `mixStateStore`, `audioEngine` sin consumidores → falta listado/detalle de proyectos en Studio | Frontend | Trabajo pendiente |
| **45** | **`railway.json`/`nixpacks.json` raíz construyen el Studio** (`bun run build` → workspace studio): verificar qué servicio de Railway usa el root y cómo se despliega el backend | Deploy | **Decisión del usuario** |
| **46** | **Borrar los 4 objetos basura bajo `masters/`** del bucket de producción (dejados por los tests antes del fix de `conftest.py`) + aserción directa de la estampa de clave en los 2 paths de cache-hit | Tests/Infra | **Decisión del usuario** |
| **47** | **Verificar en prod** `AUDIOMIND_SESSION_STORE_BACKEND` y la aplicación de `20261005180000` / `20261005220000`; sin eso la durabilidad de sesiones y `masters.status` quedan en duda | Deploy/Backend | Acción del usuario |
| **48** | **Un clone fresco no puede correr la suite completa**: `apps/audiomind/samples/*.wav` está gitignoreado, así que un checkout limpio falla **4 tests de songstarter** hasta ejecutar `scripts/generate_samples.py`. Condición preexistente (idéntica en la base `95a90c8`), detectada por la verificación independiente del saneamiento | Tests/Onboarding | Deuda técnica |
| **49** | **RDD activo pero no ejecutable en este runtime**: `gentle-ai review mode status` → `on (global)`, pero `review assess` responde `risk: high` con `unassessable` — OpenCode no es elegible para el review inmutable (requiere 1.x estable sin relay, o 2.x bajo el plugin V2). Decisión: desactivarlo clone-local (`gentle-ai review mode disable --scope clone`) o correr el review en un runtime elegible | Proceso/Entorno | **Decisión del usuario** |

---

## 8. Documentación: dónde está todo

**Canónica/vigente** (`docs/reference/`, `docs/runbooks/`, `docs/manual/`, `docs/evidence/`): índice central en `docs/README.md` — specs de implementación, `COMPLIANCE_PHASE1`, `DSP_INDUSTRY_REVIEW`, `DESIGN`, SETUP/DOCKER/DEPLOY, USER_MANUAL, UX_MAP, evidencias de benchmark.

**Nuevo en specs**: `docs/reference/specs/project_document_v1_spec.md` — diseño del documento de proyecto V1 (ownership, JSON Schema, compiler puro, tres flujos).

**Histórica** (`docs/archive/`): integración, workplan, plan original.

**Local-only (excluida de git, `.git/info/exclude`)**:

- `docs/proposals/` — 4 PDF de libros de mezcla + viabilidades y propuestas (es la materia prima del RAG de §3.5).
- `docs/postmortems/` — `inc-2026-04-22-checkout-5xx.md`.
- `odd/` — **27 documentos de tareas**, fuente principal de decisiones del periodo 02→14-Oct. Los nuevos de este periodo:

| Documento | Estado |
|---|---|
| `backend-suite-green-docs-sync.md` | Cerrado (T1–T6 ✔); mirror Engram pendiente |
| `docs-truth-pass-auth-links-specs.md` | Cerrado (T1–T8 ✔) |
| `landing-awwwards-elite.md` | Feature completo; **gate RDD pendiente** + 3 decisiones (#37) |
| `landing-motion.md` | Ítems B7/B9/B10/B11 ✔; **gate RDD + estrategia de PR** pendientes (#38) |
| `landing-tipscale-cascade-fix.md` | T1–T5 ✔; **T6–T8 abiertos** (#39) |
| `master-r2-durability.md` | Implementado; 2 decisiones de usuario (#46) |
| `moises-multitenant-project.md` | WU1–WU5 ✔ (WU5 cerrado 09-Oct); prod pendiente (#42) |
| `project-flow-prod-remediation.md` | Cerrado (T1–T4 ✔); wiring de prod siguiente (#42) |
| `saneamiento-develop-16-oct.md` | Cerrado (T1–T9 ✔): rutas duplicadas, código muerto de `engine.py` y clases `F` de ruff (#34–#36) |
| `subida-original-r2-hibrida.md` | T1–T5 ✔, verificador independiente S1–S9 MET; follow-ups (#41) |
| `ui-three-bugs.md` | T2a/T3a/T3b ✔; **T1 y T2b bloqueados por evidencia** (#40) |

- **`.atl/`** — skill registry local (última actualización 2026-10-09).

**Deuda de documentación detectada (no corregida en este relevamiento)**:

1. `docs/README.md` (índice central) **no menciona la landing page** en ninguna sección, y describe el pipeline sin el flujo de proyectos, R2 ni las tablas nuevas.
2. `docs/reference/specs/` — `01`, `06` y `07` llevan banner histórico, pero sus cuerpos siguen describiendo el **Live Engine**, HumanMidi y un equipo de 5 devs con roles para ese engine: contradicen "dos motores + flujo de proyectos".
3. `AGENTS.md` §reglas describe el pool de DSP de forma laxa (ver #28).

**Memoria Engram** (`brikmaster2027`): conocimiento consolidado del Mix Engine, postmortems y decisiones de arquitectura; las features del periodo 02→14-Oct están registradas en observaciones recientes, con mirrors de tareas **pendientes** para varios de los documentos ODD listados arriba.

---

*Documento generado por auditoría read-only del repositorio. Actualizado el 23-Sep (Mix Stem Balance), el 27-Sep (remoción del Live Engine), el 02-Oct (infraestructura desplegada + defecto async de mezcla) y el 13-Oct (sync de conteos y claims). **Relevamiento completo del 2026-10-16** sobre `develop` @ `95a90c8`: suites medidas en vivo (975 backend / 126 vitest / build OK / ruff 524), ramas y remotes reales, flujo multitenant, landing, sesiones durables en Postgres, estabilidad Demucs, RAG local, y §7 reescrito con 47 pendientes. **Ampliado el mismo 16-Oct** con la arquitectura del frontend (§4.1), la capa mobile/responsive (§4.1.1) y el detalle componente por componente de la landing (§4.2). **Cerrado el mismo 16-Oct** con el saneamiento de `develop` (`3f5c758`, `079d38a`, `211b9fb`, `861c791`): rutas duplicadas (#36), código muerto de `engine.py` (#35) y las clases `F` de ruff (50 → 15), con la verificación re-corrida y §7 ampliado a **49 pendientes**.*

*Método: lectura del código y de los documentos ODD por exploradores read-only; las cifras de tests, lint y build son de ejecuciones propias del 16-Oct. Lo no verificado está marcado explícitamente como tal en cada punto (notablemente: estado de producción de las migraciones nuevas, backend de sesiones en prod y rotación de credenciales R2).*
