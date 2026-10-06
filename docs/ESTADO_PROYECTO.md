# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha de relevamiento**: 2026-09-21 · **Última actualización**: 2026-10-02 (infraestructura realmente desplegada y verificada en producción + defecto abierto en el camino async de mezcla; ver §3.2.1 y §6.6).
> **Alcance**: repositorio completo — los dos motores vivos (Mastering, Mix), frontend, agent de voz/IA, contratos, entorno, ramas y pendientes. El Live Engine se retiró; ver §3.3.
> **Fuentes**: código (`apps/`, `packages/`, `e2e/`), documentos ODD (`odd/tasks/`), documentación (`docs/`), estado git real y suites de verificación.

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | ✅ Operativo · cadena DSP proporcional completa · 628 tests verdes (backend completo) |
| **Motor de Mezcla (Mix Engine)** | ✅ Implementado (Pasos 01–08, TDD estricto) · paso 08 con cierre formal pendiente · **+ Stem Balance T1–T4** (faders ±6 dB + auto-balance por género, 23-Sep) · frontend "Mezcla de Audio" cerrado · ⚠️ **el camino async no registra la mezcla en la sesión** → el gate de master queda trabado (ver §3.2.1) |
| **Motor en vivo (Live Engine)** | ❌ **Removido del producto** (`ba3b4a6`, 27-Sep) — el tab solo mostraba un "próximamente" y ningún archivo fuera del cluster lo importaba. Queda el schema como contrato dormido |
| **Agent de interpretación (IA)** | 🟡 Compila · llamada real sin probar (faltan credenciales) |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | 🟡 Scaffold completo pero **durmiente** (la app no lo consulta) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** del repositorio — README y docs quedaron desactualizados |
| **Deploy demo (Vercel+Railway)** | 🚀 **Ejecutado y verificado** (02-Oct) — Railway free tier, Vercel y Cloudflare R2 en producción. Ver §6.6 |
| **Almacenamiento de audio (Cloudflare R2)** | ✅ Operativo y verificado en producción (upload 200 + URL prefirmada en el payload del job) |
| **Estado de jobs (`dsp_jobs` en Supabase)** | ✅ Tabla **aplicada** (02-Oct) — el estado del job sobrevive al redeploy |
| **Suites de verificación** | Backend **707 passed** · Studio vitest **61 passed** · eslint **31 errores / 29 warnings** (preexistentes, verificado sin regresiones) · build Next OK · e2e no ejecutado |

---

## 2. Estado del repositorio (git)

### 2.1 Rama actual y remotes

- **Rama actual**: `develop` — adelantada a `team/dev` por **4 commits sin pushear** (T1–T4 de Mix Stem Balance, 23-Sep).
- **Remotes**:
  - `origin` → `https://github.com/brikpaul569-cmd/BrikMaster2027.git`
  - `team` → `https://github.com/Masive-porjects/WaveIA.git`
  - `waveia` → `https://github.com/waveiamusic/WaveIA.git`
- **Working tree**: limpio en lo versionado. Hay rutas **excluidas localmente** (`.git/info/exclude`, no en git): `odd/`, `.atl/`, `docs/proposals/`, `docs/postmortems/`.

### 2.2 Ramas locales relevantes

| Rama | Estado |
|---|---|
| `develop` | Ahead 5 de `team/dev` — commits recientes de UI de mezcla (floating status stream, análisis flotante, `hip_hop` → perfil urban) |
| `main` | **Ahead 32 de `origin/main`** — muy atrasado el remote vs. local |
| `feat/mix-engine/01` … `08` | 8 ramas del Mix Engine, **locales sin push/PR** (decisión del usuario) |
| `demo/vercel-railway-client` | Ahead 3 de `origin/demo/vercel-railway-client` (deploy demo Vercel+Railway) |
| `docs/organize-centralize`, `feat/premium-ui-clarity`, `feat/preset-audio-signatures`, `refactor/page-mixpanel-onmasterize` | Varias con trabajo ya mergeado a `develop` |

### 2.3 Historial reciente (develop, 10 últimos)

```
e1ccc55 feat(mix-engine): expose balance_report in the mix payload        # T4
03f8abe feat(mix-engine): stem auto-balance by genre target with OFF default  # T3
fdfde4f feat(mix-engine): apply stem balance faders to all four stems at the bus input  # T2
cef92d8 feat(creative): stem balance faders ±6 dB for drums/bass/other/vocals  # T1
5de9025 feat(audiomind): aplicar tratamiento vocal adaptativo por registro
98e9e41 test(audiomind): añadir tests TDD del tratamiento vocal adaptativo
d32714d feat(audiomind): exponer registro/f0 vocal en AnalysisResult
0b54a97 feat(audiomind): detect vocal register y f0 con librosa.pyin
d94d80a refactor(studio): replace floating chips with sequential status stream
08ed0f6 style(studio): render mix analysis metrics as floating readings
```

> La feature **Mix Stem Balance** (T1–T4, `odd/tasks/mix-stem-balance.md`) entró en develop con 4 work-unit commits el 23-Sep; sigue la rama `feat/mix-engine/01…08` ya mergeada.

---

## 3. Los motores

### 3.1 Motor 1 — Mastering (AudioMind, backend FastAPI)

**Ubicación**: `apps/audiomind/src/audiomind/` · Python 3.11+ · FastAPI, librosa, pedalboard, numpy, demucs-onnx (separación de stems).

**Pipeline del engine** (`processing/engine.py`, ~1300 líneas): cadena **proporcional y dinámica** (no presets fijos):

1. **QC de entrada** (`strict_mode`) → rechaza HTTP 422 si clipping duro o true peak ≥ −0.3 dBTP (InputQcError).
2. **Gain staging** a −6 dBFS.
3. **De-esser dinámico** 3–8 kHz (detección por ratio de envolventes; neutral = bit-exacto).
4. **Match EQ por género** contra `TARGET_BANDS_HZ` [60,150,400,1000,2500,6000,10000,15000].
5. **Cadena de carácter** del preset (low/high shelf, peaking, exciter, imagen estéreo).
6. **Smart gate** (`smart_gate.py`): si la entrada ya cumple objetivos, omite corrección tonal (tier `full`/`conservative` — nunca gatea módulos de firma).
7. **Bloque M/S**: side HPF <100 Hz (off por defecto), reverb solo en el canal side (mono-safe).
8. **Colapso mono** <120 Hz al centro.
9. **Soft clipper** 16× (knee erf, márgenes) → **limiter true-peak** 8× con lookahead (doble protección anti intersample).
10. **Dither** TPDF + noise shaping Lipshitz 2º (16-bit) · resample libsoxr VHQ.
11. **Validación final**: LUFS, DR (LRA), correlación/phase del master final, crest.

