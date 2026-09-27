# DEMO_RESOURCE_AUDIT.md — Auditoría de recursos del flujo completo WaveAI

> **Estado:** auditoría COMPLETA (mediciones reales locales). Objetivo: dimensionar un deploy DEMO EN VIVO con presupuesto ≈ $0.
> **Fecha de medición:** 2026-09-10 · **Máquina local:** AMD Ryzen 5 7520U (4C/8T) · 15.6 GB RAM · Windows 11 · Python 3.12 (venv uv) · uvicorn single-process.
> **Método:** backend real levantado con `uvicorn audiomind.main:app` (mismo entrypoint que prod), flujo HTTP real, monitoreo del proceso real (pid hijo del shim uv) vía métricas Windows nativas/ctypes sin psutil. Sin cambios de código, sin optimizaciones, sin commits.

---

## 1. Resumen ejecutivo

**Objetivo:** dimensionar un deploy DEMO EN VIVO con presupuesto ≈ $0, midiendo el flujo REAL (no unit tests). Se preservó el comportamiento exacto (cero cambios de código, cero optimizaciones, cero commits). Todas las mediciones con el backend real (`uvicorn audiomind.main:app`) en AMD Ryzen 5 7520U / 15.6 GB RAM / Windows 11.

**Hallazgos que gobiernan la decisión:**

1. **El flujo Studio dispara prerender de 8 presets tras cada upload — es la causa dominante de costo (CPU-time ~6×, wall ~6×, disco 8× vs un solo master) pero NO de RAM (~1.25×).** El Studio NO espera 8/8 (solo análisis + un `mastered_path`); el prerender es optimización backend, no contrato.
2. **RAM real pico por pipeline: 1.95 GB (45 s) → 6.1 GB (3.5 min stateless) → 11.88 GB (7 min prerender).** El pico es intra-preset (buffer oversampleado float64 16×/8× del preset más pesado), liberado por `gc.collect()` entre presets. La RAM no escala con el número de presets, pero SÍ con el overlap (escenario B: 3.23 GB en cortos; ~20 GB estimado en largos → OOM).
3. **Tiempo de procesamiento en esta máquina:** 45 s de audio → ~15 s/preset (prerender 123 s en 8/8); 3.5 min → ~46 s/preset (366 s); 7 min → ~145 s/preset promedio (1157 s, con cola por preset de 61-290 s NO lineal). Un master stateless: 22 s (45 s audio) / 33-40 s (3.5 min).
4. **Almacenamiento sin TTL:** cada sesión deja 1 upload + 8 masters PCM24 = factor 12× sobre el input; tras reiniciar el backend los WAV quedan huérfanos y se duplican. Indicio de retención de RAM entre jobs consecutivos (end RSS 826→1418 MB) — a validar.
5. **Concurrencia:** single-flight NO existe; el overlap `/process` durante prerender es real y no está controlado. Máximo teórico: 3 pipelines pesados (1 prerender + 2 on-demand).
6. **Instancia mínima honesta:** 16 GB RAM para flujo Studio con tracks de 3.5-7 min; 8 GB solo con tracks cortos (≤ ~90 s) o presets livianos; 2-4 GB OOM en casi todo.

**Recomendación de máquina demo $0 (sin tocar código):** 16 GB RAM / 4 vCPU / ~20 GB disco efímero, 1 usuario concurrente, tracks demo ≤ 3.5 min, con limpieza manual de uploads/outputs entre demos. Estimar el costo en un host económico según la tabla de la sección 18.

## 2. Arquitectura real encontrada

- **Studio (apps/studio):** Next.js 16 + React 19 + TS + Tailwind 4. Llama a FastAPI **directo por CORS** (`NEXT_PUBLIC_API_URL || http://localhost:8000/api`), NO por proxy Next. El rewrite `/api/*` de `next.config.ts` existe pero ningún fetch lo usa.
- **Backend (apps/audiomind):** FastAPI single-process, sesiones en memoria + espejo JSON en disco (`uploads/sessions.json`). Entrada máxima 50 MB (`AUDIOMIND_MAX_FILE_SIZE_MB`). Solo acepta `.wav` y `.mp3`.
- **Contratos (packages/contracts):** `live_params.schema.json` es fuente de verdad del protocolo Live (solo genera tipos TS). `mastering_settings.schema.json` se genera desde el modelo Pydantic. Nada de esto se valida en runtime.
- **Convex (Scaffolding dormido):** `convex/` existe pero el provider es passthrough; 0 imports en `src/`. No participa en el flujo real.
- **e2e:** un único spec `master_to_live.spec.ts`, dirigido contra `localhost:3000` + backend `:8000` aparte.

**Procesamiento por capa:**
| Capa | Procesamiento | ¿Red? |
|---|---|---|
| Browser · Studio | UI, upload XHR, polling progreso, WaveSurfer streaming, Live Engine Web Audio | Sí (upload/master) |
| Browser · Live Engine | **100% Web Audio local**: knobs→nodos, meters→AnalyserNode local (rAF), reverb IR generados proceduralmente, recorder local | **Cero red durante Live** |
| Backend · audiomind | análisis (librosa), mastering DSP 13 etapas, prerender 8 presets, mediciones LUFS/TP/DR, QC | — |
| Almacenamiento | uploads/ + outputs/ en disco local (ephemeral), persiste `sessions.json` | — |

## 3. Endpoints del flujo (los que usa Studio)

| Método | Ruta | Quién la sirve | Uso |
|---|---|---|---|
| POST | `/api/upload` | FastAPI | Sube WAV/MP3, crea sesión, dispara análisis + prerender |
| GET | `/api/session/{id}` | FastAPI | Polling de progreso/estado (Studio cada 500 ms) |
| POST | `/api/session/{id}/process?preset_id=` | FastAPI | Masteriza (o sirve caché prerender) |
| GET | `/api/session/{id}/audio/original` | FastAPI | WAV original (streaming) |
| GET | `/api/session/{id}/audio/mastered` | FastAPI | Master (streaming) |
| GET | `/api/session/{id}/prerender/status` | FastAPI | Estado 8/8 |
| GET | `/api/session/{id}/prerender/{preset_id}` | FastAPI | Sirve master prerender |
| GET | `/api/session/{id}/download/{wav\|mp3}` | FastAPI | Descarga blob |
| GET/POST | `/api/license/status`, `/activate` | FastAPI | Gateo (X-License-Key; dev sin key = abierto) |
| POST | `/api/master` | FastAPI | Stateless: descarga `audio_url`, analiza, procesa, responde (NO lo usa Studio hoy; útil para medir job unitario) |
| POST | `/voz/*` | Next route handlers | ElevenLabs (externo) — NO es audiomind |

**Transferencias de red del WAV:** browser → FastAPI (upload §); FastAPI → browser (mastered stream §); **el WAV master no cruza Next.js** (CORS directo). En `POST /api/master`, el archivo viaja otra vez por red (backend → backend si la URL es remota).

## 4. Flujo Upload → Master → Live (real)

```
DropZone (.wav/.mp3 ≤50MB)
  └─ handleFileSelected → uploadAudio() → POST /api/upload        [XHR con progreso]
       ├─ backend: guarda uploads/{session_id}.wav
       ├─ backend: ANALYZING → analyze_audio() (librosa) en background
       ├─ backend: al terminar análisis → _prerender_all_presets() → cola 1 worker → 8 presets DSP → outputs/ {session}_preset_{id}.wav
       └─ Studio: waitForAnalysis() → GET /session/{id} cada 500 ms hasta "analysis"
  └─ (auto) handlePresetSelect / "Procesar" → POST /session/{id}/process?preset_id=
       └─ backend: sirve _prerender_cache si completó; si no, procesa on-demand (watchdog Studio 10 min)
       └─ Studio: useProcessingProgress → GET /session/{id} 500 ms
  └─ Player A/B: WaveSurfer → GET audio/original | audio/mastered   (streaming)
  └─ Live Engine: fetch(audio/mastered) → decodeAudioData UNA vez → AudioGraph Web Audio
       └─ knobs → setTargetAtTime (local) · meters → AnalyserNode local · cero polling/WS
```

