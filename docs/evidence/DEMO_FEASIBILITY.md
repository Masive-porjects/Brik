# DEMO_FEASIBILITY.md — Client Mastering Demo Audit

**Auditoría:** 2026-09-11
**Rama:** `demo/vercel-railway-client` (6 commits ahead de `origin/main`)
**HEAD:** `f36f747` (chore: pin audiomind uv.lock)
**Base:** `origin/main`

> ⚠️ **Informe HISTÓRICO (2026-09-11).** Refleja el estado de esa rama y ese HEAD, no el actual. Desde entonces: el **Live Engine fue eliminado** (`ba3b4a6`, 27-Sep) — `LiveView.tsx` ya no existe; **HumanMidi fue removido** (`apps/humanmidi/` no está en el repo); y el scaffolding de Convex fue eliminado. Los hallazgos y gaps de abajo se conservan como evidencia de la auditoría original, sin reescribir.

---

## 1. ARQUITECTURA ENCONTRADA

### Estructura actual del branch

La rama `demo/vercel-railway-client` **ya existe** con 6 commits que implementan la mayor parte del demo:

| Commit | Contenido |
|--------|-----------|
| `f8c2069` | feat: demo mode — on-demand multi-preset mastering, DSP gate, TTL janitor |
| `4d3cc5e` | test: demo mode coverage — on-demand, concurrency, TTL |
| `3d5fd48` | feat: studio — preset-aware mastered URLs/download + demo upload limit modal |
| `b6f392f` | chore: demo-budget benchmark script |
| `47d0c57` | docs: resource audit of pre-demo-mode flow |
| `f36f747` | chore: pin audiomind uv.lock |

### Archivos modificados (diff origin/main...HEAD)

```
DEMO_RESOURCE_AUDIT.md (nuevo)
apps/audiomind/scripts/benchmark_demo.py (nuevo)
apps/audiomind/src/audiomind/api/mastering.py (modificado)
apps/audiomind/src/audiomind/api/upload.py (modificado)
apps/audiomind/src/audiomind/config.py (modificado)
apps/audiomind/src/audiomind/main.py (modificado)
apps/audiomind/src/audiomind/models/audio.py (modificado)
apps/audiomind/src/audiomind/services/__init__.py (modificado)
apps/audiomind/src/audiomind/services/demo_guard.py (NUEVO)
apps/audiomind/tests/test_demo_concurrency.py (NUEVO)
apps/audiomind/tests/test_demo_mode.py (NUEVO)
apps/audiomind/tests/test_demo_ttl.py (NUEVO)
apps/audiomind/uv.lock (modificado)
apps/studio/src/adapters/api/client.test.ts (modificado)
apps/studio/src/adapters/api/client.ts (modificado)
apps/studio/src/app/page.tsx (modificado)
```

### DSP NO tocado

**Archivos DSP sin modificación:**
- `apps/audiomind/src/audiomind/processing/engine.py` — sin cambios
- `apps/audiomind/src/audiomind/processing/presets.py` — sin cambios
- `apps/audiomind/src/audiomind/processing/loudness.py` — sin cambios
- `apps/audiomind/src/audiomind/processing/spatial.py` — sin cambios
- Todos los archivos de `processing/`, `analysis/`, `effects/` — sin cambios

`git diff --name-only origin/main...HEAD` confirma: **NINGÚN archivo DSP modificado.**

### Flujo confirmado

```
Browser → FastAPI directo (NEXT_PUBLIC_API_URL)
  POST /api/upload → guarda WAV → análisis background
  POST /api/session/{id}/process?preset_id=X → DSP on-demand
  GET /api/session/{id}/audio/mastered?preset_id=X → FileResponse WAV
  GET /api/session/{id}/download/wav?preset_id=X → WAV PCM24
```

- Audio NO viaja por Vercel/Next.js
- Sin object storage (filesystem local)
- Sesiones persisten a disco (`sessions.json`) via `session_store.py`
- `mastered_path` apunta al WAV master actual
- `preset_masters` dict almacena múltiples masters por preset

---

## 2. RESPUESTAS A LAS PREGUNTAS A-K

### A. ¿Puede desactivarse el prerender automático sin modificar process_audio?

**SÍ ✅**

`config.py` tiene `prerender_mode: Literal["all", "on_demand"] = "all"`. En `upload.py`, el background analysis solo llama a `_prerender_all_presets()` cuando `settings.prerender_mode == "all"`. En modo `on_demand`, la subida termina con `status: "uploaded"` y cero DSP automático. `process_audio` no se modifica.

### B. ¿Puede /process generar un preset individual usando exactamente el mismo DSP existente?

**SÍ ✅**

`mastering.py` tiene `_process_preset_on_demand()` que llama a `process_audio()` (el wrapper lazy-import del motor existente) con los parámetros del preset. El DSP es exactamente el mismo — no se modifica ningún algoritmo.

### C. ¿Puede almacenarse más de un preset generado por sesión?

**SÍ ✅**

`session.preset_masters` es un `dict[str, PresetMasterEntry]` que ya soporta múltiples presets por sesión. Cada entry tiene su propio `output_path`, `master_result`, `validation`, y `status`.