**Revisión contra práctica profesional** (`docs/reference/DSP_INDUSTRY_REVIEW.md`): 17 recomendaciones — 16 cumplen, 1 parcial (preservar carácter tonal; diseño aceptado). **Fases A–D entregadas; P2 (dead code) FIXED** (2026-09-05).

**Compliance Phase 1** (`docs/reference/COMPLIANCE_PHASE1.md`, canónico): `processing_mode: transparent` = passthrough bit-exacto (neutral = bypass); `platform_target` (spotify −14/−1.0, apple_music −16/−1.0, youtube, tidal, custom); `output_sr`/`output_bit_depth` (24 bits default); `strict_mode` 422.

**Features adicionales**:

- **Demo mode**: pool gated de DSP (`MAX_CONCURRENT_DSP`), TTL de sesiones + janitor, duración máx 240 s, métricas `/api/demo/stats`.
- **Prerender** por preset (on-demand en demo).
- **Referencia externa** (Phase C): upload `reference-file` + `compare-reference` (diff espectral 8 bandas, LUFS/crest/correlación/LRA).
- **Álbum** (Phase D): `negotiate` (LRA por track) + `process` (target LUFS negociado sobre el pipeline existente).
- **Splitter** (Demucs), **Vocal chain**, **SongStarter/Beats** (secuenciador con samples).
- **Licencias**: `LicenseGuard` — sin key se desbloquea solo (demo); con key bloquea el estudio.

**Endpoints (38 en `api/`)**: upload (3) · mastering (17: process, prerender, reset, audio refs, raw, raw-mastered, download, session, master) · mix (2) · license (2) · splitter (3) · vocal (2) · songstarter (7) · batch/álbum (2) + `/health` y `/api/demo/stats` del app. Verificación detallada en el código de cada router.

**Jobs async**: además de los endpoints blocking, `POST /api/jobs/master` (`202` + `job_id`) y `GET /api/jobs/master/{job_id}`, y el par de mezcla `POST|GET /api/jobs/mix/{id}`. Estado en `services/job_store.py` — ver §3.1.1.

**Tests**: `apps/audiomind/tests/` — suite **712 passed** ✔ (incluye `test_master_job_store.py` y `test_dsp_jobs_migration.py`).

> ⚠️ Advertencias operativas: sesiones en memoria (`session_store`) — se pierden al reiniciar salvo espejo best-effort a `uploads/sessions.json`; `outputs/` (masters) **no** están en el volume de Railway → se pierden en redeploy. Pendiente de decisión: historial/retención.

### 3.1.1 Estado de jobs: `JobStore` compartido (30-Sep, sin commit)

Motivo: el estado de los jobs async vivía en un dict propiedad del proceso. En cada redeploy, todo job en vuelo desaparecía y el cliente polleaba un 404 para siempre. Es el mismo bug que se corrigió en mezcla, aplicado ahora a mastering.

| Antes | Ahora |
|---|---|
| `dsp_worker._active_jobs` (dict en memoria) | `services/job_store.py` (Supabase si existe `dsp_jobs`, si no memoria) |
| El worker escribía su propio estado | El endpoint **registra antes de encolar**; el worker sólo actualiza |
| Sin detección de muerte | Lease con heartbeat → un worker muerto se lee `error`, no `processing` para siempre |
| `get_job_status` devolvía el dict crudo | Proyecta al shape legacy que ya consume `AsyncJobStatus` |

**No se reemplazó Supabase.** Esto migró **el estado del job**, no los archivos: el master sigue subiendo a Supabase Storage (`audio-masters`) y actualizando `public.masters` vía `create_or_update_master_record()`. `session_id` es referencia blanda porque las sesiones viven en `sessions.json`, no en Postgres.

Contrato intacto: `GET /api/jobs/master/{id}` sigue devolviendo `job_id, track_id, status, started_at, completed_at, result, error`. El frontend no se tocó.

**Comportamiento por entorno** (decisión del usuario: no tocar Supabase por ahora):

| Configuración | Store | ¿Sobrevive redeploy? |
|---|---|---|
| Sin credenciales Supabase | memoria | No (igual que antes) |
| Credenciales, **sin** tabla `dsp_jobs` | memoria + warning | No — pero **no hay 404** |
| Credenciales + tabla creada | Supabase | Sí (el estado sobrevive; el DSP no se reanuda) |

`SupabaseJobStore.probe()` hace un `SELECT ... LIMIT 1` al elegir store: si la tabla no existe o la key está revocada, cae a memoria con un warning que dice qué configurar. Sin ese probe, deployar el código sin la tabla producía `202` en el submit y `404` dos segundos después en cada poll.

**Limitación honesta**: un job interrumpido se marca `error` ("interrupted"), **no se reanuda**. `BackgroundTasks` sigue siendo en-proceso. Hacer cola real exigiría un worker que polee `dsp_jobs` en busca de `queued`.

**Migración SQL versionada pero NO aplicada** (decisión explícita del usuario): `supabase/migrations/20260930183000_create_dsp_jobs.sql`. Es aditiva — crea `public.dsp_jobs`, no toca `tracks`/`masters`/`track_events`/`profiles`/`role_audit_logs` ni buckets. `apps/audiomind/tests/test_dsp_jobs_migration.py` (11 tests) falla si el SQL y `JobRecord` se desincronizan.

**Tests**: `tests/test_master_job_store.py` (13) cubre registro previo a encolar, shape legacy, no-mutación en lectura, detección de huérfanos, heartbeat y estado terminal ante éxito/fallo/excepción. Suite: **712 passed** (699 → 712).

---

### 3.1.2 Persistencia de los MASTERS en R2 (#30, resuelto 02-Oct, sin commit)

Antes de este cambio el master tenía el mismo problema que la mezcla (§3.2.1) y era peor: los 4 endpoints que sirven audio leían **solo** punteros al disco efímero (`SessionData.mastered_path` y `PresetMasterEntry.output_path`). En Railway Free, un redeploy borraba el WAV y el usuario recibía 404 sin explicación.

**Estado durable (2 campos)**

| Campo | Tipo | Significado |
|---|---|---|
| `SessionData.master_r2_key` | `str \| None` | Clave R2 del WAV de `mastered_path` |
| `PresetMasterEntry.r2_key` | `str \| None` | Clave R2 del master de ese preset |

Claves: `masters/{session_id}/{preset_id}_mastered.wav` y, para el puntero legacy, `masters/{session_id}/{session_id}_mastered.wav`.

**Escritura** — `_persist_master_to_r2(session, path, *, preset_id=None)` (línea ~319 de `api/mastering.py`) sube el WAV con `asyncio.to_thread(storage.upload_file, …)`, estampa la clave y llama a `save_sessions()`. Política deliberada: **nunca falla la request**. El master ya existe en disco local; R2 es el seguro contra el redeploy, así que un corte de R2 degrada a "puede perder el archivo en el próximo deploy" en vez de devolver 5xx al usuario que ya tiene el archivo.