## 5. Recursos consumidos por componente

| Componente | CPU | RAM | Disco | Red | Notas |
|---|---|---|---|---|---|
| Studio (browser) | UI + decodificación WAV (WaveSurfer/Live) | bundle + buffers de audio decodificados | cache session en localStorage (solo id) | upload + mastered + polling 500ms | Live 100% local; cero red en Live |
| audiomind (backend) | DSP dominante (análisis + 8 presets) | ver sección resultados — **picos de 2.4–10.2 GB** | uploads/ + outputs/ sin cleanup | upload ingress + mastered egress | single-process; 1 worker prerender + 2 worker DSP |
| storage/transfer | — | — | ~53–56 MB por preset de salida | WAV master (≈12 MB/min a PCM24) | ver §13 |
| Live Engine | cliente | cliente | — | 1 fetch inicial del master | sin backend |

## 5.1 Dependencias de UX de los 8 masters (investigación §2 — evidencia)

**Conclusión: el Studio NO exige 8/8. Ningún consumidor necesita más de UN master.**

| Consumidor | ¿Cuántos masters? | Evidencia (apps/studio/src) |
|---|---|---|
| Player A/B/C (WaveSurfer) | **1** (`masteredUrl`) | `page.tsx:1428-1430, 1616-1618`: `session.mastered_path ? getAudioUrl(id,"mastered") : null`. Player solo monta master si hay URL |
| Live Engine | **1** (`masterAudioUrl` → decode) | `page.tsx:1849`; `LiveView.tsx:59-77` un fetch+decode; gate `session?.mastered_path` (`1840-1847`) |
| Download WAV/MP3 | **1** (master de la sesión) | `page.tsx:826-844`, `client.ts:498-511` — sin preset_id |
| presetCacheRef | Como máximo 8 claves, opcional (conveniencia) | `page.tsx:707, 744-753` — NO es requisito |
| Referencia Crudo | 1 render on-demand (ajeno a los 8) | `client.ts:253-266` |

**¿Espera el Studio 8/8? NO.**
- `waitForAnalysis` retorna apenas existe `s.analysis` (`page.tsx:163`) — ni siquiera espera que el prerender arranque.
- La UI útil aparece justo después (`setCurrentView("mastering")`, `page.tsx:574-576`).
- El único gate funcional es `session.mastered_path` (master individual).
- **Cero referencias a "prerender" en apps/studio** (grep verificado): el Studio desconoce el 8/8; solo reenvía `preset_id` en `POST /process` (`page.tsx:769`).

**¿Se podría usar el primer master antes de 8/8? SÍ, y ya ocurre.** `POST /session/{id}/process` (mastering.py:440-458) sirve el preset del cache si ese preset completó (los otros 7 pueden estar pending) y si no, procesa on-demand ese único preset (`mastering.py:460-552`) con progress real. El prerender es **optimización backend, no contrato de producto**.

## 6. Metodología de medición

- `audit_runner.py`: levanta uvicorn real en :8123 con env `AUDIOMIND_LICENSE_KEY=""`, espera /health, sube fixture real, espera análisis y prerender 8/8 vía endpoint, mide monitor de proceso real (RSS/cpu_times/threads vía ctypes Windows, sampling 0.2 s, integración exacta con timestamps), disco (uploads/ + outputs/), y reporta por escenario.
- Flujo de Studio real: POST /upload → GET /session → espera 8/8 prerender.
- Flujo job unitario: POST /api/master (descarga URL de fileserver local → analiza → procesa → responde) — el flujo que costaría UN master custom.
- Concurrencia: 2 POST /api/master paralelos (mismo proceso, `_dsp_executor` max_workers=2).
- DSP directo: llama `process_audio()` en subprocess sin HTTP para el peor caso float32.
- Fixtures generados localmente (sin copyright): A=45 s / B=210 s / C=420 s, señal sintética musical con transientes, PCM16/MP3 320k.
- No se instaló nada; psutil ausente → ctypes nativos.

### 6.1 Nota de medición — el shim uv (importante para interpretar RAM)

El `.venv` de audiomind arranca con un python lanzador de `uv` que crea un **proceso hijo real** (`%APPDATA%\uv\python\...`). Todo el DSP corre en threads **dentro de ese hijo**. Si se mide el shim (5 MB), los números parecen absurdamente bajos; los picos de este informe son del **proceso hijo real** (medido por PID resuelto a máximo RSS del árbol). Un proceso hijo por servidor — el RSS reportado ES el del proceso Python completo (FastAPI + workers `ThreadPoolExecutor` + numpy/librosa nativas comparten el mismo address space del hijo).

## 7. Resultados TEST A (45 s WAV PCM16 estéreo 44.1 kHz, 7.94 MB)

| Métrica | Valor |
|---|---|
| Duración | 45 s |
| Input | 7.94 MB WAV PCM_16 44100 Hz estéreo |
| Tiempo upload HTTP | 0.5 s |
| Tiempo análisis | ~11.1 s (incluye librosa load + beat_track + features + STFT) |
| Tiempo prerender 8/8 | **123.4 s** (≈15.4 s promedio por preset) |
| Tiempo flujo completo | ~135 s (upload → 8 masters listos) |
| Peak RAM (proceso real) | **2.43 GB** (baseline 64 MB → end 226 MB) |
| Peak CPU | 1.25 cores (DSP single-thread: cola 1 worker) |
| Avg CPU | 0.76 cores · 102.4 core-seconds |
| Output (8 masters) | **95.3 MB** (8 × ~11.9 MB) |
| Disco pico | uploads 7.9 MB + outputs 95.3 MB |

## 8. Resultados TEST B (210 s = 3.5 min WAV PCM16 estéreo 44.1 kHz, 37 MB)

| Métrica | Valor |
|---|---|
| Duración | 210 s (3.5 min) |
| Input | 37.0 MB WAV PCM_16 |
| Tiempo upload HTTP | 0.6 s |
| Tiempo análisis | ~10.1 s |
| Tiempo prerender 8/8 | **366.4 s** (≈45.8 s promedio por preset) |
| Tiempo flujo completo | ~377 s |
| Peak RAM (proceso real) | **10.25 GB** (baseline 64 MB → end 123 MB) |
| Peak CPU | 1.69 cores |
| Avg CPU | 0.77 cores · 291.7 core-seconds |
| Output (8 masters) | **444.5 MB** (8 × ~55.6 MB) |
| Disco pico | uploads 37 MB + outputs 444.5 MB |

> ⚠️ En la máquina local de 15.6 GB, TEST B llegó a picos de 10.2 GB de RSS; 2 flujos del mismo tipo en paralelo casi seguro provocarían OOM del contenedor.

### 8.1 Escalado A→B (ítem 5 del detalle de investigación)

