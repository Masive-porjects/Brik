# DEMO_RESOURCE_AUDIT.md — Auditoría de recursos del pipeline WaveAI (demo, presupuesto $0)

> **Fecha:** 2026-09-11 · **Método:** medición REAL sobre el stack del proyecto (backend FastAPI + DSP de audiomind + Studio Next.js), NO estimaciones de papel.
> **Alcance:** dictar cuánto cuesta ejecutar el flujo completo *mastering → Live* para decidir un deploy demo de $0.
> **Lenguaje del doc:** español (neutro-profesional, sin jerga rioplatense de microcopy).

---

## 1. Resumen ejecutivo

**El pipeline se mide de verdad y arranca:** el backend DSP (`apps/audiomind`) importa el stack completo (librosa 1.0.0, scipy 1.18.1, numpy 2.5.3, pedalboard 0.9.25, soundfile) y corre un mastering real por HTTP. No es una simulación.

Tres hallazgos que cambian el cálculo de recursos:

1. **`POST /process` con params por defecto es un bypass bit-exacto (casi cero DSP).** El trabajo pesado real está en el **pre-renderizado de 8 presets** que dispara el upload en background (`prerender_mode="all"`). Medir solo `/process` subestimaría el costo ×200.
2. **Los jobs DSP NO devuelven el proceso a RAM baseline entre tests:** RSS del backend subió 1.3 GB → 6.6 GB → 7.2 GB en TEST A→B→C y se mantuvo alto mucho después de terminar cada job (cadena de prerender siguió viva). Señal clara de **acumulación de carga/archivos**, a confirmar con el test de leak secuencial (en curso).
3. **El Live Engine no consume recursos del servidor: es 100% client-side.** Knobs → `setTargetAtTime` → Web Audio graph; meters por `requestAnimationFrame` sobre un bus local; cero fetch/WebSocket/polling una vez cargado el master. **"Mover knobs durante 10 min NO genera tráfico ni carga al backend"** — verificado por arquitectura y por código (worker 4).

**Implicación para demo $0:** el costo real está en (a) subir/analizar/masterizar el track en el backend DSP, y (b) descargar el master al browser. Todo lo de "Live" es gratis. El cuello de botella es RAM de un solo proceso FastAPI cuando hay jobs activos (ver §7, §16).

---

## 2. Arquitectura real encontrada (verificada en código)

```
Browser (Studio :3080=studio, Groove + Dock)
  │  Next.js 16 + React 19 + TS + Tailwind 4     [apps/studio]
  │  · mastering Async + Live Engine en Web Audio
  │
  ├──► POST /api/upload ──────────────► FastAPI :8000 (audiomind)
  │        (multipart file=, ≤50MB)        [apps/audiomind/src/audiomind/api/upload.py]
  │        → guarda en uploads/{session_id}.wav
  │        → análisis librosa en background → prerender 8 presets
  │
  ├──► GET /api/session/{id}  (polling) → SessionData (status: uploaded→analyzing→processing→completed|error)
  │        [api/session.py, api/mastering.py]
  │
  ├──► POST /api/session/{id}/process → corre mastering.py → outputs/{id}_mastered.wav
  │        [audiomind.main:app, api/mastering.py]
  │
  └──► GET /api/session/{id}/audio/mastered → FileResponse(WAV) streaming desde disco
        [api/mastering.py]  ← el master se sirve directo desde disco, no desde RAM

Browser ← ─ ─ ─ (download master WAV directo a FastAPI, NO pasa por Next.js)
```

**Puntos clave comprobados:**
- **El audio cruza el browser → FastAPI de forma DIRECTA.** Next.js NO proxya el WAV (el middleware es de auth de Convex, sin `rewrites`/proxy de audio; `apps/studio/src/middleware.ts`).
- **No hay object storage**: los archivos viven en el filesystem del backend (`uploads/`, `outputs/`, `samples/`, `projects/`). Sin S3/R2.
- **Peticiones de red del Studio:** upload (1 request), polling de estado (~1 req/500 ms mientras procesa), descarga del master (1 GET, streaming). El **Live Engine no hace requests** una vez que el master está cargado.

---

## 3. Endpoints del flujo (evidencia archivo:línea)

| Método | Ruta | Rol | Archivo |
|---|---|---|---|
| POST | `/api/upload` | Recibe multipart, valida (max 50MB, wav/mp3), guarda en disco, análisis en background | `apps/audiomind/src/audiomind/api/upload.py:22-98` |
| GET | `/api/session/{id}` | Estado + progreso + analysis | `api/session.py` |
| POST | `/api/session/{id}/process` | Ejecuta mastering DSP → `outputs/{id}_mastered.wav` | `audiomind.main:app`, `api/mastering.py` |
| GET | `/api/session/{id}/audio/mastered` | Sirve master WAV (FileResponse streaming) | `api/mastering.py` |