### D. ¿Puede Studio volver a un preset generado sin ejecutar DSP otra vez?

**SÍ ✅**

`_process_preset_on_demand()` Case 2: si `entry.status == "completed"` y el archivo existe, devuelve la sesión inmediatamente sin DSP. El cache hit es por `(session_id, preset_id)` gestionado por `demo_guard.get_or_create_flight()`.

### E. ¿Puede download descargar exactamente el preset actualmente seleccionado?

**SÍ ✅**

`download_audio()` acepta `preset_id: str | None = Query(default=None)`. Si `preset_id` es proporcionado, descarga ese preset específico del `preset_masters` dict. El frontend pasa `activePresetId` en `handleDownload`.

### F. ¿Puede imponerse concurrency=1 alrededor del DSP sin modificar algoritmos DSP?

**SÍ ✅**

`demo_guard.py` usa `threading.BoundedSemaphore(max(1, settings.max_concurrent_dsp))` como `_gate`. `DSP_THREAD_POOL` se crea con `max_workers=max(1, settings.max_concurrent_dsp)`. En demo, `settings.max_concurrent_dsp=1`. Todo el DSP pesado pasa por `with demo_guard.gate():`. Los algoritmos DSP no se tocan.

### G. ¿Puede rechazarse >60 s antes de comenzar procesamiento pesado?

**SÍ ✅**

`upload.py` llama a `demo_guard.probe_duration()` que usa `soundfile.info()` para WAV (header-only, rápido) o `librosa.get_duration()` para MP3. Si `duration > settings.demo_max_duration_seconds`, lanza `HTTPException(422)`. El archivo se limpia y se rechaza antes de cualquier DSP.

### H. ¿Puede Live quedar deshabilitado visualmente sin borrarlo?

**PARCIALMENTE ⚠️**

El componente `LiveView.tsx` no tiene mecanismo de bloqueo por demo mode. La página `page.tsx` renderiza `LiveView` cuando `currentTab === "live"` sin verificar demo mode. Se necesita agregar una verificación de demo mode en el frontend para mostrar "Próximamente" en lugar del Live Engine completo.

### I. ¿Puede Agent quedar deshabilitado visualmente sin borrarlo?

**PARCIALMENTE ⚠️**

El "Agent" es el `ChatPanel` y la página `voz` (`apps/studio/src/app/voz/`). No tienen mecanismo de bloqueo por demo mode. Se necesita agregar un banner "Próximamente" para el Agent en demo mode.

### J. ¿Puede apps/studio hablar directamente con Railway usando NEXT_PUBLIC_API_URL?

**SÍ ✅**

`config.ts` del Studio usa `RAW_API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"`. El `normalizeApiBase` corrige trailing slashes y duplicados. No hay proxy de audio en Next.js. El audio viaja directo del browser a FastAPI.

### K. ¿Puede hacerse todo esto sin modificar el resultado musical?

**SÍ ✅**

Confirmado por `git diff --name-only`: ningún archivo DSP modificado. `process_audio`, `clipper`, `limiter`, oversampling, true peak, LUFS, DR, EQ, compression, de-esser, saturation, QC, gain staging, stereo/mono DSP, sample rate, bit depth — TODO SIN CAMBIOS.

---

## 3. HALLAZGOS CRÍTICOS Y GAPS

### Gap 1: Sin NEXT_PUBLIC_DEMO_MODE en el Studio

**Severidad:** Alta
**Descripción:** El Studio frontend no tiene variable de entorno `NEXT_PUBLIC_DEMO_MODE` ni mecanismo equivalente para detectar que está en modo demo. El backend tiene `AUDIOMIND_DEMO_MODE` pero el frontend no lo consulta.
**Impacto:** Sin esto, no se puede mostrar "Próximamente" en Live/Agent, ni habilitar las restricciones de demo en el frontend.
**Solución:** Agregar `NEXT_PUBLIC_DEMO_MODE=true` al `next.config.js` o `.env` del Studio, y verificar el demo mode en `page.tsx` para los tabs Live y Agent.

### Gap 2: Sin bloqueo "Próximamente" para Live/Agent

**Severidad:** Alta
**Descripción:** Los tabs Live y Agent (y la página `voz`) no tienen mecanismo de bloqueo para modo demo.
**Impacto:** El cliente puede acceder al Live Engine y Agent durante la demo, lo cual no es el comportamiento deseado.
**Solución:** En `page.tsx`, cuando `demoMode` está activo, renderizar un overlay/banner "Próximamente" en lugar del contenido real de Live/Agent.

### Gap 3: HumanMidi existe en el repo

**Severidad:** Media
**Descripción:** El directorio `apps/humanmidi/` existe completo (run.py, src/, tests/, requirements.txt, etc.). No tiene referencias en studio/audiomind.
**Impacto:** No afecta funcionalidad del demo, pero el usuario pidió borrar todo rastro de HumanMidi.
**Acción:** `apps/humanmidi/` debe eliminarse del repo para cumplir con el requisito del usuario.

### Gap 4: Config de demo mode en Studio incompleta