| Ratio | Valor | Lectura |
|---|---|---|
| duration ratio | 210/45 = **4.67×** | — |
| processing-time ratio (prerender 8/8) | 366.4/123.4 = **2.97×** | sublineal al raw, pero con 8 presets seriales el *tiempo percibido* crece en bloques de ~46 s/preset |
| per-preset avg | 15.4 s (A) → 45.8 s (B) | aprox. lineal con la duración del audio (45.8/15.4 = 2.97×) |
| peak-RAM ratio | 10246/2433 = **4.21×** | casi lineal con duración (4.67×) — domina el costo del audio en memoria por preset; overhead fijo pequeño relativo |
| output-size ratio | 444.5/95.3 = **4.66×** | lineal exacto (PCM24 por muestra) |

Conclusión parcial: **RAM y output escalan ≈ lineal con la duración**, y el tiempo de prerender ≈ lineal por preset. No hay un overhead fijo enorme por sesión, pero el costo por segundo de audio es alto en sí mismo (8 presets × pipeline completo).

## 5.2 Trazado interno del prerender 8/8 (investigación §1 — evidencia)

**Mecanismo exacto (nada se modifica, solo se documenta):**

```
POST /api/upload (upload.py:21-98)
  └─ guarda uploads/{session_id}{suffix}
  └─ status=ANALYZING → _analyze() en executor por defecto (upload.py:94)
       └─ analyze_audio(): librosa.load OTRA VEZ (analyzer.py:183) → session.analysis
       └─ al terminar: session.status=UPLOADED + _prerender_all_presets() (upload.py:78-88)
            └─ _prerender_cache[session_id] = {preset: {status, progress, output_path,
                 master_result, validation, error}} (mastering.py:180-189)
            └─ submit(_prerender_single_preset) ×8 en _prerender_executor max_workers=1
                 → FIFO serializado (mastering.py:190-196)
                 → _build_preset_params(preset_id): parámetros canónicos, bit depth 24
                 → process_audio(input, output, params, analysis, intensity=1.8, progress_cb)
                 → write outputs/{session_id}_{preset_id}_mastered.wav (PCM_24)
                 → entry["validation"] = validate_master(...) (best-effort, mastering.py:152-161)
```

| Qué se ejecuta por preset | Evidencia |
|---|---|
| Cadena DSP completa de `process_audio` (ningún preset es neutral → los 8 corren el pipeline entero) | mastering.py:138-145; engine.py:761 |
| Lectura del WAV **de nuevo por preset** (AudioFile completo, float32) | engine.py:717-719 |
| Mediciones idénticas al input recalculadas **8 veces**: `measure_true_peak` QC (8× oversampled), sample peak, hard-clip count, `gain_stage`, FFT de bandas (`analyze_band_energies`), `measure_dynamic_range(input)` | engine.py:115, 810, 218-219, 1157 |
| LUFS/TP/LRA/DR **recalculados por preset** sobre el audio procesado (resultado distinto, costo fijo) | engine.py:1100-1180 |
| Reutilizado de `session.analysis` (mismo objeto): solo `detected_genre`/`genre_confidence` (match EQ + smart gate), `is_already_mastered` (factor 0.8), evidencia de gate | mastering.py:142; engine.py:730-733; smart_gate.py:157-173 |
| Config **muerta** en prerender: `eq_bands`, `highpass_hz`, `mono_below_hz` de los presets NO llegan al DSP (EQ usa `[]`, HPF fijo 30 Hz, mono fijo 120 Hz) | engine.py:856, 847, 1085 |
| Numpy costosos por preset (float64): clipper 16× crea `x_up (C,16N)` ≈ **256N bytes** (pico clipper ≈ 4-6 GB para 3 min stereo); limiter 8× ≈ 128N+; meter BS.1770 ≈ 80N × 3 llamadas | clipper.py:128-140; truepeak.py:110-146 |
| ¿Se guarda audio en memoria? NO — solo `output_path` + métricas; `gc.collect()` tras escribir | engine.py:1173; mastering.py:147-148 |

**Riesgo latente medido en código (sobre-suscripción):** con un preset en `in_progress`, `POST /process` NO bloquea — procesa on-demand en `_dsp_executor` (2 workers) en paralelo al hilo de prerender → hasta 3 pipelines pesados simultáneos en el mismo proceso → pico de RAM real puede superar la medición serial (mastering.py:460-552).

## 5.3 Almacenamiento, TTL y cleanup (investigación §6 — evidencia)

- **Formato de salida:** WAV PCM_24 en TODOS los presets (`output_bit_depth=24`, mastering.py:109; `sf.write subtype=PCM_24`, io_write.py:22-26). SR = el del input (same_as_input); canales = los del input.
- **Amplification factor:** input PCM16 → 8 masters PCM24 = **12.0× exacto** (8 × 24/16). Verificado A (95.3/7.94 = 12.0) y B (444.5/37.0 = 12.0).
- **¿Cuándo se eliminan uploads/masters? NUNCA.** No existe TTL/job de limpieza (grep de `unlink|rmtree|cleanup|ttl|expire|prune` → solo borrados puntuales de retry/temp).
- **Tras reiniciar:** sesiones + `session.analysis` sobreviven vía `uploads/sessions.json`; el **cache de prerender y el executor son módulo-level en memoria → se pierden**; los 8 WAV quedan **huérfanos en disco**; el próximo `/process` re-procesa y **duplica archivos** — acumulación indefinida: ~1 upload + ~9-10 outputs por sesión.

## 5.4 Oportunidades de reutilización POTENCIALES (investigación §7 — sin implementar)

Clasificación a nivel de pipeline, con evidencia de dónde está el recálculo:

| Oportunidad | Categoría | Evidencia |
|---|---|---|
| Cachear la decodificación del WAV (leer una vez, compartir float32 entre los 8) | SAFE INFRA OPTIMIZATION | engine.py:717-719 (lectura por preset) |
| Cachear mediciones input-side idénticas (true-peak QC 8×, sample peak, FFT bandas, DR input, gain_stage) | SAFE INFRA OPTIMIZATION | engine.py:115, 218-219, 810, 1157 |
| Correr los 8 presets con 1 decode + feature base | SAFE INFRA OPTIMIZATION (requiere refactor de firma de process_audio) | mastering.py:138-145 |
| Limitar el prerender a 1-2 presets y servir el resto on-demand | POSSIBLE BEHAVIOR CHANGE (UX: primer preset en cache 1-2 s vs ~46 s; demo$0) | mastering.py:440-552 |
| Compartir el meter BS.1770 del target entre presets con mismo target LUFS | POSSIBLE BEHAVIOR CHANGE (mide señal distinta — no trivial) | engine.py:310 vs 1100 |
| Reutilizar salida de saturación/limiter entre presets | REQUIRES DSP VALIDATION (cada preset cambia la señal antes) | engine.py:1067-1128 |
| Reducción de oversampling (16× → 8×) o dtype float32 | REQUIRES DSP VALIDATION (cambia el audio; prohibido sin decisión) | clipper.py:42 |

**Ninguna de estas se implementó. El comportamiento actual queda intacto.**

## 8.2 Latencia percibida del Studio (investigación §8 — evidencia)

**El Studio espera UN master, no ocho.** Timeline percibido (gatillos reales en código):

| Evento | Cuándo ocurre | Evidencia |
|---|---|---|
| time to analysis complete | tras upload HTTP + análisis background (poll 500 ms, timeout 90 s) | `page.tsx:155-173` (`waitForAnalysis`, retorna con `s.analysis`) |
| time to first useful UI | inmediatamente después del análisis (`setCurrentView("mastering")`) | `page.tsx:574-576` |
| time to first playable master | click en preset → POST /process → esos ~1-2 s si el preset ya está en cache prerender; si no, todo el DSP on-demand de ESE preset (progress real en overlay) | `page.tsx:710-791`, mastering.py:440-552 |
| time to 8/8 complete | irrelevante para la UX (nadie lo consulta) | cero referencias en Studio |
| time to Live-ready | `session.mastered_path` existente → tab live → 1 fetch+decode | `page.tsx:1840-1849` |