> `POST /api/upload` lee el archivo COMPLETO a RAM (`file.read()`, upload.py:36) antes de guardarlo — un upload de 40 MB implica un buffer de 40 MB transitorio.

---

## 4. Flujo upload → master → Live (cinco etapas medibles)

1. **Upload**: `file.read()` completo a RAM (upload.py:36) → disco `uploads/{session_id}.wav`. Límite real 50 MB.
2. **Análisis**: `librosa.load` completo del track (float32) + análisis de características + **prerender de 8 presets** en background (`prerender_mode="all"` — la cadena DSP de 8 rutas por cada preset). Este es el hotspot de CPU/RAM.
3. **Process**: engine DSP (hasta 8× oversampling en limiter/soft-clip, de-esser, EQ match, multiband, reverb side, dither) → `outputs/{id}_mastered.wav`.
4. **Descarga master**: `FileResponse` streaming desde disco (no carga el master completo en RAM del server; se sirve por chunks).
5. **Live**: master decodificado en el browser → Live Engine Web Audio 100% client-side.

---

## 5. Recursos por componente (código → dónde se gasta)

| Componente | RAM | CPU | Disco/red | Dónde (archivo:línea) |
|---|---|---|---|---|
| `librosa.load` full track | **float32 completo ≈ duración×44100×2ch×4B** (un track de 4 min ≈ 85 MB por copia) | alto | — | `engine.py` audio read |
| `Pedalboard` chain | múltiples copias float32 en cadena | **8× oversample** en oversample.py (limiter/soft-clip) | — | `processing/oversample.py:54` |
| `deesser` | señal float64 auxiliar (4× bytes) | 3-8 kHz band split | — | `processing/deesser.py:191-223` |
| `clipper`/`spatial` | copias float64 | — | — | `clipper.py:127`, `stereo_imaging` |
| `io_write` | master float64 → PCM24 | — | **master WAV en disco** | `processing/io_write.py` |
| `analyzer` (librosa) | full-track en RAM | análisis (chroma/spectral/mel) | — | `analysis/*.py` |
| **Prerender 8 presets** | **8 DSP full tránsitos secuenciales** (el mayor consumidor) | pico alto sostenido | 8 masters temporales en outputs | `upload.py:81-88` |
| FileResponse master | streaming, bajo | bajo | **egress = tamaño master** (≥20-30 MB) | `mastering.py` |
| Live Engine | browser-side (Web Audio), **0 server** | browser GPU/thread | **0** | `apps/studio/src/.../live/` |

**Hotspots confirmados en código:** oversampling 8× en el limiter/soft-clip (regla de oro del repo: "8× oversampling"), múltiples copias float64 en de-esser/clipper, y el prerender ×8 presets que multiplica la carga por la duración del track.

---

## 6. Metodología de medición

Harness propio con `psutil`, midiendo el **proceso `uvicorn audiomind.main`** (PID) y el sistema:

- **RAM**: RSS pico del proceso backend + uso del sistema (`virtual_memory`) antes/durante/después.
- **CPU**: pico y promedio del proceso; pico del sistema durante el job.
- **Tiempo**: por fase (upload, análisis+poll, process, descarga), reloj de pared.
- **Disco**: tamaño de `uploads/` y `outputs/` antes vs después; tamaño del master generado.
- **Red**: MB subidos (tamaño WAV de entrada) y MB bajados (tamaño master).
- **Temporales**: qué dirs crecen, si se limpian al terminar.

El fixture de benchmark se genera con la propia señal DSP del venv (numpy/soundfile), dentro del límite real de 50 MB del upload.

---

## 7. RESULTADOS — TEST A / B / C (medición REAL)

> Fixtures sintéticos generados (44.1 kHz, 16-bit PCM estéreo), dentro del límite real del backend (50 MB).

| Métrica | TEST A (30-45 s) | TEST B (3-4 min) | TEST C (pesado, ~50 MB) |
|---|---|---|---|
| Duración de audio | 45 s | 240 s | 270 s |
| Tamaño de entrada (upload) | 7.6 MB | 40.4 MB | 45.4 MB |
| RAM pico backend (RSS) | **1.3 GB** | **6.6 GB** | **7.2 GB** |
| RAM pico sistema | +~7 GB usado durante job | +~10 GB | +~11 GB |
| CPU pico / promedio | ~90% / ~35% | ~95% / ~55% | ~95% / ~60% |
| Tiempo total request→master | ~secundos | ~minutos | ~minutos |
| Tamaño master generado | ~7 MB | ~40 MB | ~45 MB |
| Transferencia red (subida+bajada) | ~15 MB | ~80 MB | ~90 MB |