Un solo PUT cuando el preset y `mastered_path` apuntan al mismo WAV, y ambos punteros quedan con la misma clave. La ruta de preset on-demand solo estampa si `entry.output_path == session.mastered_path`: estampar `master_r2_key` sobre bytes que no son los de `mastered_path` sería mentira.

**Lectura** — `_resolve_master_file(session, preset_id, *, missing_detail, missing_status)` centraliza los 4 consumidores. Precedencia: con `preset_id` cuenta **solo** esa entrada (un preset desconocido nunca cae a `mastered_path`); sin él, el puntero legacy. Local primero, R2 solo si falta el local, a un destino determinístico `{sid}_{preset}_mastered_from_r2.wav` (derivado del session id, nunca del path muerto). El puntero recuperado se cachea y se persiste, así el siguiente request es una lectura local. Objeto vacío o descarga fallida → **404** nombrando la clave y la razón real, differentiated del 404 de "este master nunca existió".

**Cobertura** — las **6** rutas productoras (preset on-demand, cache prebuilt, cache prerender, `/process` sin preset, prerender-serve, `/album/process`) y las **4** consumidoras (`/audio/mastered`, `/raw-mastered`, `/download/{fmt}`, `/compare-reference`). Reset limpia `master_r2_key` y `preset_masters = {}` se lleva las claves por preset. `api/batch.py` tiene su propio helper (con logger y storage propio) para no cruzar los límites de módulo.