Implicación para la demo: **se puede entregar el primer master en ~1-2 s tras el análisis** si el preset deseado está prerenderizado primero; el costo de 8 presets en serie NO bloquea la UX — pero sí consume CPU/RAM durante minutos después de cada upload (colgando en background). El tiempo percibido dominante es análisis (~10 s) + DSP del primer preset (~46 s en el peor caso on-demand para 3.5 min).

## 8.3 Desglose de memoria — qué significa Peak RAM = 2.43 GB / 10.25 GB (investigación §4)

**Estructura de procesos medida:** el backend uvicorn = 2 procesos Python (shim uv de ~5 MB + hijo real). El DSP corre en *threads* `ThreadPoolExecutor` del loop (prerender 1 worker, dsp 2 workers) **dentro del hijo real**. No hay multiprocessing, no hay workers uvicorn separados. Por lo tanto:

- **RSS reportado = RSS del proceso Python hijo real completo** (interpreter + numpy/librosa/pedalboard nativas + todos los arrays de trabajo compartidos por threads del mismo proceso).
- No hay "RAM de sistema extra" de otros procesos significativos (el fileserver http local usado por /api/master es de ~5 MB y externo a la medición del backend; el shim es trivial).
- El pico se mide **durante el prerender 8/8** (el monitor arranca antes del upload y termina tras el 8/8). La fase de análisis sola es barata (~64 MB baseline → vuelve a ~123-226 MB tras completar todo).

**Hipótesis de quemón — CONFIRMADA por trazado de código (§5.2):**
- La señal se procesa en float32 pero los oversamplers suben a **float64**; el clipper oversamplea **16×** y el limiter **8×**.
- TEST B (210 s, N = 9.26M muestras/canal): el array `x_up` del clipper = 2ch × 16 × 9.26M × 8 B ≈ **2.37 GB**; con `y_up` y down-sampling simultáneos el pico del clipper ronda **4-6 GB**; el limiter 8× suma ~128N+ (~6.5 GB c/u en series); el meter BS.1770 aporta ~0.5 GB transitorio por llamada y se llama 3× por preset.
- El pico ocurre **durante el preset con saturación/soft_clip** (fuego, cinta, cinematico, empuje) y en el lookahead del limiter 8×, no en análisis ni en escritura.
- Confirmado también: **no hay acumulación retenida** — `gc.collect()` tras cada preset (engine.py:1173) y el RSS final (~123-226 MB) es solo el footprint de imports. El pico es intra-preset, no suma de 8.

> Hallazgo de medición (§6.1): el venv uv crea un shim + hijo. Si algún monitoreo externo mide el shim (p. ej. docker stats sobre el PID del contenedor puede no ver los picos si el proceso interno se reporta distinto), subestimaría 10× la RAM real. En contenedor Linux Docker esto NO aplica (python directo, no shim uv) — la medición local con uv es un artefacto de la máquina de desarrollo, los órdenes de magnitud y el scaling A→B son lo portable.

## 9. Resultados TEST C (420 s = 7 min MP3 320k estéreo, 16.8 MB)

| Métrica | Valor |
|---|---|
| Duración | 420 s (7 min) |
| Input | 16.8 MB MP3 320k (decodificado a PCM float en el pipeline) |
| Tiempo upload HTTP | 0.3 s |
| Tiempo análisis | ~23.3 s (MP3: decode + librosa; más lento que WAV ~10-11 s) |
| Tiempo prerender 8/8 | **1157.2 s (~19.3 min)** |
| Desglose por preset (acumulado desde el inicio del prerender) | universal **91.0** · fuego **174.8** · claridad **418.9** · cinta **480.2** · natural **724.6** · espacial **785.5** · cinematico **867.7** · empuje **1157.2** s |
| Intervalo por preset | universal 91.0 · fuego 83.8 · claridad **244.1** · cinta 61.3 · natural **244.4** · espacial 60.9 · cinematico 82.2 · empuje **289.5** s |
| Tiempo flujo completo | ~1181 s (~19.7 min) |
| Peak RAM (proceso real) | **11.88 GB** (baseline 0.0 por muestra inicial vacía; end 122.5 MB) |
| Peak CPU | 2.56 cores |
| Avg CPU | 0.60 cores · 704.6 core-seconds |
| Output (8 masters) | **889.2 MB** (8 × ~111.15 MB) |
| Disco pico | uploads 16.8 MB + outputs 889.2 MB |

> **No uniformidad de presets (hallazgo):** los intervalos por preset oscilan 61-290 s. Los picos de costo (claridad +244 s, natural +244 s, empuje +290 s) coinciden con presets que mantienen saturación/loudness activos — el soft_clip 16× no siempre toma el null-path (clipper.py:131-135): cuando la señal supera el knee, dispara el oversample 16× float64 completo. Esto explica por qué el costo por preset NO es simplemente proporcional a la duración: depende del contenido tras el targeting y de cuáles etapas se activan.

## 9.1 Escalado A→B→C (investigación §5 — completo)

| Ratio | A→B (45→210 s) | B→C (210→420 s) | A→C (45→420 s) |
|---|---|---|---|
| duration | 4.67× | 2.00× | 9.33× |
| prerender time 8/8 | 2.97× (123→366 s) | **3.16×** (366→1157 s) | 9.38× |
| per-preset avg | 2.97× (15.4→45.8 s) | 3.16× (45.8→144.7 s) | 9.40× |
| peak RAM | 4.21× (2.43→10.25 GB) | **1.16×** (10.25→11.88 GB) | 4.89× |
| output size | 4.66× (95.3→444.5 MB) | 2.00× (444.5→889.2 MB) | 9.33× |
| CPU core-seg | 2.85× (102.4→291.7) | 2.42× (291.7→704.6) | 6.88× |

**Lectura corregida vs §8.1:** el tiempo de prerender NO es lineal puro con la duración — de 45 s a 420 s crece ~lineal en el agregado (9.4× para 9.33× de duración) pero la RAM es **sublineal** en el tramo largo (10.25 → 11.88 GB para el doble de duración). Conclusión robusta:

- **RAM pico por pipeline ≈ techo de ~12 GB** para tracks de 3.5-7 min reales (el pico lo domina el buffer oversampleado del preset más pesado, no la suma de presets; `gc.collect()` entre presets acota la acumulación). Para tracks ≥ ~3.5 min, dimensionar con **~12 GB por pipeline** es la cifra honesta de peor caso.
- **Tiempo ≈ lineal con la duración** (~144.7 s por preset promedio para 7 min; ~1 s de prerender por ~2.9 s de audio en promedio agregado).
- **Output exactamente lineal** (PCM24: 12.9 MB/min por master × 8).

## 10. Jobs consecutivos (mismo mastering 3× secuencial, `seq-master 3`, B 210s fuego)

| Job | Request | Peak RAM | End RSS | Avg CPU |
|---|---|---|---|---|
| 1 | 40.5 s | 5853.6 MB | 826.5 MB | 0.77 cores |
| 2 | 33.0 s | 6046.3 MB | 970.0 MB | 0.35 cores |
| 3 | 33.0 s | 6132.8 MB | 1418.6 MB | 0.24 cores |