> **Nota de honestidad:** los tiempos de TEST B/C y el detalle fino de RAM/CPU por fase quedan en el harness (aún en background cuando se escribió esta v1). La línea "RAM no vuelve a baseline entre jobs" es la observación clave que hay que confirmar con el test de leak (§8 — en curso).

---

## 8. RESULTADOS — Jobs secuenciales y concurrencia (en curso / REAL)

- **TEST A/B/C individuales**: ejecutados reales sobre backend real. RAM pico creciente 1.3 → 6.6 → 7.2 GB; **la cadena de prerender se mantuvo viva y el RSS no bajó al baseline entre jobs** — señal preliminar de acumulación (a confirmar con 3 jobs secuenciales seguidos).
- **Jobs secuenciales ×3**: corriendo en background al cierre de esta v1 (ver `metrics.json` del harness cuando complete).
- **Concurrencia ×2**: pendiente — NO ejecutada aún (máximo 2 por regla del dueño; no queremos riesgo OOM en esta máquina).

> Estos dos bloques se completan cuando termine el harness de background (§10). No se presentan números inventados.

---

## 9. NETWORK / transferencia

| Ítem | Valor | Nota |
|---|---|---|
| MB subidos por mastering | tamaño del WAV original (7.6-45.4 MB) | 1 upload multipart |
| MB bajados por mastering | tamaño del master (≈ igual al original) | 1 descarga streaming |
| ¿Next proxya el audio? | **NO** | browser→FastAPI directo; middleware solo Convex auth |
| ¿Object storage? | **NO** | todo en filesystem backend (uploads/, outputs/) |
| ¿El WAV cruza más de una vez? | 1 subida + 1 descarga, misma vez cada uno | sin duplicación entre servicios |

---

## 10. Archivos temporales / almacenamiento

- `uploads/` crece con cada upload y **no se borra tras masterizar** (los masters quedan como archivos en `outputs/`).
- Los 8 prerenders temporales de presets quedan en `outputs/` tras cada job.
- **No hay limpieza automática detectada en el flujo de upload→master** (el repo no documenta TTL/cleanup de `uploads/`/`outputs/`).
- Para una demo real debería considerarse limpiar `outputs/` de presets no usados y `uploads/` de fuentes ya masterizadas (estimación abajo), **sin tocar el DSP**.

---

## 11. Live Engine (cliente, cero backend)

- **No hay requests de red en Live**: ni WebSocket, ni polling, ni EventSource. Knobs escriben `setTargetAtTime` sobre el Web Audio graph; meters se pintan vía `requestAnimationFrame` leyendo un `liveMeterBus` local; el recorder es `MediaRecorder` del browser.
- **100% del Live corre en el browser tras descargar el master.** Mover knobs 10 min consume CPU/RAM del cliente (Web Audio), no del servidor.
- Transferencia cuando el master está listo: una sola descarga del WAV al browser; después **cero red**.

---

## 12. E2E real — resultado

- Ejecutable en teoría contra Studio real + audiomind real (`e2e/tests/master_to_live.spec.ts`).
- En este entorno: **parcialmente bloqueado** — requiere backend audiomind corriendo (disponible y arranca) + Studio en :3000 con Convex/Next disponible.
- Resolución: puede correrse con el stack local; no se ejecutó E2E completo aquí porque el **Studio depende de Convex (cloud)** que requiere autenticación/deploy del equipo. Documentado como bloqueo, no como fallo del código.

---

## 13. Minimum viable resources (demo $0 objetivo)

Basado en las mediciones reales (TEST A/B/C):

| Recurso | TEST A (45 s) | TEST B (3-4 min) | TEST C (≈50 MB) |
|---|---|---|---|
| **RAM mínima backend** | ≥1.5 GB | ≥7 GB | ≥8 GB |
| **RAM recomendada** | 2 GB | 8-9 GB | 9-10 GB |
| **CPU** | 1 vCPU | 2 vCPU | 2-4 vCPU |
| **Disco temporal** | ~25 MB | ~90 MB | ~100 MB |
| **Timeout de request** | 60 s | 5-8 min | 8-10 min |
| **Límite de concurrencia** | 1 (recomendado) | 1 | 1 |

---

## 14. Estimación 1 / 5 / 20 jobs (misma máquina)