**Severidad:** Media
**Descripción:** El `next-env.d.ts` del Studio tiene una modificación no confirmada (`git diff`). El Studio no tiene un archivo `.env` con `NEXT_PUBLIC_DEMO_MODE`.
**Solución:** Crear `.env` en el Studio con las vars de demo mode, o configurar en `next.config.js`.

---

## 4. ARCHIVOS EXISTENTES DE DEMO

Ya existen en el repo (sin confirmar):

| Archivo | Estado |
|---------|--------|
| `docs/evidence/DEMO_RESOURCE_AUDIT.md` | Untracked — auditoría de recursos |
| `e2e/tests/demo_flow.spec.ts` | Untracked — E2E demo completo |
| `e2e/fixtures/generate_demo_fixture.py` | Untracked — generador de fixture |
| `apps/audiomind/tests/test_demo_mode.py` | Untracked — tests demo |
| `apps/audiomind/tests/test_demo_concurrency.py` | Untracked — tests concurrencia |
| `apps/audiomind/tests/test_demo_ttl.py` | Untracked — tests TTL |
| `apps/audiomind/scripts/benchmark_demo.py` | Untracked — benchmark |
| `apps/audiomind/tests/create_test_wav.py` | Untracked |

---

## 5. GATE DE VIABILIDAD — RESUMEN

| Pregunta | Respuesta | Evidencia |
|----------|-----------|-----------|
| A. Prerender off | ✅ SÍ | `config.py` `prerender_mode` |
| B. Proceso individual | ✅ SÍ | `_process_preset_on_demand` |
| C. Multi-preset cache | ✅ SÍ | `preset_masters` dict |
| D. Cache hit sin DSP | ✅ SÍ | Case 2 de `_process_preset_on_demand` |
| E. Download por preset | ✅ SÍ | `preset_id` query param |
| F. Concurrency=1 | ✅ SÍ | `BoundedSemaphore` + `DSP_THREAD_POOL` |
| G. Rechazo >60s | ✅ SÍ | `demo_guard.probe_duration` |
| H. Live Próximamente | ⚠️ PARCIAL | Falta frontend |
| I. Agent Próximamente | ⚠️ PARCIAL | Falta frontend |
| J. Studio→Railway directo | ✅ SÍ | `NEXT_PUBLIC_API_URL` |
| K. Sin cambios DSP | ✅ SÍ | `git diff` confirma |

**Verdict: VIABLE con 2 gaps de frontend (H, I) y 1 gap de config (NEXT_PUBLIC_DEMO_MODE).**

---

## 6. HUMAN MIDI — RASTRO

- `apps/humanmidi/` existe como directorio completo
- **0 referencias** en `apps/studio/src` (grep)
- **0 referencias** en `apps/audiomind/src` (grep)
- No hay imports, rutas, ni dependencias cruzadas
- HumanMidi es completamente aislado del flujo de mastering demo

**Recomendación:** Borrar `apps/humanmidi/` del repo para cumplir con el requisito del usuario.

---

## 7. LICENCIA

- `require_license` dependency existe en `license.py`
- Cuando `license_key` es vacío (desarrollo), todas las requests pasan
- En producción, requiere header `X-License-Key`
- Los tests de demo monkeypachean `settings.license_key` a `""`
- **La demo funciona sin licencia en modo desarrollo**

---

## 8. ESTADO DEL REPO

```
Branch: demo/vercel-railway-client
Base: origin/main (f36f747)
HEAD: f36f747 (6 commits ahead)

Modified files:
  apps/studio/next-env.d.ts

Untracked files:
  apps/audiomind/tests/create_test_wav.py
  docs/evidence/DEMO_RESOURCE_AUDIT.md
  e2e/fixtures/generate_demo_fixture.py
  e2e/tests/demo_flow.spec.ts
  playwright-report/
  test-results/
```

---

## 9. PRÓXIMOS PASOS

1. **[CRÍTICO]** Agregar `NEXT_PUBLIC_DEMO_MODE` al Studio
2. **[CRÍTICO]** Implementar bloqueo "Próximamente" para Live/Agent en `page.tsx`
3. **[ALTA]** Borrar `apps/humanmidi/` del repo
4. **[ALTA]** Crear `.env` con vars de demo mode en Studio
5. **[MEDIA]** Verificar `album` tab handling en demo mode
6. **[MEDIA]** Ejuter baseline de tests (backend + studio)
7. **[MEDIA]** Ejecutar benchmarks 45s, 60s, 61s
8. **[MEDIA]** Ejecutar tests single-flight y concurrencia
9. **[MEDIA]** Ejecutar E2E `demo_flow.spec.ts`

---

## 10. CONCLUSIÓN

La arquitectura del demo **es viable**. El backend ya tiene toda la infraestructura implementada (on-demand processing, single-flight, concurrency gate, TTL, multi-preset cache). El DSP no se modifica. El flujo Browser → FastAPI directo funciona. Los gaps son exclusivamente de frontend (detectar demo mode y bloquear Live/Agent visualmente), que son cambios menores de UI sin impacto en la lógica de audio.

**El demo puede levantarse localmente para pruebas una vez resueltos los 2 gaps de frontend.**