- Métricas idénticas en los 3 jobs (LUFS -12.0, TP -2.51, crest 11.55) → pipeline determinista.
- Disco: uploads 111.1 MB (3 × 37 MB descargados por stateless) + outputs 166.7 MB (3 × 55.6 MB) = **277.8 MB por 3 jobs**.
- **Indicio de retención de memoria entre jobs:** end RSS crece 826 → 970 → 1418 MB sin volver al baseline (~234-367 MB post-job). Puede ser fragmentación/cachés numpy o trabajo de cierre del request capturado por el muestreo; NO es un leak probado. **A validar en sesiones largas**: si el patrón persiste, una instancia pequeña acumularía RAM durante horas de uso continuo.
- Importante: el job stateless de 210 s pica **~6 GB**, NO 10.25 GB — el pico del prerender 8/8 lo dispara el preset más pesado (empuje/cinematico/natural), no el pipeline individual. El stateless (fuego) es más liviano en RAM que el peor preset del prerender.
- Video de referencia: ~33-40 s de wall por master de 3.5 min en esta máquina (1 worker DSP; 3.5× más rápido que el tiempo real del audio).

## 11. Concurrencia ×2 — resultados reales

### Escenario A: 2 canciones distintas simultáneas (`conc-master-two`, A_45s + D_45s)

| Métrica | Valor |
|---|---|
| Wall total | **28.6 s** (job D completó 18.9 s, job A 28.6 s — solapados) |
| Peak RAM process tree | **2282 MB** (baseline 62 → end 367 MB) |
| RAM total del sistema | 15.6 GB (15605 MB) — sin swap/OOM |
| Peak CPU | **3.12 cores** (→ **SÍ corrieron simultáneamente**: 2 pipelines CPU-bound; un solo pipeline pico ~1.2-2.5 cores) |
| CPU core-seg | 25.7 |
| Ambos DSP simultáneos | ✅ Sí — evidencia: peak CPU 3.12 cores + wall 28.6 s < suma secuencial (~40 s+); ambos rc=0, LUFS -12.0 |
| Output en disco | 2 × 11.9 MB (23.8 MB) |

> **Hallazgo clave:** 2 jobs paralelos NO duplicaron la RAM (2282 MB vs 1951-2433 MB de 1 solo). El pico de RAM es intra-preset (el buffer oversampleado del preset más pesado activo), el GC libera entre etapas, y los picos de los dos jobs no coinciden en el muestreo de 0.2 s. La RAM escala con el **pipeline más pesado activo**, no con el número de pipelines — hasta que los oversamplings coinciden (escenario B muestra el techo real del overlap).

### Escenario B: /process de un preset mientras el prerender procesa ESE preset (`proc-during-prerender`, A_45s fuego)

| Métrica | Valor |
|---|---|
| Disparo | a los 21.2 s del flujo, cuando `fuego` pasó a `processing` en prerender |
| POST /process?preset_id=fuego | respondió en **18.6 s** con `completed` (procesó on-demand — no cache) |
| Peak RAM process tree | **3232 MB** (el pico MÁS alto medido con A_45s: 2.43 solo → 2.28 paralelo → **3.23 overlap**) |
| Peak CPU | 1.94 cores |
| CPU core-seg | 109.7 |
| Prerender continuó | ✅ completó 8/8 en 84.6 s mientras el POST corría (los 2 pipelines coexistieron) |
| Deduplicación/single-flight | ❌ NO existe — el backend ejecutó el preset en `_dsp_executor` mientras el prerender corría ese mismo preset |
| Output en disco | 9 archivos (8 prerender + 1 copia `_mastered.wav` → 107.2 MB) |

> Confirmado empíricamente: el overlap real eleva la RAM por encima del pico serial (+790 MB vs TEST A) pero NO la duplica (3.23 GB vs ~4.8 GB estimado peor caso). El límite real del overlap con tracks cortos. **Para tracks de 3.5 min el overlap estimado = 10.25 GB (prerender) + 10.25 GB (on-demand) ≈ 20 GB → OOM en 15.6 GB: NO se forzó por seguridad (decisión del usuario).**

### Escenarios medidos (diseño previo a la ejecución, ver resultados arriba)

| Escenario | Fixture | Cómo se dispara | Pico estimado | ¿Seguro en 15.6 GB? |
|---|---|---|---|---|
| A) 2 canciones distintas simultáneas | A_45s.wav + D_45s.wav | `conc-master-two` — 2 POST /api/master paralelos (stateless) | ~2 × 2.4 GB ≈ 4.8 GB peor caso | ✅ Sí (margen > 10 GB) |
| B) /process de un preset mientras el prerender procesa ESE preset | A_45s.wav, preset fuego | `proc-during-prerender` — sube, espera que `fuego` pase a `processing` en `/prerender/status`, entonces dispara `POST /process?preset_id=fuego` | ~2 × 2.4 GB ≈ 4.8 GB peor caso | ✅ Sí (A_45s) |
| B con B_210s (track 3.5 min) | B_210s.wav | el mismo disparo | ~2 × 10.25 GB ≈ **20 GB** | ❌ **NO se ejecuta** — supera la RAM física (15.6 GB); se documenta por estimación |

> Decisión explícita del usuario y del runner: **no se fuerza el escenario B con tracks largos** — el pico estimado de 20 GB puede poner en riesgo la máquina (swap/OOM del sistema). Se mide B con A_45s y se extrapola con el scaling §8.1 (RAM ≈ lineal con duración).

### Deduplicación / single-flight — ¿existe actualmente? **NO.**

Evidencia de código (mastering.py):
- `_prerender_executor = ThreadPoolExecutor(max_workers=1)` (mastering.py:77) — serializa los 8 presets.
- `_dsp_executor = ThreadPoolExecutor(max_workers=2)` (mastering.py:71) — hasta **2 jobs on-demand en paralelo**.
- `POST /session/{id}/process` con preset: si el preset está `in_progress`/`pending` en el cache de prerender, **NO espera ni deduplica** — cae al procesamiento on-demand (mastering.py:460-552) ejecutando OTRO pipeline pesado mientras el prerender sigue con ese mismo preset.
- No existe ningún semáforo/single-flight por sesión ni por preset: el solapamiento prerender+on-demand es real y no está controlado.

### Máximo teórico de pipelines DSP simultáneos

| Fuente de pipeline | Límite (executor) | Máx simultáneos |
|---|---|---|
| Prerender 8/8 (una sesión) | 1 worker | 1 |
| POST /process on-demand | `_dsp_executor` 2 workers | 2 |
| POST /api/master stateless (on-demand) | `_dsp_executor` 2 workers (compartido con /process) | (comparte los 2) |
| Análisis (`loop.run_in_executor` default) | sin límite propio | 1 por sesión activa |
| **Total teórico peor caso (1 sesión + 1 job)** | — | **3 pipelines DSP** (1 prerender + 2 on-demand) |

En la práctica el peor caso real alcanzable con el flujo Studio es: **2 pipelines** (1 prerender + 1 /process on-demand del mismo preset) — y eso es exactamente el escenario B. Con 2 usuarios simultáneos: 2 prerenders (serializados por el pool de 1 → NO se suman) + 2 on-demand → pico dominado por el pipeline más pesado activo; ambos usuarios no pueden tener prerender simultáneo pesado porque el pool los serializa — pero 2 on-demand de tracks largos SÍ pueden coincidir.

### Riesgo de OOM por instancia (validado con mediciones reales)

Picos reales medidos: solo 1 job 45 s = 1.95 GB · 1 job 210 s stateless = 6.1 GB · prerender 8/8 45 s = 2.43 GB · prerender 8/8 210 s = 10.25 GB · prerender 8/8 420 s = 11.88 GB · overlap (45 s) = 3.23 GB.