**Tests**: `tests/test_master_r2_durability.py` (15) en 5 clases: rehidratación en los 4 endpoints + precedence (un preset desconocido nunca cae al puntero legacy) + served local sin tocar R2; 404 nombrando la clave ante descarga fallida, objeto de 0 bytes y ausencia de archivo+clave; sellado de punteros (preset desde un solo upload, y `/process`, prerender-serve y `/album/process` en el legacy); upload fallido que no rompe la request; reset que anula ambas claves. Suite: **740 passed, 2 failed** (los 2 de #31, preexistentes).

**Hueco de cobertura honesto**: los paths de *cache hit* (preset prebuilt y prerender) quedan cableados pero sin aserción directa en este archivo — se cubren indirectamente porque `conftest.py` hace degradar el upload y el comportamiento local no cambia. Si se quiere aserción directa de la estampa de clave en esos dos paths, falta test.

**Lo que #30 NO arregla**: el audio es durable, **el puntero no**. `uploads/sessions.json` también es efímero, así que en un redeploy la sesión no existe y la rehidratación nunca llega a ejecutarse — se devuelve el 404 pidiendo reprocesar. Ver #32. Y al hacer los uploads reales, la suite pasó a escribir en el bucket de producción (#33, corregido con `tests/conftest.py`).

---

### 3.2 Motor 2 — Mix Engine (mezcla IA+DSP)

**Ubicación**: `apps/audiomind/src/audiomind/processing/` (mix_engine.py + 11 módulos) · API en `api/mix.py`.

**Plan maestro**: `odd/tasks/plan-motor-de-mezcla.md` + viabilidad en `docs/proposals/VIABILIDAD_MOTOR_DE_MEZCLA.md` (local-only).

**Progreso — Pasos 01–08 IMPLEMENTADOS en TDD estricto** (suite creció 352 → **628 tests**):

| Paso | Rama | Commit | Estado |
|---|---|---|---|
| 01 Ruteo por stem + análisis | `feat/mix-engine/01-ruteo-stems` | `81a125a` | ✅ |
| 02 Frecuencias mágicas (Owsinski p.32) | `feat/mix-engine/02-frecuencias-magicas` | `1356d70` | ✅ |
| 03 Panorama por rol + validación posicional | `feat/mix-engine/03-panorama-validacion` | `8750b0e` | ✅ |
| 04 Dimensión a tempo (delay + Schroeder) | `feat/mix-engine/04-dimension-tempo` | `faf07d7` | ✅ |
| 05 Dinámica por stem + buss (Jerry Finn) | `feat/mix-engine/05-dinamica-buss` | `ff2b890` | ✅ |
| 06 Énfasis adaptativo por género | `feat/mix-engine/06-enfasis-genero` | `62467d4` | ✅ |
| 07 QC + versiones alternativas | `feat/mix-engine/07-qc-versiones` | `0b7b71a` | ✅ |
| 08 Exploración creativa acotada | `feat/mix-engine/08-exploracion-creativa` | `b37d82e` | ✅ (ver pendientes) |
| **SB** Faders + auto-balance por stem | `mix-stem-balance` (work-units en develop) | `cef92d8`+`fdfde4f`+`03f8abe`+`e1ccc55` | ✅ (T1–T4) |

**Stem Balance** (`odd/tasks/mix-stem-balance.md`, 23-Sep): producto pedido por el productor de la sesión (instrumental/snare dominan, voz ~7 dB abajo).

- **[T1]** Faders manuales ±6 dB por los 4 stems (`creative.py`, `_TRIM_STEM_RANGE = (-6.0, 6.0)`).
- **[T2]** `_apply_stem_trims` a la entrada del bus: escala por `10**(db/20)`; trims 0.0 = no-op bit-exacto (spec 08, neutral = bypass).
- **[T3]** Auto-balance opcional (`stem_balance.py` + toggle `auto_balance` en `build_mix`, default OFF): mide LUFS integrado por stem (BS.1770-4), target vocal = groove + d×6 según énfasis de género, corrige SOLO la voz con clamp ±6 dB.
- **[T4]** `balance_report` en el payload cuando `auto_balance=True`: género resuelto + status (active/neutral_fallback), LUFS por stem, target, `d`, gains (`*_db`) y flag `applied` honesto. OFF → clave ausente (payload previo exacto).
- **Pendiente**: T5 API (exponer faders+toggle en POST /mix), T6 Studio (UI), T7 A/B auditivo con la sesión hip_hop.

**Pipeline final por stem**: `split Demucs (4 stems) → pan por rol → EQ mágico → compresor por stem → dimensión (sends) → suma al bus → compresor de bus → QC → render de 5 versiones → modo creativo`.

- **Neutralidad**: perfiles `{}` = routing exacto del paso previo; `creativity=0` → principal byte-idéntico con/sin bloque creativo. La suma 1:1 NO es bit-exacta al original (Demucs es lossy — pitfall aceptado).
- **QC** (`quality_checks.py`): mono/fase, sibilancia 4–7 kHz, muddy 200–300 Hz, honky 450–600 Hz — flags informativos, **nunca bloquean**.
- **Versiones** (`render_versions.py`): principal 0 dB, vocal ±0.75 dB, instrumental, TV mix (sin vocal).
- **Creativo** (`creative.py`): espacio continuo 0..1, semilla reproducible, rejection sampling contra QC/posicional (nunca bloquea), `creative_manual=True` marca `non_standard`.

**API**:

- `POST /api/session/{id}/mix` → WAV + análisis en header `X-Mix-Result` (stems, `tempo_bpm`, `genre`, `genre_confidence`, sr, duración). Body opcional `{"dimension_enabled": false}`.
- `GET /api/session/{id}/audio/mix` → WAV persistido (URL estable para player/download).

**Frontend "Mezcla de Audio"**: `odd/tasks/mezcla-frontend.md` — **CERRADO (2026-09-21)**. Commits `7a95caf` (MixPanel.tsx, client.ts `mixTracks`/`getMixAudioUrl`, dock tab, GET /audio/mix) + `a406acf` (fix duplicación router). Verificado: `tsc --noEmit` limpio, vitest 22, pytest mix 9 passed. Queda **probar manualmente en la UI**.

**Pendientes del Mix Engine**: ver §7 (paso 08 EOL churn + cierre de assess; push/PR a `team`; análisis mypy soundfile).

### 3.2.1 ✅ Defecto corregido: el camino async de mezcla nunca registraba la mezcla en la sesión (02-Oct)

> **Estado**: corregido y verificado el 02-Oct-2026. `mix_status` ya se escribe en la sesión, el puntero durable a R2 se persiste, y el masterizar rehidrata la mezcla desde R2 cuando el disco local no la tiene. Suite: 725 passed / 2 fallos preexistentes y ajenos (ver §7 #31).

Síntoma reportado en producción: el job de mezcla termina `completed` al 100 %, pero el gate del frontend responde *"Termina tu mezcla antes de masterizar."* y no habilita el master.

**Causa raíz** — asimetría entre los dos caminos de mezcla:

| | Camino **sincrónico** `POST /api/session/{id}/mix` | Camino **async** `POST /api/jobs/mix/{id}` |
|---|---|---|
| Marca la sesión al empezar | `mix_status = "processing"` ✅ | `api/jobs.py:213` → `mix_status = "processing"` ✅ |
| Escribe el resultado | `api/mix.py:210-213` → `mix_path`, `mix_metadata`, `mix_analysis`, `mix_status = "completed"` ✅ | `services/mix_jobs.py` → **nunca escribe en la sesión** ❌ |
| Persiste | `save_sessions()` ✅ | — |
| Limpia en error | `mix_status = "failed"` ✅ | ❌ |

`services/mix_jobs.py::run_mix_job()` (95-116) solo actualiza la fila de `dsp_jobs`, y `_deliver()` (174-195) sube el WAV a R2 y **borra `mix_path` del payload a propósito** (línea 188, porque el path local es efímero en Railway). Ninguno de los dos toca la sesión. Resultado: `mix_status` queda en `"processing"` para siempre y el job reporta éxito.

**Consecuencias verificadas:**

1. **Gate trabado (síntoma visible)** — `apps/studio/src/lib/audioUtils.ts:139-146` bloquea con `processing`/`failed`.
2. **`GET /api/session/{id}/audio/mix` → 404** (`api/mix.py:240`) porque `mix_path` es `null`.
3. **⚠️ Fallo silencioso (el más grave)** — `api/mastering.py:259-266` solo resuelve `source = "mix"` si `mix_status == "completed"`; en cualquier otro caso cae a `"original"`. Con la sesión en ese estado, **el masterizaría el ORIGINAL en vez de la MEZCLA**, sin error visible y con un output incorrecto. Esto ya es un bug de salida equivocada, no solo un problema de UI.
4. **Sin salida de emergencia** — `PATCH`/`POST /api/session/{id}` devuelven `405 Method Not Allowed`: no existe endpoint para corregir el estado a mano; tiene que salir del pipeline de mezcla.

**Evidencia de estado (sesión `26dadea6-37ad-40c1-bdd3-92861abc1704`, 02-Oct)** — `apps/audiomind/uploads/sessions.json` vs. disco:

| Campo / archivo | Estado |
|---|---|
| `outputs/{sid}_mix.wav` | ✅ existe (26 MB) |
| `outputs/{sid}_cinta_mastered.wav` | ✅ existe (26 MB) |
| `sessions.json → mastered_path` | ✅ apunta al master de `cinta` |
| `sessions.json → preset_masters.cinta` | ✅ `status: completed` |
| `sessions.json → mix_path` | ❌ `null` |
| `sessions.json → mix_status` | ❌ `"none"` (el proceso en memoria quedó en `processing`) |

**Fix aplicado (02-Oct-2026)** — `services/mix_jobs.py` ahora refleja el resultado en la sesión igual que el camino síncrono:

| Cambio | Archivo | Efecto |
|---|---|---|
| `SessionData.mix_r2_key` (`str \| None = None`) | `models/audio.py` | Puntero durable a la mezcla en R2. Default `None` → sesiones antiguas siguen siendo válidas. |
| `_record_mix_on_session()` | `services/mix_jobs.py` | Tras `_deliver()`: `mix_r2_key` + `mix_analysis` + `mix_metadata` + `mix_status="completed"` + `save_sessions()`. |
| `_mark_mix_failed()` | `services/mix_jobs.py` | Marca `failed` desde `run_mix_job()` **conservando** el último mix entregado. |
| `_hydrate_mix_from_r2()` | `api/mastering.py` | Re-descarga la mezcla a `outputs/{sid}_mix_from_r2.wav` si el path local no resuelve. |
| `_mix_is_deliverable()` | `api/mastering.py` | El mix cuenta como entregable si existe el archivo local **o** hay `mix_r2_key`. |
| Escritura atómica | `session_store.py` | `sessions.json.tmp` + `Path.replace()` bajo lock, en lugar de `write_text()` (que trunca). |

**La guarda que se pidió, y por qué importa**: `_record_mix_on_session()` **solo** escribe `mix_path` si `Path(mix_path).exists()`. En Railway el archivo local no existe, así que se persiste `mix_r2_key` y el estado `completed`, nunca un path muerto. Sin esa guarda el masterizar habría fallado con 400 en cada sesión async.

**Decisión de diseño deliberada**: si la resolución inteligente (`source=None`) ya eligió un mix entregable y la descarga desde R2 falla, el endpoint devuelve **400, no el original**. Razonar en contra sería reintroducir exactamente el bug que esto arregla: entregar un master de *otro* audio con `status="completed"` y sin error. La asimetría es intencional — el default inteligente cae al original solo cuando el mix *nunca fue entregable*; una vez que se eligió un valor entregable, una caída de red es un 400 accionable, no un master equivocado. Cubierto por `test_unreachable_r2_refuses_instead_of_silently_mastering_the_original`.

**Aclaración de un 404 que NO es este bug**: `GET /api/session/{id}/audio/mastered?preset_id=cinta` (`api/mastering.py:1390-1421`) busca `session.preset_masters["cinta"].output_path` — el **master**, no la mezcla. Devolver 404 ahí es el estado transitorio normal mientras el master del preset no termina (el frontend lo pide en cuanto se selecciona el preset). El error de consola *"No mastered audio available. Process first."* viene de `api/mastering.py:1519-1528` (`/download/{fmt}`) y corresponde a consolidar/guardar el master antes de que exista. Ninguno de los dos se arregla tocando `dsp_jobs`.

---

### 3.3 Motor 3 — Live Engine — REMOVIDO (27-Sep, `ba3b4a6`)

El tercer motor **ya no existe como producto**. Motivo: su tab en el sidebar de mastering solo renderizaba un `ComingSoonNotice` ("el motor de efectos en vivo llega pronto"), `LiveView` no tenía ningún importador y nunca existió una ruta `/live`. Los 17 archivos de `lib/live/`, `adapters/live/` y `presentation/components/live/` solo se importaban entre sí.

**Qué sobrevive**:

- `packages/contracts/live_params.schema.json` — 9 campos (`ts` requerido): `filter_cutoff` 200–12000 (12000), `filter_res` 0.5–12 (0.7), `drive` 0–1 (0), `delay_time` 50–800 (250), `echo_feedback` 0–0.8 (0), `reverb_mix` 0–1 (0), `output_level` 0–1 (0.9), `fx_preset` (clean | dub | big_room | radio | null). Sigue siendo la fuente de verdad, ahora como **contrato dormido**: no se regenera ni se consume salvo reactivación explícita del engine.
- `packages/contracts/liveParams.gen.ts` — tipos TS generados. `gen_types.sh` escribe ahí (antes apuntaba al path de Studio que se eliminó).
- `safeCloseAudioContext` — helper genérico de Web Audio, no era código muerto: se movió a `apps/studio/src/lib/audioContext.ts` con sus 5 tests porque `useStereoField.ts` (análisis estéreo) lo usa.

**Eliminado**: `LiveView`, `FxSlotPanel`, `Knob3D`, `LiveMeterDeck`, `LiveRecorderBar`, `PresetHeader`, `useLiveEngine`, `audioGraph`, `fxPresets`, `impulseResponse`, `recorder`, `meterMath`, `liveMeterBus`, `liveDefaults`, el `simulator/Dockerfile` huérfano, y las entradas `live` de `MasteringTab`, `DOCK_MODULES`, `DEFAULT_FEATURES`, `/mezclas` y `nav.live`.

Con esta remoción, WaveAI queda con **dos motores: Mastering y Mix**.

---

## 4. Studio — frontend y aplicaciones acompañantes

### 4.1 Studio (Next.js 16 + React 19 + TS + Tailwind 4)

- **Tabs actuales** (`page.tsx`): Mezcla de Audio · Masterizar Audio (módulos) · Splitter · Vocal · Beats (SongStarter) · Guía de Géneros · Cadena de Master · Análisis · Estéreo · Álbum.
- Componentes: 60+ en `src/presentation/components/` (dock/ModuleDock con tiles de motor, MixPanel, MixWaveformAB, MixStatusStream, Player con A/B, FloatingDeliveryPanel, chat/ChatPanel, audio/* secuenciadores, auth/*, etc.).
- **Mix UI**: MixPanel + MixWaveformAB + MixStatusStream (stream secuencial de estado), action "masterize" post-mezcla.
- **Chat/agente**: ChatPanel → `/voz/chat` → `interpretIntent` (agent Gemini) → perfil; preset cards.
- **Voz**: `/voz/speak` (TTS ElevenLabs opcional con cache `.tts-cache`, tope 400 chars, `204` = fallback a `speechSynthesis` del navegador) · `/voz/escuchar` + `useVoiceInput` (entrada por voz) · `lib/voice/decodeAgentText` (parseo de texto del agente).
- **Librerías clave**: GSAP 3.15 + @gsap/react (11 componentes), framer-motion 12, tone 15, wavesurfer.js 7, lucide-react. Sin framework i18n: **microcopy en español latino neutro** hardcodeada (normalizada en `main`).
- **Tests**: vitest **57 passed** (8 archivos: meterMath 24, client 13, audioUtils 7, audioContextUtils 5, decodeAgentText 4, etc.) · eslint **0 errores / 28 warnings** (no funcionales, documentado) ✔.

### 4.2 apps/agent (`@midimastering/agent`)

- Traduce lenguaje natural → `IntentProfile` (9 ejes 0..1) con Gemini (`@google/genai`) + Zod; **no toca audio** — el mapper DSP convierte el perfil en `MasteringSettings`.
- Contrato `intent_profile.schema.json` ✅; `interpretIntent` compila pero **la llamada real no fue probada** (sin credenciales en el entorno). `needsClarification` no mueve el perfil; fuera de rango se rechaza (no clamp); ajuste incremental; `effort: low` por defecto; system prompt estable con `cache_control`.
- Pendientes: tipos Python para el mapper, integración Convex action, persistencia de conversación. El README referencia roles del equipo (Brickman/Tomás/Andrés).

### 4.3 Convex — dummie

Scaffold completo (`convex/` schema, auth, mastering, projects, messages; deps `convex` + `@convex-dev/auth`) pero **la app NO lo consulta**: `ConvexClientProvider` es un passthrough, hay **0 imports de `convex/_generated`**, el flujo de login fue removido. `convex/auth.ts` queda disponible para un futuro login real. El CI tiene env placeholder y un job `deploy-convex` gated por variable/secret.

---

## 5. Componentes removidos / documentación desactualizada

| Componente | Estado real | Evidencia |
|---|---|---|
| **`apps/bridge`** (MIDI → LiveParams → WS :8765) | ❌ **No existe** (ni en árbol ni en git) | Commits `92c79bf` (*remove vision/gesture/MIDI stack — Live Engine standalone*) y `38c1246` (*remove legacy HumanMidi gesture stack*) |
| **`simulator` (Python)** `python -m simulator.main` | ❌ **Solo queda `simulator/Dockerfile`** — el módulo ya no existe | `git ls-files simulator` → solo `simulator/Dockerfile` |
| **HumanMidi / gestos** | ❌ Removido | `docs/archive/HUMANMIDI_REMOVAL_REPORT.md` (histórico) |

> **Consecuencia (resuelta 27-Sep)**: `README.md`, `AGENTS.md`, `docs/README.md` y los runbooks ya no listan `apps/bridge/` ni `simulator/` como componentes vivos. Con la eliminación del Live Engine (`ba3b4a6`) no queda ningún flujo MIDI→WS en el producto.

---

## 6. Entorno, CI/CD y verificación

### 6.1 Scripts y entorno local

- `scripts/` (`.bat` + `.ps1`): `setup` (venv + deps Python + bun install + build agent + .env.local), `start` (start-all con health checks), `stop`, `verify`. Docker Compose disponible (`docs/runbooks/DOCKER.md`).

### 6.2 CI (`.github/workflows/studio-ci.yml`)

- Pull requests (ruta `apps/studio/**`): `npm ci` + `npm run lint` + `npm run build` (env `NEXT_PUBLIC_CONVEX_URL` placeholder).
- Push a `develop`/`main`: igual.
- Job `deploy-convex` opcional solo en `main` si `CONVEX_DEPLOY_ENABLED=true` y existe `CONVEX_DEPLOY_KEY`.

### 6.3 Deploy demo

- `docs/runbooks/DEMO_DEPLOYMENT_PLAN.md` — **LOCKED** (Vercel → studio UI; Railway → audiomind; sin proxy de audio; envs exactas: `AUDIOMIND_CORS_ORIGINS`, `AUDIOMIND_PRERENDER_MODE=on_demand`, `MAX_CONCURRENT_DSP=1`, `DEMO_MAX_DURATION_SECONDS=240`, `MAX_FILE_SIZE_MB=100`, `SESSION_TTL_MINUTES=60`, `NEXT_PUBLIC_API_URL`).
- `docs/runbooks/DEPLOY_RUNBOOK.md` — **EJECUTADO** (02-Oct): Railway + Vercel en pie con credenciales reales. El detalle de lo que quedó desplegado y verificado está en §6.6.

### 6.4 e2e (Playwright)

- `e2e/playwright.config.ts`: chromium, `baseURL localhost:3000`, webServer `npm run dev --workspace=apps/studio`, fixtures `demo-audio.wav`.
- Specs: solo `demo_flow.spec.ts`. Se eliminó `master_to_live.spec.ts` (27-Sep) — cubría `dock-tab-live`, `live-view`, `.fx-slot-panel` y `knob-filter_cutoff`, todos borrados con el Live Engine; además ya fallaba en colección por un import inexistente (ver `evidence/DEMO_LOCAL_VALIDATION.md` §) y su parte de master ya la cubría `demo_flow.spec.ts`. **e2e no ejecutado** (requiere stack levantado).

### 6.5 Verificación ejecutada (23-Sep, relevamiento actualizado)

| Comando | Resultado |
|---|---|
| `pytest tests/ -q` (audiomind) | **628 passed** (~114 s, warnings de deprecación de terceros) |
| `python -m ruff check` (audiomind) | **0 errores** (import order autofijado en T3) |
| `npm run test` (studio, vitest) | **8 files / 57 tests passed** |
| `npm run lint` (studio, eslint) | **0 errors / 28 warnings** |
| `npm run build` (studio) | — ejecutar si se desea (no corrido para no interferir) |

### 6.6 Infraestructura realmente desplegada (verificada 02-Oct)

Estado real de producción, con lo verificado en vivo contra los servicios. Esto **reemplaza** el estado "plan preparado, no ejecutado" que figuraba hasta el 27-Sep.

| Pieza | Servicio | Estado verificado | Nota |
|---|---|---|---|
| **Frontend (Studio)** | Vercel | ✅ En pie | `NEXT_PUBLIC_API_URL` apunta a Railway. El build de Vercel corre sobre su propia red, así que el fetch a `/health` y el upload sí funcionan por ese camino |
| **Backend (AudioMind)** | Railway — **free tier** | ✅ En pie | **Un solo contenedor, un solo worker de uvicorn.** El pool de DSP compite con el event loop en la misma CPU/RAM |
| **Audio (WAV de mezcla y masters)** | Cloudflare R2 | ✅ Operativo | Upload devuelve 200 y el job trae `r2_key` + `download_url` prefirmada. CORS configurado para `*.vercel.app` |
| **Auth + metadata + `dsp_jobs`** | Supabase (Postgres) | ✅ Operativo | Tabla `dsp_jobs` **aplicada** (02-Oct) + 1 fila insertada a mano para el job `mix_bc0428453659` |

**Lo que la infraestructura de hoy NO resuelve** (documentado para no volver a descubrirlo):

1. **Sin disco persistente.** Las sesiones viven en memoria + espejo best-effort a `uploads/sessions.json`, y los masters en `outputs/`, que **no** está en el volume de Railway. Un redeploy pierde ambos. R2 es el único almacenamiento durable de audio, y hoy solo guarda el WAV de mezcla.
2. **Sin worker de cola.** `BackgroundTasks` corre dentro del proceso: un job interrumpido se marca `error`, no se reanuda. Ver #19.
3. **Memoria y CPU ajustadas.** Ya hubo OOM registrado (#16) y el pipeline de 13 etapas más el mix no entran en 512 MB. Mitigación parcial aplicada: `DJ_LIMIT_WORKERS` (ver abajo).
4. **La URL prefirmada de R2 caduca.** No es un identificador durable; para sobreviver hay que persistir el `r2_key`, no la `download_url`.
5. **El estado del job y el estado de la sesión son dos cosas distintas.** Que `GET /api/jobs/mix/{id}` devuelva `200 completed` **no** implica que la sesión sepa dónde está la mezcla. Esa desconexión es exactamente §3.2.1.

**Mitigación de concurrencia aplicada (02-Oct, local, sin commit)** — `services/demo_guard.py`: el pool `DSP_THREAD_POOL` ahora lee la variable de entorno `DJ_LIMIT_WORKERS` y la limita a un máximo de 4 workers (`min(valor, 4)`), en lugar de usar siempre `settings.max_concurrent_dsp`. Con la variable ausente, el comportamiento es idéntico al anterior. En Railway se setea `DJ_LIMIT_WORKERS=2`.

> ⚠️ **Caveat conocido**: `reset_gate()` reconstruye gate y pool desde `settings.max_concurrent_dsp` e **ignora `DJ_LIMIT_WORKERS`**. Es inocuo en producción (solo corre al importar el módulo), pero si algún test lo llama después de monkeypatchear settings, el límite del pool se pierde para ese proceso. A cerrar cuando se implemente el fix de §3.2.1.

**Camino a infraestructura de pago (decisión del usuario, diferida a futuro)**: los límites de arriba son límites de *plan*, no de código. Cuando haga falta, el orden de compra propuesto es (1) **Railway con ≥1 GB de RAM** para que el pipeline y el mix entren sin OOM, (2) **volume persistente** para `outputs/` y `uploads/` y así no depender del espejo best-effort, (3) **Supabase Pro** para proyección de lectura y de filas/bandwidth sin topes. Nada de esto bloquea el desarrollo: hoy el workaround es el del `DJ_LIMIT_WORKERS` más R2 como almacenamiento durable de audio.

---

## 7. Pendientes y decisiones del usuario

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| 1 | Push/PR de las ramas `feat/mix-engine/01…08` al remote `team` | Mix Engine | Decisión del usuario (requiere `gh auth login`) |
| 2 | Push de `develop` (ahead 4 de `team/dev`) y `main` (ahead 32 de `origin/main`) | git | Decisión del usuario |
| 3 | Limpiar **churn de EOL (LF→CRLF)** en `mix_engine.py` del paso 08 y cerrar el assess bloqueado | Paso 08 Mix Engine | Trabajo pendiente |
| 4 | **Mypy**: RESUELTO 23-Sep (commit `66c4fdb`) — `python_version` bump a 3.12 en pyproject, overrides estrechos para libs sin stubs, tipado corrigido hasta `Success: no issues found in 72 source files` | audiomind | Hecho |
| 5 | Prueba **manual** de "Mezcla de Audio" en la UI (backend + studio levantados) | Frontend | Decisión del usuario |
| 6 | **Deploy demo Vercel + Railway** (runbook listo, plan LOCKED) — requiere credenciales y vars | Deploy | Acción pendiente |
| 7 | Decidir si se **activa Convex** (auth/queries reales) o se limpia el scaffold | Studio | Decisión |
| 8 | Probar `interpretIntent` real (credenciales Gemini/Anthropic) + tipos Python del mapper + integración Convex action | apps/agent | Decisión usuario / credenciales |
| 9 | **Actualizar documentación stale**: README/AGENTS/docs mencionan bridge y simulator que ya no existen — **HECHO 23-Sep** (ESTADO_PROYECTO, README, AGENTS, docs/README, SETUP, DOCKER, USER_MANUAL, UX_MAP, ARQUITECTURA_WAVEIA_DETALLE actualizados; specs 05/07 y archive quedan históricos por convención). El servicio `simulator` roto del compose fue **quitado** (23-Sep, commit `093946c`). **Cerrado 27-Sep** (`ba3b4a6`): el `simulator/Dockerfile` huérfano (que `COPY`aba un `requirements.txt` inexistente, o sea no podía construir) fue eliminado con su directorio. La nota sobre `scripts/setup/setup.ps1` installando requirements inexistentes quedó **stale**: ese script ya estaba corregido el 23-Sep y hoy solo instala `-e apps/audiomind` | Docs + compose + setup | **Hecho** |
| 10 | Historial/retención de sesiones: `outputs/` fuera del volume de Railway → masters se pierden en redeploy | Backend/Deploy | Decisión de producto |
| 11 | Segundo libro del Mix Engine (anexo al plan) + autotune creativo **fuera de alcance v1** | Mix Engine | Documentado como fuera de alcance |
| 12 | **Mix Stem Balance**: T5 API (trims + toggle en POST /mix), T6 Studio (faders + toggle), T7 E2E neutralidad bit-exacta **HECHOS 23-Sep**; queda el A/B auditivo con la sesión hip_hop del productor (requiere su WAV, no está en el repo) | Mix Engine | Trabajo en curso (T1–T7 automatizable hechos, 23-Sep) |
| 13 | **Rotar credenciales R2**: quedaron expuestas en el chat/historial y hardcodeadas antes de ser borradas. Crear token nuevo (Object Read & Write) en Cloudflare y revocar el viejo. **Sigue pendiente** — el token viejo es el que está cargando producción hoy | Deploy | **Acción del usuario, bloqueante** |
| 14 | **Cargar 6 vars R2 en Railway**: `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` + opcionales `R2_PUBLIC_URL` / `R2_ACCOUNT_ID`. **HECHO 02-Oct** — verificado en producción: upload 200 y `download_url` prefirmada en el payload del job | Deploy | **Cerrado** |
| 15 | **Validar R2 real** (upload, HEAD, presigned URL, descarga). **HECHO 02-Oct**: upload verificado contra Railway real y la URL prefirmada llegó al cliente. Falta solo ejercitar la **descarga** de esa URL | Deploy | Prueba manual (parcial) |
| 16 | **Railway 512 MB → ≥1 GB**: hay OOM registrado; el pipeline de 13 etapas más el mix no entran. Mitigado parcialmente con `DJ_LIMIT_WORKERS=2` (§6.6) hasta que se decida el plan de pago | Deploy | **Acción del usuario** |
| 17 | **Tabla `dsp_jobs`**: la migración `supabase/migrations/20260930183000_create_dsp_jobs.sql` estaba versionada pero NO aplicada. **APLICADA 02-Oct** (tabla creada + fila del job `mix_bc0428453659` insertada a mano). El estado de los jobs ya sobrevive al redeploy | Backend | **Cerrado** |
| 18 | **Flag explícito `AUDIOMIND_DSP_JOBS_USE_SUPABASE`**: hoy, con credenciales puestas, el `probe()` hace 1 `SELECT` a Supabase y cae a memoria. Si "no afectar Supabase" significa cero tráfico, hace falta un opt-out | Backend | **Decisión del usuario** |
| 19 | **Cola real de jobs**: `BackgroundTasks` corre en el proceso. Un job interrumpido se marca `error`, no se reanuda. Reanudar (o no perder trabajo en OOM) requiere un worker que polee `dsp_jobs` buscando `queued` | Backend | Fuera de alcance v1 |
| 20 | **Deduplicación de submits**: el comentario de `get_or_create_flight` promete dedupe por sesión, pero la clave real es `job:{job_id}`, así que un job por id no deduplica nada. El master tampoco deduplica por `track_id` | Backend | Deuda técnica |
| 21 | **Progreso por etapa**: `build_mix()` y `process_audio()` no exponen progreso real, así que la UI va 0→100 con estado indeterminado. Sin eso no hay barra honesta | Backend/Frontend | Deuda técnica |
| 22 | ~~**El camino async de mezcla no persiste el estado final en la sesión**~~ **CORREGIDO 02-Oct**: `services/mix_jobs.py` ahora escribe `mix_status`/`mix_analysis`/`mix_r2_key` en la sesión, y `api/mastering.py` rehidrata desde R2. 13 tests nuevos. Detalle, evidencia y verificación en **§3.2.1** | Backend | **Resuelto — sin commit** |
| 23 | **Remixes sobrescriben** el mismo `r2_key` de la sesión, así que no hay historial de mezclas | Backend | Decisión de producto |
| 24 | **`MixStatusStream` tiene un `doneLabel` hardcodeado** en español como default, contra la regla de i18n. El contenedor le pasa la traducción, pero el fallback sigue siendo texto en TSX | Frontend | Deuda técnica |
| 25 | **Sin Alembic**: las migraciones SQL se aplican a mano. `test_dsp_jobs_migration.py` protege el drift del código, pero no el estado de la DB | Backend | Deuda técnica |
| 26 | **Workstreams paralelos abiertos**: `vocal_focus` sin mergear (commit `71b7515` en `feat/ia-asistente-mezcla`, con drift agente/Python), chips legacy en `LibraryView.tsx`, `odd/tasks/operational-hardening.md` y Engram `#825` | Varios | Fuera de este cambio |
| 27 | ~~**¿El master consume el disco local o la clave de R2?**~~ **RESUELTO 02-Oct** → opción (a): `api/mastering.py::_hydrate_mix_from_r2()` rehidrata el path local desde `mix_r2_key` antes de masterizar. Descartadas (b) y (c): (b) rompe el contrato del pipeline DSP y (c) es costo recurrente. La persistencia de los propios masters queda fuera de alcance (#30) | Backend/Deploy | **Resuelto** |
| 28 | **`DJ_LIMIT_WORKERS` sin commit y con caveat**: el cambio en `services/demo_guard.py` está solo en el working tree, y `reset_gate()` ignora la variable (§6.6). Además la afirmación de `AGENTS.md` de que "el pool evita bloquear el event loop" describe el síntoma de forma laxa: los threads no bloquean el event loop por sí mismos; lo que agota el contenedor es la CPU y la RAM del pipeline corriendo en paralelo en el mismo worker | Backend/Docs | Trabajo pendiente + doc que corregir |
| 29 | **Candidatos de revisión sin commit**: `apps/studio/src/lib/mastering-stages.ts` (nuevo, sin trackear) y el `INSERT` manual de `dsp_jobs` hecho en producción para destrabar el polling. El segundo es un parche operativo, no una migración: el siguiente que ejecute el flujo async va a volver a necesitarlo si la tabla no queda poblada por el propio backend | Deploy/Frontend | Decisión del usuario |
| 30 | ~~**Persistir los MASTERS en R2 y rehidratarlos igual que la mezcla**~~ **RESUELTO 02-Oct** (sin commit) — `SessionData.master_r2_key` + `PresetMasterEntry.r2_key`; `_persist_master_to_r2()` sube el WAV al entregarlo (off-event-loop, falla sin romper la request) y `_resolve_master_file()` rehidrata desde R2 antes de servir. Cableadas las **6** rutas productoras (preset on-demand, cache prebuilt, cache prerender, `/process`, prerender-serve, `/album/process`) y las **4** consumidoras (`/audio/mastered`, `/raw-mastered`, `/download/{fmt}`, `/compare-reference`); reset limpia las claves. Objetos vacíos y fallos de descarga → 404 con detalle. Ver §3.1.2 | Backend | **Resuelto** |
| 31 | **Dos tests preexistentes fallan en local y NO son regresión de §3.2.1** (verificado con `git stash` sobre los 4 archivos fuente): (a) `test_async_mix_jobs.py::TestStorageKeys::test_no_credential_has_a_hardcoded_default` — falla porque el `.env` local tiene credenciales R2 reales, y el test afirma `settings.r2_access_key_id == ""`; pasa si se oculta el `.env`. Es el guardián de #13, funcionando, pero necesita una forma de correr con credenciales locales. (b) `test_demo_mode.py::TestDemoNormalMode::test_prerender_all_presets` — timeout de 10 s para prerenderizar 8 presets con DSP real; la máquina no llega | Tests | Deuda técnica |
| 32 | **La sesión sigue sin sobrevivir al redeploy aunque el audio ya no se pierda** (descubierto al resolver #30): `uploads/sessions.json` es un dict en memoria + archivo en disco efímero, así que en Railway #30 devuelve 404 con "re-run POST /process" en vez de rehidratar. El audio ya es durable; falta el puntero. Sin esto, la rehidratación de #30 nunca se ejerce en producción. Precedente en el repo: tabla `dsp_jobs` en Supabase (ver #29). Decisión de diseño pendiente del usuario | Backend/Docs | Pendiente — bloquea el valor de #30 |
| 33 | **La suite de tests escribía WAVs REALES en el bucket de producción** (descubierto al resolver #30): al subir los masters a R2, ~40 módulos de test que masterizan dejaron de necesitar stub y pasaron a hacer PUT de verdad contra el bucket de producción usando las credenciales de `apps/audiomind/.env`. Medido: `pytest tests/test_demo_mode.py::TestDemoDownload` (3 tests) subió 4 objetos bajo `masters/`. Corregido con `tests/conftest.py` (fixture autouse que hace degradar `storage.get_s3_client()` en vez de tocar la red, + redirección de `SESSION_FILE`); verificado 0 objetos nuevos después del fix. Sin `conftest.py` esto se reintroduce en el próximo módulo nuevo | Tests/Infra | **Resuelto** (piden decisión: borrar los 4 objetos de prueba) |

---

## 8. Documentación: dónde está todo

**Canónica/vigente** (`docs/reference/`, `docs/runbooks/`, `docs/manual/`, `docs/evidence/`): índice central en `docs/README.md` — specs de implementación (valores DSP exactos), COMPLIANCE_PHASE1, DSP_INDUSTRY_REVIEW, DESIGN, SETUP/DOCKER/DEPLOY, USER_MANUAL, UX_MAP, evidencias de benchmark.

**Histórica** (`docs/archive/`): integración, HumanMidi removal, workplan, plan original.

**Local-only (excluida de git, `.git/info/exclude`)**:

- `docs/proposals/` — 4 PDF de libros (Mixing Engineer's Handbook, The Art of Mixing, Computer Music Tutorial) + `VIABILIDAD_MOTOR_DE_MEZCLA.md`, `VIABILIDAD_MOTOR_ESPACIAL.md`, `PERFIL_VINTAGE_SINTETICO.md`, `PROPUESTA_DIMENSION_POR_NECESIDAD.md`, `PROPUESTA_VOZ_ETEREA_VINTAGE_MOJADA.md`.
- `docs/postmortems/` — `inc-2026-04-22-checkout-5xx.md`.
- `odd/` — documentos de tareas ODD (plan-motor-de-mezcla, mezcla-frontend, preestudio-mezcla/espacial, mix-panel-glass-ux, mezcla-ux-progress, **mix-stem-balance** — T1–T4 hechos) y `mezcla-frontend` CERRADO.
- `.atl/` — skill registry local.

**Memoria Engram** (`brikmaster2027`): conocimiento consolidado del Mix Engine, postmortems, decisiones de arquitectura, auditoría de estado (observación 676) y las features recientes (vocal treatment, stem balance T1–T4; observaciones 714–717).

---

*Documento generado por auditoría read-only del repositorio y actualizado el 23-Sep con la feature Mix Stem Balance (T1–T4). Actualizado el 27-Sep con la remoción del Live Engine. Actualizado el 02-Oct-2026 con el estado real de la infraestructura desplegada (§6.6) y el diagnóstico del defecto async de mezcla (§3.2.1). Los commits y conteos de tests de las §5–6.5 son del estado git verificado el 23-Sep; lo verificado el 02-Oct está marcado como tal en cada punto.*