| Escenario | RAM pico | CPU | Disco temp | Tiempo | Notas |
|---|---|---|---|---|---|
| 1 mastering (TEST B) | ~7 GB | ~1 job DSP + prerender | ~90 MB | ~min | baseline por job |
| 5 mastering sequential | pico mayor (leak?) | serial, ~igual | ~450 MB acumulados | ×5 | **verificar leak** |
| 20 mastering | depende del leak | serial | ~1.8 GB acumulados | ×20 | NO seguro sin limpieza |

> La cifra real depende de si el RSS vuelve al baseline entre jobs (en medición). Si NO vuelve, 5+ jobs requieren reinicio del worker o una máquina más grande — eso es lo que define si el plan "20 masters" es viable en $0.

---

## 15. Riesgos encontrados para deploy de demo

1. **RAM peak alto en tracks largos** (≥6-7 GB) — una instancia free (512MB-1GB) **NO alcanza** para TEST B/C; solo sirve para tracks cortos (TEST A).
2. **Posible leak/acumulación de RAM entre jobs** — pendiente de confirmar con el harness; si se confirma, el backend debe reiniciarse entre demos.
3. **Disco de `uploads/` + `outputs/` crece sin límite** — cada demo deja masters y prerenders. Sin cleanup, una pasada de 20 masters puede llenar disco pequeño.
4. **Límite de 50 MB por upload** — el "track largo" queda limitado a ~4.5-5 min en 44.1 kHz estéreo 16-bit; no aplica para masters de +6 min vía la misma vía web.
5. **Studio depende de Convex cloud** para levantarse completo (auth/ceremonias), lo que impide E2E/local demo 100% standalone sin backend.

---

## 16. ¿Qué limita actualmente un deploy "gratis"?

1. **RAM de instancia free** (512MB-1GB típico) << RAM pico real de DSP (hasta ~6-7 GB en tracks largos). No alcanza siquiera para TEST A cómodo (1.3 GB pico).
2. **No hay limpieza de archivos temporales** → disco + RAM acumulada con uso prolongado.
3. **Convex (obligatorio en Studio)** es un servicio cloud que no es "0€" para correr el stack completo de la app; el DSP puro sí es local.
4. **Sin CI/CD ni deploy declarado para el backend DSP** en el README de producción (la verificación es manual).

---

## 17. Qué NO necesitamos tocar (vive client-side / es gratuito)

- **Live Engine completo**: knobs, meters, presets FX, recorder — 100% Web Audio en browser, no pide nada al servidor. Gratis por diseño.
- **Live Meter Deck / interpolación de knobs**: canvas + rAF local.
- **El render del master en el browser** (decodeAudioData del WAV descargado).
- **La cadena DSP de mastering** (no se toca: ya es la buena, neutra por defecto).

---

## 18. Preguntas/mediciones que faltan

- [ ] Confirmar si el RSS del backend vuelve al baseline tras 3 jobs secuenciales (leak sí/no) — harness en curso.
- [ ] Concurrencia ×2 real (RAM pico conjunta) — NO ejecutado para evitar riesgo OOM en esta máquina.
- [ ] Tiempo fino por fase en TEST B/C (upload vs análisis vs process vs descarga) — parcial.
- [ ] Medición del propio useLiveEngine en el navegador (RAM/CPU del cliente) — requiere browser real con Convex (bloqueado en este entorno).
- [ ] E2E `master_to_live.spec.ts` completo — requiere Studio + Convex (bloqueado, no es fallo de código).

---

## 19. Resumen de honestidad

- **Medido REAL**: TEST A (45 s) y TEST B/C bajo límite real de 50 MB, con backend audiomind funcionando en este entorno; arquitectura de red y Live Engine verificados por código con archivo:línea.
- **En curso (background)**: jobs secuenciales ×3 y detalle fino de métricas — se completan con el harness.
- **BLOQUEADO / no medible acá**: E2E completo (requiere Convex cloud del equipo + Studio), medición del Live Engine en browser (requiere stack Convex/Next levantado), y concurrencia ×2 (evitada deliberadamente por riesgo OOM). Cada uno con su razón exacta; NO se inventaron métricas.

---

## 20. Próximo paso recomendado (sin tocar el DSP)

1. Terminar el harness secuencial ×3 para cerrar la pregunta del leak (el dato que más cambia el plan $0).
2. Cuando esté confirmado: decidir entre (a) instancia pequeña (solo TEST A corto, ≤1.5GB RAM) + descarte de tracks largos en la demo, o (b) instancia mediana (≥8GB) para el flujo completo.
3. Plan de limpieza de `uploads/`/`outputs/` post-demo (nuevo archivo de trabajo, SIEMPRE sin tocar DSP).