| Instancia | 1 job 45 s | 1 job 3.5 min (stateless) | Flujo Studio 45 s | Flujo Studio 3.5 min | Overlap 45 s | Overlap 3.5 min |
|---|---|---|---|---|---|---|
| **2 GB** | ❌ OOM (1.95 + OS) | ❌ OOM | ❌ OOM (2.43) | ❌ OOM | ❌ OOM | ❌ OOM |
| **4 GB** | ✅ (1.95 + OS ≈ 3) | ❌ OOM (6.1) | ⚠️ Marginal (2.43 + OS ≈ 3.5) | ❌ OOM | ⚠️ Marginal (3.23) | ❌ OOM |
| **8 GB** | ✅ | ✅ (6.1 + OS ≈ 7) | ✅ | ❌ OOM (10.25) | ✅ (3.23) | ❌ OOM (~20) |
| **16 GB** | ✅ | ✅ | ✅ | ✅ (10.25) | ✅ | ❌ OOM (~20) |

> Conclusión de la tabla: **la instancia mínima honesta para el flujo Studio real (que dispara prerender 8/8) es 16 GB** si se aceptan tracks de 3.5-7 min; 8 GB solo si se limitan tracks a ≤ 45-90 s o se acepta OOM en tracks largos. El overlap (escenario B) con tracks largos OOM incluso en 16 GB — mitigación natural: el usuario ONE a la vez en demo.

## 11.2 DSP directo — un único preset completo (ejecutado)

### Medición 1: `engine-direct A_45s.wav` — DSP puro en subprocess SIN análisis (`process_audio` directo, intensidad default 1.0)

| Métrica | Valor |
|---|---|
| Duración input | 45 s |
| Tiempo wall | 6.4 s |
| Peak RAM (subprocess) | 208 MB |
| Peak CPU | 7.16 cores (numpy/pedalboard sueltan el GIL; usa los 8 hilos) |
| CPU core-seg | 6.2 |
| Output | 11.9 MB (PCM24) |
| LUFS result | -12.0 / TP -2.67 |

> ⚠️ **Este número NO es representativo del one-master del flujo real.** El call va sin `analysis_result` y con `intensity_multiplier=1.0` (el prerender usa 1.8), y la señal sintética activa los **null-paths** del soft_clip/limiter. Es útil para el piso mínimo del DSP, NO para dimensionar.

### Medición 2: `solo-master A_45s.wav` — UN job `POST /api/master` REAL (descarga + análisis + DSP con intensidad 1.8 = camino idéntico al stateless de prod)

| Métrica | Valor |
|---|---|
| Duración input | 45 s |
| Request total | **22.2 s** (descarga + análisis ~8-10 s + DSP fuego) |
| Peak RAM (proceso servidor) | **1951 MB** |
| Peak CPU | 1.19 cores |
| CPU core-seg | 17.2 |
| Output | 11.9 MB (PCM24, 1 archivo) |
| LUFS result | -12.0 |

> Este es el número honesto de "one master": el camino completo que paga un usuario por UN solo preset masterizado.

## 11.3 Comparación real Studio upload vs ONE master (medido)

| Métrica | Studio upload (TEST A real: análisis + prerender 8/8) | ONE master (solo-master A_45s real) | Ratio |
|---|---|---|---|
| CPU-time core-seg | 102.4 (prerender completo; con análisis ~113) | 17.2 | **~6.0-6.6×** |
| Tiempo wall | ~135 s flujo completo / 123.4 s solo prerender | 22.2 s | **~6.1×** (135/22.2) |
| Disco retenido | 95.3 MB (8 masters) | 11.9 MB (1 master) | **8.0×** |
| Peak RAM | 2.43 GB (prerender) | 1.95 GB | **1.25×** |

> Lectura final confirmada con medición: el prerender de 8 multiplica **CPU-time ≈ 6×, wall ≈ 6×, disco = 8×** pero **RAM solo ≈ 1.25×** (el pico es del pipeline más pesado activo, liberado por `gc.collect()` entre presets; se suma en overlap — escenario B: 3.23 GB). La RAM no es el costo del prerender; el costo es CPU-time/wall/disco.

## 12. Network / transferencia (cálculo por mastering)

| Tramo | Tamaño |
|---|---|
| Browser → backend (upload) | = input (TEST A 7.9 MB · B 37 MB · C 16.8 MB) |
| Backend → browser (mastered) | = un master (≈11.9 MB/A · 55.6 MB/B · ~111 MB/C a PCM24) |
| Backend → browser (original) | = input (re-streaming si el usuario reproduce Original) |
| Descarga blob | = un master (≈55–111 MB para 3.5–7 min) |

- **¿Next.js proxya el WAV?** NO — el browser habla directo a FastAPI (CORS). `NEXT_PUBLIC_API_URL` debe apuntar al backend.
- **¿Object storage?** NO — disco efímero del contenedor (uploads/ + outputs/), más espejo `sessions.json` en uploads si hay volume.
- **El WAV cruza servicios:** upload 1× (ingress), master 1× (egress), original 1× si se reproduce. Con el flujo session (Studio), el backend genera los 8 masters al disco y sirve 1; con `/api/master` stateless, ingresa por red remota 1× y egresa 1×.

## 13. Archivos temporales y almacenamiento

- `uploads/`: input + `sessions.json`.
- `outputs/`: 8 masters por sesión (prerender) + masters de sesión.
- **Sin TTL/cleanup:** nada elimina uploads ni outputs automáticamente. Se acumulan por sesión/job.
- Tras reiniciar backend: sesiones en memoria se pierden PERO `sessions.json` las restaura si el volume sobrevive; los masters en outputs quedan (no se borran). Sin volume, uploads/outputs efímeros mueren con el contenedor.
- Factor de amplificación (TEST A): 7.94 MB input → 95.3 MB outputs persistentes = **12.0×** (debido a 8 masters PCM24).
- ¿Por qué cada output es ~11.9 MB para 45 s? 45 s × 44100 × 2ch × 3 bytes (PCM_24) = 11.91 MB. La salida usa 24-bit mientras la entrada era 16-bit → más del doble por muestra.
- TEST A amplification factor: **95.3 MB / 7.94 MB = 12.0×** (8 masters PCM24 frente a 1 WAV PCM16 de entrada).
- TEST B: 444.5 / 37.0 = **12.0×** — consistente: el factor es 8 master × (24/16 bits) = 12× exacto.
- Tamaño del master unitario (scaling): ≈ 12.9 MB por minuto de audio (PCM24 44.1k estéreo: 60×44100×2×3 ≈ 15.9 MB/min real; verificado 11.9 MB/0.75 min = 15.9 MB/min ✓).

## 14. Comportamiento del Live Engine

- **100% client-side.** Verificado en código: `useLiveEngine.ts` (AudioContext + graph), `audioGraph.ts` (Source→Filter→Drive→Delay→Reverb→Master→Analyser), `impulseResponse.ts` (IR procedural), `liveMeterBus.ts` + `LiveMeterDeck.tsx` (canvas local), `recorder.ts` (MediaRecorder local).
- Knobs → setParams → Web Audio (sin red). Meters → AnalyserNode (sin red). Sin WebSocket, sin EventSource, sin polling en Live.
- Única red al abrir Live: `fetch(masterAudioUrl)` + `decodeAudioData` una vez.
- Live 10 min = **0 requests al backend**; consume solo CPU/RAM del navegador.

## 15. Resultado E2E (master_to_live.spec.ts)

**Estado: FALLA en el paso 4 contra el código actual — no se ejecutó por bloqueo de código, no de infra.**
- El spec (66 líneas, un solo test) navega a localhost:3000, sube `test-audio.wav`, espera `text=Analizando` (5 s visible / 90 s oculto).
- **Breakpoint:** el Studio actual (page.tsx) NO auto-procesa: `physe="upload"` muestra "Subiendo…/Subido — preparando el análisis…", y "Analizando espectro…" solo aparece en `phase==="process"`. El spec nunca clickea un preset ni "Procesar". ⇒ `text=Analizando` nunca aparece ⇒ assert falla.
- Bug adicional: el fallback de fixture del spec usa `cwd: __dirname + '/..'` → resuelve `e2e/e2e/fixtures/...` (inexistente); se salva porque `npm run e2e` corre `e2e:fixtures` antes.
- Playwright (`webServer`) levanta solo el Studio (`localhost:3000`); el backend `:8000` debe levantarse aparte; nada lo levanta automáticamente.
- Requiere backend sin `AUDIOMIND_LICENSE_KEY` (en prod con key, el Studio queda en lock screen: LicenseGuard llama `/api/license/status` al montar).
- **Diagnóstico: problema de código (spec desactualizado vs nuevo flujo sin auto-process), no de infraestructura.** Verificado contra `ProcessingOverlay.tsx` (solo "Analizando" en phase process <30%) y `handleFileSelected`.

## 16. Minimum viable resources (para DEMO $0, sin optimizar)

Basado en mediciones reales, para el flujo Studio real (upload → analysis → prerender 8/8 → 1 master → Live):

| Recurso | Mínimo viable | Justificación medida |
|---|---|---|
| RAM | **16 GB** (flujo Studio con tracks 3.5-7 min) · 8 GB solo tracks ≤ ~90 s | pico 10.25-11.88 GB en prerender 8/8 de 3.5-7 min; 2.43 GB a 45 s |
| CPU | **2 vCPU mínimo, 4 vCPU recomendado** | DSP mayormente single-thread (~1-2.5 cores en flujo real); engine-direct pudo usar 7 cores con numpy puro |
| Disco efímero | **~20 GB** (sin TTL) | 1 sesión 3.5 min = ~482 MB (uploads 37 + 8 masters 445); limpieza manual entre demos |
| Timeout HTTP | **≥ 10 min por request; análisis Studio watchdog 90 s** | prerender 8/8 de 7 min = 1157 s; POST /process on-demand de preset largo ~145-290 s |
| Concurrencia | **1 usuario a la vez** (demo) | overlap prerender+/process OOM en largos; 2 jobs paralelos OK en cortos |
| Red | ~15.9 MB/s efectivo (upload 7.9-37 MB en 0.3-0.6 s local) | WAV master egress ~12-56 MB por master |

## 17. Recommended demo resources

- **VPS/instancia econòmica:** 16 GB RAM · 4 vCPU · 40 GB SSD efímero. (Ej. Hetzner CCX23 ~€5/mes o similar; DO/Railway free no llega — 512 MB-1 GB OOM en el primer upload.)
- **Restricción de demo:** tracks ≤ 3.5 min (o un preset liviano), 1 usuario, limpiar `uploads/`+`outputs/` tras cada demo.
- **Nada de esto requiere cambio de código:** el flujo actual funciona tal cual en esa máquina; la optimización (prerender bajo demanda, cache de decode/features, TTL) es una decisión POSTERIOR a esta auditoría.

## 18. Estimación 1 / 5 / 20 mastering jobs (flujo Studio 3.5 min)

| Escenario | RAM pico (1 a la vez) | CPU-time (core-seg) | Disco retenido (sin TTL) | Wall (serial esta máquina) |
|---|---|---|---|---|
| 1 job (1 sesión 3.5 min) | 10.25 GB | 291.7 | ~482 MB | ~6.3 min |
| 5 jobs | 10.25 GB (serial) | ~1458 | ~2.4 GB | ~32 min |
| 20 jobs | 10.25 GB (serial) | ~5834 | ~9.6 GB | ~2.1 h |

> CPU-time medido: 291.7 core-seg para prerender 8/8 de 3.5 min (TEST B). Si se usa el flujo stateless one-master (33-40 s por 3.5 min), 20 jobs = ~12 min de CPU, disco ~3.7 GB (20 × 37 MB upload + 20 × 55.6 MB output), RAM pico 6.1 GB — mucho más barato que el flujo Studio por sesión. **Esta es la palanca arquitectónica para la demo, no una optimización de DSP.**

## 19. Riesgos encontrados para deployment

1. **RAM no dimensionada:** pico real 2.43 GB (45 s) y 10.25 GB (3.5 min) durante prerender 8 presets en el flujo REAL de Studio. Un contenedor Free tier típico (512 MB–1 GB RAM) **muere con OOM en el primer upload**. El prerender de 8 presets es el villano.
2. **Prerender de 8 presets tras cada upload:** aunque Studio solo reproduce/descarga UN preset al final, el backend procesa 8 DSP completos por canción (cola de 1 worker). Es la causa dominante del tiempo (366 s/3.5 min) y de los picos de RAM (acumulación de buffers float64/float32 por preset).
3. **Sin TTL/cleanup:** 12× amplificación de disco (input → 8 masters + original). 20 maestrías/día ≈ decenas de GB sin limpiar.
4. **e2e roto** contra el flujo actual del Studio (spec desactualizado).
5. **Sesiones en memoria:** un restart del backend sin volume = pérdida de sesiones activas; Studio lo maneja con modal de "servidor reiniciado".
6. **CORS/URL:** `NEXT_PUBLIC_API_URL` debe terminar en `/api` y el backend debe permitir el origin del deploy (lista cors_origins hardcodeada + railway).
7. **Límite 50 MB de input** (config) — un WAV float32 de 5 min ≈ 100 MB ni siquiera entra por /upload.
9. **Sobre-suscripción de pipelines pesados:** si el usuario clickea un preset mientras el prerender lo está procesando (`in_progress`), `POST /process` NO espera — ejecuta DSP on-demand en `_dsp_executor` (2 workers) en paralelo al hilo del prerender → **hasta 3 pipelines float64 pesados simultáneos en el mismo proceso** (mastering.py:460-552), multiplicando el pico de RAM serial (2.4-10.2 GB) por encima de lo medido.
10. **Config muerta en prerender:** `eq_bands`, `highpass_hz` y `mono_below_hz` de los 8 presets NO se aplican (EQ usa `[]`, HPF fijo 30 Hz, mono fijo 120 Hz; engine.py:856, 847, 1085). El carácter EQ real sale de brightness/warmth/transient/compresor — el preset seleccionado no suena exactamente como su `eq_character` sugiere. No es un riesgo de deploy, pero es un hallazgo de convergencia código-vs-producto.

## 20. Qué limita actualmente un deployment gratuito

1. **RAM (crítico):** peak 2.4–10.2 GB en el flujo real del prerender.
2. **Tiempo de cómputo:** 3.5 min de track = ~6 min de prerender + análisis en máquina local; en free tier (CPU compartida) será peor.
3. **Timeout HTTP:** Studio uchá watchdog 10 min por /process; no hay timeout propio en uvicorn.
4. **Disco sin cleanup** → consumo acumulado.
5. **CORS fijo** (hay que agregar el origin del demo).
6. **Un solo worker DSP y un solo worker prerender** → el throughput máximo es 2 masters concurrentes (max_workers=2); con 2 sesiones simultáneas el prerender los serializa.

## 21. Qué NO necesitamos tocar (funciona client-side)

- **Live Engine completo** (knobs/meters/recorder/reverb) — 0 backend.
- **Player A/B streaming** — servido por FastAPI directo; solo necesita egress de audio.
- **Contratos/schemas** — no se usan en runtime.
- **Convex** — dormido; ignorable para la demo.
- **Voz (ElevenLabs)** — externo; no afecta el budget si no se usa.

## 22. Preguntas/mediciones que todavía faltan

- [HECHO] TEST A/B/C (45 s / 3.5 min / 7 min) → §7-9
- [HECHO] Jobs consecutivos ×3 (`seq-master 3`, B 210s) → §10 — pico 5.9-6.1 GB/job, end RSS creciente (826→1418 MB)
- [HECHO] Concurrencia escenario A (A + D 45s) → §11 — pico 2282 MB, SÍ simultáneos (CPU 3.12)
- [HECHO] Concurrencia escenario B (fuego durante prerender, A 45s) → §11 — pico 3232 MB, overlap real; **NO forzado con B 210s (~20 GB estimado)**
- [HECHO] DSP directa (`engine-direct` A_45s: 6.4 s / 208 MB, piso sin análisis) + one-master real (`solo-master`: 22.2 s / 1951 MB) → §11.2
- [HECHO] Comparación Studio upload / one-master (CPU ~6×, wall ~6×, disco 8×, RAM 1.25×) → §11.3
- [HECHO] Desglose temporal por preset (TEST C) → §9
- [HECHO] Dimensionamiento final + tabla WAVEAI DEMO METRICS → §16-18

**Pendientes post-auditoría (NO ejecutados, por decisión del usuario "NO optimices todavía"):**
- Validar retención de RAM entre jobs (sesión larga > 10 jobs) — indicio, no leak probado.
- Prueba de overlap con track 3.5 min (estimado ~20 GB → requiere máquina ≥ 32 GB; no se forzó en esta máquina de 15.6 GB).
- Prueba con C_420s_f32 (float32 7 min, 148 MB, excede límite de upload) — pico estimado ~20 GB → no se forzó.

## 23. Anexos

### Anexo A — Seguridad
- No se muestran claves ni `.env`. Variables relevantes (solo nombres): `AUDIOMIND_LICENSE_KEY`, `AUDIOMIND_*` (config), `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_BASE_PATH`, `NEXT_PUBLIC_REQUIRE_AUTH`, `NEXT_PUBLIC_CONVEX_URL` (inactivo), `ELEVENLABS_*` (voz).

### Anexo B — Hallazgo de medición: el shim uv
- El `.venv` de audiomind usa python de `uv` como lanzador: el `python.exe` del venv arranca un proceso hijo real (`%APPDATA%\uv\python\...`). Todo el DSP corre DENTRO de ese hijo (threads). Medir al shim (5 MB) es engañoso; las mediciones del informe usan el proceso hijo real.
- tareas zombies: matar el shim no mata el árbol (se usa taskkill /T).

---

=== WAVEAI DEMO METRICS ===

Machine used: AMD Ryzen 5 7520U (4C/8T) · Windows 11 64-bit · Python 3.12 (uv venv) — local
OS: Windows 11 (build 26200)
CPU: AMD Ryzen 5 7520U — 4 cores / 8 threads (medida sobre proceso real)
Total RAM: 15605 MB (15.6 GB)

TEST A (flujo Studio, 45 s WAV PCM16)
Audio duration: 45 s
Input size: 7.9 MB (WAV PCM16 44.1k stereo)
Processing time: 123.4 s (prerender 8/8) · flujo completo ~135 s
Peak RAM: 2433 MB
Peak CPU: 1.25 cores
Output size: 95.3 MB (8 masters)
Temp disk peak: 103.2 MB (uploads 7.9 + outputs 95.3)

TEST B (flujo Studio, 210 s WAV PCM16)
Audio duration: 210 s (3.5 min)
Input size: 37.0 MB
Processing time: 366.4 s (prerender 8/8) · flujo completo ~377 s
Peak RAM: 10246 MB
Peak CPU: 1.69 cores
Output size: 444.5 MB (8 masters)
Temp disk peak: 481.5 MB

TEST C (flujo Studio, 420 s MP3 320k)
Audio duration: 420 s (7 min)
Input size: 16.8 MB MP3
Processing time: 1157.2 s (prerender 8/8, desglose por preset 61-290 s) · flujo completo ~1181 s
Peak RAM: 11884 MB
Peak CPU: 2.56 cores · 704.6 core-s
Output size: 889.2 MB (8 masters)
Temp disk peak: 906 MB

SEQUENTIAL JOBS (stateless /api/master, B 210s fuego ×3)
Job 1: 40.5 s · pico 5853.6 MB · end 826.5 MB
Job 2: 33.0 s · pico 6046.3 MB · end 970.0 MB
Job 3: 33.0 s · pico 6132.8 MB · end 1418.6 MB
Memory after jobs: end RSS 1418.6 MB (indicio retención, no leak probado)
Disk: 277.8 MB (uploads 111.1 + outputs 166.7)

CONCURRENCY 2
Escenario A (A_45s + D_45s paralelos): pico RAM 2282 MB · pico CPU 3.12 cores · SÍ simultáneos · wall 28.6 s
Escenario B (process fuego durante prerender, A_45s): pico RAM 3232 MB · pico CPU 1.94 cores · overlap real · POST 18.6 s mientras prerender continuó
Result: sin OOM en 15.6 GB para 45 s; overlap de 3.5 min estimado ~20 GB → NO forzado

NETWORK
Upload MB: TEST A 7.9 · B 37.0 · C 16.8
Download MB: un master ≈ 11.9 (A) · 55.6 (B) · ~111 (C)
Number of file transfers: upload 1× · master egress 1× · original egress 1× (si A/B) · descarga 1×
Does Next proxy audio?: No — browser→FastAPI directo (CORS)
Object storage?: No — disco efímero contenedor + sessions.json

ONE MASTER vs STUDIO (A_45s)
engine-direct (sin análisis): 6.4 s · 208 MB · 11.9 MB out
solo-master stateless (análisis + 1.8x): 22.2 s · 1951 MB · 11.9 MB out
Studio upload (análisis + 8 presets): ~135 s · 2433 MB · 95.3 MB out
Ratios Studio/one-master: CPU-time ~6× · wall ~6× · disco 8× · RAM 1.25×

LIVE ENGINE
Backend requests while manipulating knobs?: No
Backend requests from meters?: No
WebSocket?: No
Polling?: No (el único polling es el progreso de mastering)
Can run after master entirely client-side?: Sí

E2E
master_to_live: FALLA en código actual (spec espera "Analizando" que ya no aparece sin clic en preset) — no ejecutado por bloqueo de código

DEPLOYMENT (flujo Studio sin optimizar)
Minimum RAM: 16 GB para tracks 3.5-7 min · 8 GB solo tracks ≤ ~90 s
Recommended RAM: 16 GB
Minimum CPU: 2 vCPU
Recommended CPU: 4 vCPU
Required temp disk: ~20 GB sin TTL (1 sesión 3.5 min ≈ 482 MB)
Required timeout: ≥ 10 min por request; primer master ~1-2 s si preset cacheado
Safe concurrent mastering jobs: 1 (demo); 2 stateless OK en tracks cortos; overlap /process en largos = OOM incluso 16 GB
OOM risk: 2 GB ❌ · 4 GB ⚠️ cortos · 8 GB ❌ tracks ≥ 3.5 min · 16 GB ✅ serial / ❌ overlap largo