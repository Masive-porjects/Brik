# 07 — Estrategia de Equipo: 5 Desarrolladores para midiMastering

> Plan de arquitectura, roles, contratos y UX/UI para construir el ecosistema completo (WaveAI + Live Engine + HumanMidi) con **5 desarrolladores** en el marco del hackaton (7 días), aplicando **SOLID** en el código y en la organización misma.
>
> **⚠️ 2026-09-11 · DOCUMENTO HISTÓRICO:** HumanMidi (Dev 4, visión/gestos) fue removido del producto. El rol del bridge Python y el Live Engine que este banner daba por vigentes también desaparecieron (`ba3b4a6`, `92c79bf`, `38c1246`); ver `../../ESTADO_PROYECTO.md` §3.3 y §5.

## 1. Principio rector: dividir por DOMINIO, no por capa

El error clásico en equipos pequeños es repartir "frontend / backend / QA". Eso crea dependencias cruzadas y colas de espera. Aquí dividimos por **dominios de producto**, cada uno con su `git` workflow, sus tests y su dueño:

```
┌─────────────────────────────── 5 DOMINIOS ───────────────────────────────┐
│                                                                          │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────┐      │
│  │ 1. Backend  │   │ 2. Frontend  │   │ 3. Live Engine           │      │
│  │  Mastering  │   │    Studio    │   │  (Web Audio + UX Live)   │      │
│  │  (FastAPI)  │   │   (Next.js)  │   │                          │      │
│  └──────┬──────┘   └──────┬───────┘   └──────────┬───────────────┘      │
│         │                 │                      │                       │
│         │        ┌────────▼─────────┐            │                       │
│         │        │ 4. HumanMidi +   │            │                       │
│         │        │    Bridge        │            │                       │
│         │        │ (Python + WS)    │            │                       │
│         │        └──────────────────┘            │                       │
│         │                                         │                      │
│         └─────────────── 5. QA + UX Lead ─────────┘                      │
│                         (transversal)                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Regla de oro:** un dev toca SU dominio; tocar el de otro requiere PR y aprobación del dueño. Los únicos puntos de contacto entre dominios son los **contratos** (sección 3), que se definen el día 0 y luego cambian poco.

## 2. Roles, archivos y responsabilidades (detallado)

> Convención de rutas: estructura de monorepo (sección 6). `humanmidi/` conserva su estructura interna actual (`run.py` en su raíz de app).

---

### DEV 1 — Backend Mastering (FastAPI "AudioMind")

**Misión:** que la fase offline funcione de punta a punta: subir un WAV/MP3 → análisis → master WAV servible por HTTP, con el DSP proporcional intacto y medible.

**Stack:** FastAPI · librosa · pedalboard · scipy · numpy · ffmpeg · Pydantic · pytest.

**Archivos que toca (dueño exclusivo):**
```
backend/src/audiomind/
├── main.py                      # routers, CORS, /health
├── config.py                    # max_file_size_mb, target_lufs, sample_rate
├── api/
│   ├── upload.py                # POST /api/upload, análisis en background
│   └── mastering.py             # POST /process, GET /audio/*, /download/{wav|mp3}
├── models/audio.py              # SessionData, ProcessingStatus, MasteringParameters
├── analysis/analyzer.py         # métricas librosa, género, already-mastered
├── processing/
│   ├── engine.py                # process_audio (la cadena de 13 etapas)
│   ├── presets.py               # PRESET_CHAINS
│   ├── loudness.py · truepeak.py · clipper.py · multiband.py · dyn_eq.py
│   ├── exciter.py · tape.py · spatial.py · stereo_imaging.py
│   ├── adaptive_comp.py · mono.py · dither.py · oversample.py
└── storage/cache.py             # SessionCache (Fase 1)
backend/tests/                   # suite de backend (ampliar)
```

**Tareas por día:**
- **Día 0–1:** levantar el backend local; correr la suite existente; benchmark de render de un track de 3 min (medir ~44 s) y del lookup prebuilt (~1.5 s). Documentar números en `docs/benchmarks.md`.
- **Día 2:** verificar/endurecer `GET /api/session/{id}/audio/mastered` (el Live Engine lo consumirá); test manual con curl: upload → process → download WAV válido (`file` dice WAV).
- **Día 3–4:** si hace falta, endpoint auxiliar `GET /api/session/{id}/live/master` que devuelve el master WAV con cabeceras de cache (`Cache-Control: public, max-age=3600`) para que el navegador no lo re-descargue por cada sesión.
- **Día 5–6:** optimizar lo que se pueda SIN romper la cadena (el DSP es sagrado); medir latencia del lookup prebuilt; asegurar que los presets devuelvan el master en ~1.5 s.
- **Día 7:** freeze; solo bugfixes críticos; soportar el E2E del Dev 5.

**Entregables tangibles:** backend corriendo en `localhost:8000`; suite pytest verde; `docs/benchmarks.md` con tiempos de render y prebuilt; master WAV servible con caché.

**Definition of done (verificable):**
```bash
pytest backend/tests -q                    # verde
curl -s localhost:8000/health              # {"status":"ok"}
curl -s -F "file=@demo.wav" localhost:8000/api/upload     # 200, session id
curl -s localhost:8000/api/session/{id}/audio/mastered -o m.wav
file m.wav                                 # WAV audio
```

**NO toca:** frontend Next.js, Live Engine Web Audio, bridge, HumanMidi. Si el Live Engine necesita un cambio en `MasteringParameters`, lo pide por PR a Dev 5 (guardiana del contrato).

**Riesgo propio:** sesiones en memoria (se pierden al reiniciar) → para la demo el backend queda vivo; Redis es post-hackaton.

---

### DEV 2 — Frontend Studio (Next.js + sistema de diseño)

**Misión:** que el studio conserve su identidad visual y gane la estructura de la pestaña "Live" sin romper nada de la vista Estudio.

**Stack:** Next.js (App Router) · React 18 · TypeScript · Tailwind · GSAP + `@gsap/react` · Framer Motion · WaveSurfer.

**Archivos que toca (dueño exclusivo):**
```
frontend/src/
├── app/
│   ├── layout.tsx               # tema pre-hydration (no tocar el script)
│   ├── page.tsx                 # orquestación + estado de pestaña (añadir "live")
│   └── globals.css              # tokens (SOLO añadir tokens nuevos, no borrar legacy)
├── components/
│   ├── ModulePanel.tsx · PlatformSelector.tsx · Player.tsx · AnalysisPanel.tsx
│   ├── ProcessingOverlay.tsx · LicenseGuard.tsx · ModuleSheet.tsx · PaintedModule.tsx
│   ├── FloatingGhosts.tsx · FloatingNotes.tsx · BigGhostWithNotes.tsx
│   └── live/                    # (nuevo, autocontenido — ver Dev 3)
│       ├── LiveView.tsx         # contenedor de la pestaña Live
│       ├── FxSlotPanel.tsx      # render de slots FX con Knob3D
│       ├── GestureBadge.tsx     # etiqueta "pulgar derecho → Filtro"
│       ├── CameraOverlay.tsx    # <video> getUserMedia + canvas de landmarks (opcional WS)
│       └── LiveMeters.tsx       # reutiliza visual de AnalysisPanel para salida
└── lib/
    ├── api.ts · presets.ts · motion.ts   # (no tocar salvo aditivo)
    └── live/                    # tipos generados + helper de rangos (Dev 3 co-escribe)
```

**Tareas por día:**
- **Día 0–1:** setup monorepo + CI (`next build` en cada PR); mover la app al layout de monorepo sin regresiones.
- **Día 2:** añadir la entrada "★ Live" al rail lateral (nueva pestaña, `page.tsx`); esqueleto de `LiveView.tsx` con layout de 3 columnas (cámara / cadena FX / meters) reutilizando tokens y glass.
- **Día 3–4:** `FxSlotPanel` con los `Knob3D` existentes (4 slots: Filtro, Drive, Delay, Reverb) + `GestureBadge` (icono de mano + microcopy rioplatense); integrar `CameraOverlay` (getUserMedia local, sin landmarks todavía).
- **Día 5–6:** estado de conexión del bridge (badge verde/gris + banner de error con recovery); empty states ("Subí un audio…", "Conectá las manos…"); integrar los landmarks dibujados por WS si Dev 4/Dev 5 lo aprueban.
- **Día 7:** freeze; pulido visual final; screenshot del studio completo para la demo.

**Entregables tangibles:** pestaña Live navegable con el diseño del doc 04; knobs operables con mouse; cámara visible; cero regresiones en Estudio.

**Definition of done (verificable):**
```bash
cd frontend && npm run build              # build verde
npm run lint                              # sin errores nuevos
# Manual: Estudio sigue masterizando; Live renderiza; theme light/dark ok; reduced-motion ok
```

**NO toca:** nodos Web Audio (Dev 3 los monta dentro de los componentes que él crea en `components/live/`), backend, bridge. La regla con Dev 3: **Dev 2 crea la estructura visual, Dev 3 el audio**; si ambos tocan `LiveView.tsx`, el acuerdo es que Dev 3 trabaja en `lib/live/audioGraph.ts` y sus propios hooks, y solo importa componentes de Dev 2.

**Riesgo propio:** colisión con Dev 3 en `components/live/` → Dev 2 es dueño de los componentes `.tsx` de presentación; Dev 3 de `lib/live/` y hooks de audio. Frontera explícita por directorio.

---

### DEV 3 — Live Engine (Web Audio API)

**Misión:** que el master suene en el navegador con una cadena de FX en tiempo real (filtro → drive → delay/echo → reverb), controlable por parámetros externos, con neutral = audio idéntico y sin clicks.

**Stack:** TypeScript · Web Audio API (`AudioContext`, `BiquadFilterNode`, `WaveShaperNode`, `DelayNode`, `ConvolverNode`, `AnalyserNode`) · `setTargetAtTime` · MediaRecorder/captureStream · Vitest.

**Archivos que toca (dueño exclusivo):**
```
frontend/src/lib/live/                    # ← TODO el audio vive aquí
├── liveParams.gen.ts                     # tipos TS GENERADOS del schema (no editar a mano)
├── audioGraph.ts                         # monta/desmonta la cadena de nodos
├── fxPresets.ts                          # clean / dub / big_room / radio
├── liveSocket.ts                         # cliente WebSocket (recibe LiveParams, heartbeat)
├── useLiveEngine.ts                      # hook: estado + aplicación de params a nodos
└── recorder.ts                           # MediaRecorder + captureStream → grabación WAV
frontend/src/hooks/useLiveEngine.test.ts  # vitest
```

**Cadena de nodos exacta (audioGraph.ts):**
```
source (AudioBufferSourceNode, master WAV, loop)
  → filter (BiquadFilterNode, type="lowpass", frequency, Q)
  → drive (WaveShaperNode, curva tanh precalculada de N=1024 muestras)
  → delay (DelayNode) + fb (GainNode, feedback loop delay→fb→delay)
  → wet/dry (GainNode reverb_mix) + convolver (ConvolverNode, IR)
  → master (GainNode output_level)
  → analyser (AnalyserNode, para meters)
  → destination
```

**Tareas por día:**
- **Día 0–1:** playground de Web Audio (prototipo suelto fuera de la app); probar `AudioContext({ latencyHint: "interactive" })`; cadena mínima filtro→master con un WAV local.
- **Día 2–3:** `audioGraph.ts` completo con los 4 slots; **anti-zipper**: todos los cambios de parámetro vía `setTargetAtTime(value, ctx.currentTime, 0.02)` — nunca asignación directa; IR de reverb (generar uno sintético con ruido exponencialmente decaído, o cargar uno corto).
- **Día 3–4:** `liveSocket.ts` (conectar al bridge, aplicar mensajes en orden por `ts`, congelar a neutral si el socket cae 2 s); `fxPresets.ts` (clean = todo neutral; dub = delay 320 ms / feedback 0.45 / reverb 0.15; big_room = reverb 0.6 / delay 200 ms; radio = lowpass 3 kHz / drive 0.2).
- **Día 5–6:** `recorder.ts` (grabar la salida con `captureStream()` + MediaRecorder → descarga WAV); meters desde `analyser` (LUFS aproximado + true peak) expuestos al Dev 2; tests vitest del grafo.
- **Día 7:** freeze; pruebas auditivas finales con el músico del Dev 5.

**Entregables tangibles:** master sonando en loop con 4 FX controlables; socket aplicando LiveParams en vivo; grabación de salida descargable; suite vitest verde.

**Definition of done (verificable):**
```bash
cd frontend && npx vitest run             # verde
# Manual: con LiveParams neutral el master suena idéntico al original (A/B a oído)
# Manual: barrido de filter_cutoff de 200→12000 no produce clicks
# Manual: cortar el socket → en <2 s el audio vuelve a neutral
```

**NO toca:** el layout/estilo de la pestaña (usa los componentes de Dev 2), la API REST de mastering, HumanMidi, el bridge Python. Si necesita un parámetro nuevo → PR al schema (Dev 5).

**Riesgo propio:** zipper/clicks → `setTargetAtTime` es obligatorio; buffers grandes → usar `AudioWorklet` solo si se detecta latencia > 50 ms.

---

### DEV 4 — HumanMidi + Bridge (Python)

**Misión:** que los gestos de las manos se conviertan en `LiveParams` estables y de baja latencia que el navegador pueda consumir. Incluye mantener HumanMidi sano (26 tests) y construir el puente MIDI → WebSocket.

**Stack:** Python 3.12 · mediapipe 0.10.14 (PIN) · opencv · python-rtmidi · websockets · asyncio · pytest.

**Archivos que toca (dueño exclusivo):**
```
apps/humanmidi/                           # (migrado del repo actual, estructura interna intacta)
├── run.py · quick_start.py · config/config.yaml
├── src/core/camera_handler.py · hand_detector.py · midi_sender.py
├── src/gestures/base_gesture.py · drums_gesture.py · piano_gesture.py
│            · cc_thumbs.py · cc_controller.py
├── src/mappers/gesture_mapper.py · zone_mapper.py
└── src/config/settings.py · defaults.py

apps/bridge/                              # (nuevo — el puente)
├── main.py                               # orquestación asyncio (MIDI + WS en un proceso)
├── midi_listener.py                      # MidiIn (rtmidi) → callback de CC/notas
├── gesture_to_params.py                  # tabla CC→LiveParams + escalado
├── smoother.py                           # EMA + dead zone + debounce
├── ws_server.py                          # websockets: broadcast, heartbeat 5 s
├── latency.py                            # medición round-trip (timestamp por mensaje)
└── tests/test_gesture_to_params.py · test_smoother.py · test_ws_server.py
```

**Protocolo MIDI del modo studio (CONTRATO INTERNO, definido el día 0):**

| CC / Nota | Origen (gesto) | Parámetro LiveParams | Escalado |
|---|---|---|---|
| CC 74 | Pulgar derecho | `filter_cutoff` | **logarítmico**: 0–127 → 200 Hz – 12 kHz (`200 * (12000/200)^(v/127)`) |
| CC 92 | Pulgar izquierdo | `reverb_mix` | lineal 0–1 (÷127) |
| CC 71 | Altura de mano | `delay_time` | lineal 50–800 ms (`50 + (750 * v/127)`) |
| CC 73 | Apertura de mano | `echo_feedback` | lineal 0–0.8 (×0.8/127) |
| CC 16 | Posición X | `drive` | lineal 0–1 (÷127) |
| Nota 36/38/42/49 | Palmada (zona 0–3) | `fx_preset` | clean / dub / big_room / radio |

> CC 74 y CC 92 ya son los que emite `cc_thumbs` (Filter y Delay Send) — reutilización directa. CC 71/73/16 y las palmadas requieren un **modo studio** en HumanMidi: `python run.py --mode studio` (Vía B, día 5–6) que mapea los 5 gestos a estos CCs fijos. Hasta entonces, el bridge funciona con `--mode cc-thumbs` (2 parámetros) + palmadas.

**Tareas por día:**
- **Día 0–1:** migrar HumanMidi a `apps/humanmidi/`; verificar `python run.py --mode cc-thumbs` + puerto MIDI virtual (IAC/loopMIDI); confirmar 26 tests verdes.
- **Día 2–3:** `midi_listener.py` (abrir `MidiIn` en el puerto "HumanMidi", callback → cola asyncio); `gesture_to_params.py` con la tabla y el escalado logarítmico; tests de cada mapeo.
- **Día 3–4:** `smoother.py` (EMA con alpha 0.3 + dead zone ±2 CC + debounce 100–200 ms); `ws_server.py` (broadcast de `live_params` completos con `ts`, heartbeat 5 s); `latency.py`; primer loop end-to-end: enviar CCs sintéticos → ver LiveParams en el navegador.
- **Día 5–6:** modo `--mode studio` en HumanMidi (Vía B): reutilizar `cc_thumbs` para pulgares y añadir altura/apertura/X/palmadas; pruebas de latencia real con cámara (< 30 ms local es la meta).
- **Día 7:** freeze; soporte del E2E de Dev 5.

**Entregables tangibles:** bridge corriendo en `localhost:8765`; HumanMidi con `--mode studio`; suite pytest (26 + ~10 nuevos) verde; medición de latencia documentada.

**Definition of done (verificable):**
```bash
cd apps/bridge && pytest -q                # verde (tests de mapeo, smoother, WS)
cd apps/humanmidi && pytest tests/ -v      # 26 tests siguen verdes
# E2E sintético: python tools/midi_test_send.py  # envía CCs 74/92/71/73/16 por el puerto
#   → el bridge los publica por WS → el navegador aplica → latencia reportada < 50 ms
# Manual: gesto en reposo → valores neutrales (no hay "parámetros fantasma")
```

**NO toca:** FastAPI backend, componentes Next.js, Web Audio (recibe los valores ya mapeados). El contrato LiveParams lo custodia Dev 5 — cualquier cambio de rango es PR al schema.

**Riesgo propio:** mediapipe 0.10.14 congelado (0.10.21+ depreca `mp.solutions.hands`); latencia del puerto MIDI en macOS (IAC) — si > 50 ms, usar Vía B (emisión directa sin MIDI) como fallback.

---

### DEV 5 — QA + UX Lead (transversal)

**Misión:** que la experiencia prometida (tocar el master con las manos, sin fricción) se cumpla, que los contratos mantengan al equipo desbloqueado y que la demo final sea reproducible. Es el guardián de SOLID y de la calidad.

**Stack:** JSON Schema · json-schema-to-typescript · jsonschema (Python) · Playwright · axe-core · Node/Python (simulador).

**Archivos que toca (dueño exclusivo):**
```
packages/contracts/
├── live_params.schema.json               # LA fuente de verdad (versionada, semver)
├── README.md                             # cómo generar tipos y versionar
└── scripts/gen_types.sh                  # genera TS (studio) y dataclass (bridge)

apps/simulator/                           # (nuevo — desbloquea a Dev 2 y Dev 3)
├── main.py                               # emite LiveParams sintéticos por WS
├── scenarios.py                          # sweep de filtro, ciclo de presets, random walk
└── README.md

e2e/
├── playwright.config.ts
└── tests/master_to_live.spec.ts          # flujo completo E2E

docs/
├── benchmarks.md                         # (co-escribe con Dev 1)
└── ux_checklist.md                       # la sección 5 materializada en checklist
```

**Tareas por día:**
- **Día 0 (BLOQUEANTE):** entregar `live_params.schema.json` v1 (rangos de la sección 3) + `scripts/gen_types.sh` + el simulador funcionando. Esto desbloquea a Dev 2, Dev 3 y Dev 4 el mismo día.
- **Día 1–2:** checklist UX en `docs/ux_checklist.md`; test del contrato (validar que los tipos TS generados compilan y el simulador emite schema-válido); revisar PRs de todos (gate de estilo + contratos).
- **Día 3–4:** auditoría a11y con axe-core + navegación por teclado + `prefers-reduced-motion`; primeros specs de Playwright (subir audio → masterizar → abrir Live con el simulador → knobs cambian).
- **Día 5–6:** validación con un músico (sesión de 1 h: ¿los gestos se sienten naturales? ¿la latencia es aceptable?); incorporar feedback en checklist; E2E completo con bridge real.
- **Día 7:** **gate final**: los 4 dominios en verde + checklist UX aprobado + demo grabada (video de pantalla: track → master → performance en vivo).

**Entregables tangibles:** contrato v1 + generador de tipos; simulador de LiveParams; suite Playwright verde; checklist UX completado; video demo.

**Definition of done (verificable):**
```bash
cd e2e && npx playwright test             # verde
# Contrato: el simulador emite schema-válido (jsonschema validate OK)
# A11y: axe-core sin violaciones críticas; todo el flujo operable con teclado
# Demo: video completo track → master → gestos → grabación de salida
```

**NO toca:** código de producción de los otros dominios (solo tests, docs y el simulador). Si encuentra un bug, lo reporta con reproducción mínima; el dueño del dominio lo arregla.

**Riesgo propio:** ser cuello de botella → su trabajo BLOQUEANTE (el contrato) se entrega el día 0; después su carga es incremental y puede delegar la ejecución de tests a los dueños.

---

### Matriz de propiedad de archivos (quién toca qué)

| Ruta | Dueño |
|---|---|
| `backend/src/audiomind/**`, `backend/tests/**` | Dev 1 |
| `frontend/src/app/**`, `frontend/src/components/*.tsx` (raíz), `globals.css` | Dev 2 |
| `frontend/src/lib/live/**`, `frontend/src/hooks/useLiveEngine*` | Dev 3 |
| `frontend/src/components/live/**` | Dev 2 (estructura) + Dev 3 (audio) — frontera por archivo: `.tsx` presentación = Dev 2, hooks/lib audio = Dev 3 |
| `apps/humanmidi/**`, `apps/bridge/**` | Dev 4 |
| `packages/contracts/**`, `apps/simulator/**`, `e2e/**`, `docs/ux_checklist.md` | Dev 5 |
| `README.md`, `docs/` (arquitectura) | Dev 5 (con aportes de todos) |

## 3. Contratos entre dominios (contract-first, día 0)

Todo el paralelismo depende de estos 3 contratos. **Se definen el día 0 en `packages/contracts/` y no se cambian sin bump de versión.** Esto es DIP aplicado al equipo: los devs dependen del contrato, no de la implementación del otro.

### 3.1 `MasteringParameters` (ya existe — no tocar)
Pydantic en backend, espejo TS en frontend. Gobierna la fase offline. Ver doc 03 §11.

### 3.2 `LiveParams` (NUEVO — el corazón del Live Engine)
JSON Schema único → genera tipos TS (Dev 3) y Python (Dev 4). **El audio nunca viaja aquí, solo parámetros.**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "LiveParams",
  "type": "object",
  "properties": {
    "filter_cutoff":  { "type": "number", "minimum": 200,  "maximum": 12000, "default": 12000 },
    "filter_res":     { "type": "number", "minimum": 0.5,  "maximum": 12,    "default": 0.7 },
    "drive":          { "type": "number", "minimum": 0,    "maximum": 1,     "default": 0 },
    "delay_time":     { "type": "number", "minimum": 50,   "maximum": 800,   "default": 250 },
    "echo_feedback":  { "type": "number", "minimum": 0,    "maximum": 0.8,   "default": 0 },
    "reverb_mix":     { "type": "number", "minimum": 0,    "maximum": 1,     "default": 0 },
    "output_level":   { "type": "number", "minimum": 0,    "maximum": 1,     "default": 0.9 },
    "fx_preset":      { "type": ["string", "null"], "enum": ["clean", "dub", "big_room", "radio", null] },
    "ts":             { "type": "number" }
  },
  "required": ["ts"],
  "additionalProperties": false
}
```

**Regla de neutralidad:** `default` = sin efecto. Si el bridge está caído o el gesto en reposo, el Live Engine usa defaults → el master suena idéntico.

### 3.3 Protocolo WebSocket (bridge ↔ navegador)
```
Bridge → Navegador:  { "type": "live_params",  "data": LiveParams }   (~30 msg/s máx, con debounce)
Navegador → Bridge:  { "type": "state", "data": { "playing", "loop", "position_s", "output_lufs", "output_true_peak", "gesture_mode" } }
Bridge → Navegador:  { "type": "hello", "data": { "version", "midi_port", "gesture_mode" } }   (handshake)
```

- Cada mensaje con `ts`; el navegador ignora mensajes con `ts` anterior al último aplicado (reordenación).
- `live_params` completos (no deltas) — el último estado gana; simple y sin estados perdidos.
- Heartbeat cada 5 s; si el socket cae, el Live Engine congela los últimos valores → neutral en 2 s si el gesto no reenvía.

## 4. SOLID aplicado (código y equipo)

### 4.1 En el código

| Principio | Dónde vive | Ejemplo concreto |
|---|---|---|
| **SRP** | Todos los módulos | `CameraHandler` solo captura; `MidiSender` solo envía; `FXSlot` solo procesa audio; `BridgeListener` solo traduce CC→LiveParams. Una razón de cambio por clase |
| **OCP** | `gestures/` y `lib/live/` | Nuevo gesto = nueva clase `BaseGesture` (ya existente). Nuevo efecto = nuevo slot FX implementando `FXSlot` (interfaz `connect(input: AudioNode): AudioNode`) — sin tocar `audioGraph.ts` |
| **LSP** | `BaseGesture`, `FXSlot`, `MidiSender` | Cualquier gesto o slot sustituye a otro sin cambiar el orquestador; el bridge puede escuchar el puerto MIDI o una API directa sin cambios en el navegador |
| **ISP** | Contratos por dominio | El bridge depende SOLO de `LiveParams`; el Live Engine NO conoce `MasteringParameters`; HumanMidi NO conoce la API REST de mastering. Interfaces pequeñas y cohesivas |
| **DIP** | Bridge, Live Engine, tests | Bridge depende del contrato `LiveParams`, no de HumanMidi ni del navegador. El Live Engine recibe valores ya mapeados — nunca parsea gestos. Tests contra interfaces, no contra concreciones |

### 4.2 En la organización del equipo

| Principio | Interpretación de equipo |
|---|---|
| **SRP** | Cada dev tiene UNA razón de cambio: su dominio. Ownership explícito (matriz de archivos de la sección 2) |
| **OCP** | El sistema acepta nuevas features (nuevo efecto, nuevo gesto, nuevo preset) sin reorganizar al equipo |
| **LSP** | Cualquier dev puede sustituir a otro en un dominio SI los contratos están estables — el conocimiento está en el código y los tests, no en la cabeza |
| **ISP** | Los devs se comunican por contratos (schema + protocolo), no por "pásame el objeto tal". Reuniones solo cuando un contrato cambia |
| **DIP** | El roadmap depende de los contratos, no de las personas: si Dev 4 se bloquea, Dev 3 sigue con el Live Engine usando el simulador de Dev 5 |

## 5. UX/UI: la promesa del Live Engine

La UX de este producto se juega en **qué tan natural se siente tocar el audio con las manos**. Checklist que el Dev 5 audita y el resto implementa:

### 5.1 Onboarding de gestos (primera vez)
- [ ] **Guía visual de gestos** en la pestaña Live: mano virtual animada mostrando cada gesto → qué perilla controla (con el acento serif: "Abrí el *Filtro*").
- [ ] **Calibración:** detectar la mano antes de activar el control; estado "¿Dónde está tu mano?" hasta que aparece.
- [ ] **Modo prueba:** tocar cada perilla sin que suene (dry run) para aprender sin miedo.

### 5.2 Affordance y feedback en vivo
- [ ] **Cada knob muestra su gesto asignado** (icono de mano + etiqueta) — el usuario sabe qué mover para qué efecto.
- [ ] **El knob se mueve con la mano en tiempo real** (mismo componente Knob3D, animación 0.08 s ya definida).
- [ ] **LED del knob** brilla cuando el gesto está activo (color del preset o del acento #627e84).
- [ ] **Meters de salida reaccionan** (AnalyserNode → LUFS/True Peak con los colores meter-safe/warn/clip).
- [ ] **Badge de conexión del bridge:** "Manos conectadas" (verde), "Sin conexión — usando mouse" (gris). Nunca silencio inexplicable.

### 5.3 Estados (nunca vacío ni roto)
- [ ] Sin master: "Subí un audio para masterizar" (botón → Estudio).
- [ ] Master listo, Live cerrado: CTA "Tocá el master en vivo".
- [ ] Bridge caído: banner rojo con recovery ("Reiniciá HumanMidi" / "Seguí con el mouse").
- [ ] Gestos en reposo: hint sutil "Mové los pulgares para abrir el filtro y el reverb".

### 5.4 Accesibilidad y consistencia
- [ ] `prefers-reduced-motion`: los efectos coreografiados se reducen (ya es contrato del doc 04) y **el control por mouse/teclado siempre disponible** (los knobs son operables sin gestos).
- [ ] Contraste de tokens respetado; microcopy rioplatense ("Subí", "Ajustá", "Probá de nuevo").
- [ ] Latencia percibida: mostrar ms del round-trip del control (< 50 ms = "en vivo", > 150 ms = warning).

### 5.5 La promesa de diseño
La pestaña Live NO es una pantalla nueva distinta: es el mismo studio con **una capa más** (la cámara + la cadena FX). Mismos tokens, mismos knobs, mismos ghost/notes ambientales detrás, misma gramática de motion. Si un screenshot no parece del mismo producto, el Dev 2 y el Dev 5 lo rechazan.

## 6. Estrategia de repo y git

### Monorepo (3 apps + 1 paquete de contratos)
```
hackaton-midimastering/
├── apps/
│   ├── studio/          # Next.js — Dev 2 + Dev 3 (Live Engine dentro)
│   ├── humanmidi/       # Python — Dev 4 (migrado del repo actual)
│   └── bridge/          # Python — Dev 4
├── packages/
│   └── contracts/       # live_params.schema.json — Dev 5 (guardián)
├── e2e/                 # Test E2E — Dev 5
└── docs/                # Esta carpeta de arquitectura
```

### GitHub Flow (ramas cortas, PR obligatorios)
1. Rama por feature: `feat/live-engine`, `feat/bridge-ws`, `fix/thumb-jitter`.
2. **PR mínimo de 1 reviewer** (el dueño del dominio tocado; el Dev 5 revisa todo lo que toque UX).
3. **CI en cada PR:** pytest (humanmidi + backend + bridge) + `next build` (studio) + lint. El PR no se mergea si el CI falla.
4. **Tags por milestone:** `hackaton-day2`, `hackaton-day4`, `hackaton-final`.
5. Nada se mergea directo a `main` sin pasar el **gate del Dev 5** (checklist UX + tests).

### Orden de merges para evitar conflictos
- Dev 2 y Dev 3 trabajan en la misma app Next.js → **Dev 2 mergea primero** sus cambios de estructura (rail, pestaña, componentes presentación), luego Dev 3 rellena `lib/live/` y hooks. Si coinciden en el mismo archivo, Dev 3 rebasea sobre Dev 2 (acuerdo explícito).
- Dev 4 y Dev 5 solo tocan `packages/contracts/` por PR con revisión del otro.

## 7. Plan de 7 días (dependencias explícitas)

| Día | Dev 1 Backend | Dev 2 Studio | Dev 3 Live Engine | Dev 4 HumanMidi+Bridge | Dev 5 QA+UX |
|---|---|---|---|---|---|
| **0** | Backend local + suite verde + benchmark render/prebuilt | Setup monorepo + CI (`next build`) | Playground Web Audio (cadena mínima) | Migrar HumanMidi a `apps/` + 26 tests verdes + MIDI virtual OK | **Entregar LiveParams v1 + generador de tipos + simulador** (bloqueante) |
| **1–2** | Endurecer `GET /audio/mastered` + caché; test curl upload→download | Esqueleto `LiveView` + entrada "★ Live" en el rail | `audioGraph.ts` (4 slots) + `setTargetAtTime` + IR reverb | `midi_listener.py` + `gesture_to_params.py` (tabla + escalado log) | Checklist UX + test del contrato + revisión de PRs |
| **3–4** | Endpoint `/live/master` con `Cache-Control` | `FxSlotPanel` + `GestureBadge` + `CameraOverlay` (getUserMedia) | `liveSocket.ts` + `fxPresets.ts` (4 presets) + orden por ts | `smoother.py` + `ws_server.py` + primer loop WS end-to-end | Audit a11y (axe + teclado + reduced-motion) + primeros specs Playwright |
| **5–6** | Optimización prebuilt (~1.5 s) + `docs/benchmarks.md` | Badge de conexión + empty states + landmarks por WS (si aplica) | `recorder.ts` (grabar salida) + meters + vitest | Modo `--mode studio` (5 gestos → 5 CCs) + latencia real < 30 ms | Validación con músico (1 h) + feedback al checklist + E2E con bridge real |
| **7** | Freeze + soporte E2E | Freeze + pulido visual | Freeze + pruebas auditivas | Freeze + soporte E2E | **Gate final: 4 dominios verdes + checklist UX + demo grabada** |

**Dependencias críticas (el grafo):**
```
LiveParams (Dev 5, día 0)
   ├──→ Dev 3: Live Engine (sin esperar a nadie más — usa simulador)
   ├──→ Dev 4: Bridge (sin esperar a nadie más — usa HumanMidi real)
   └──→ Dev 2: render de knobs (etiquetas de gesto)
Master WAV (Dev 1, día 2)
   └──→ Dev 3: transporte del Live (puede usar un WAV local mientras tanto)
Diseño de pestaña (Dev 2, día 2)
   └──→ Dev 3: integración visual
```

Si una dependencia se atrasa, el **simulador de LiveParams** (Dev 5) desbloquea a Dev 3 y Dev 2 — DIP en acción.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Dev 2 y Dev 3 pisan los mismos archivos Next.js | Frontera por directorio: Dev 2 = `components/live/*.tsx` de presentación; Dev 3 = `lib/live/` + hooks de audio. Dev 2 mergea primero |
| Latencia bridge > 50 ms | Bridge en Python con `python-rtmidi` (misma pila que HumanMidi); medición de ms en cada mensaje (Dev 4, `latency.py`); debounce 100–200 ms; fallback Vía B (emisión directa sin MIDI) |
| Zipper/clicks al mover knobs | `setTargetAtTime` (time constant ~20 ms) — contrato técnico del Dev 3; test auditivo en QA |
| MediaPipe 0.10.14 (wheels Python 3.12) | Pin congelado; nadie actualiza sin PR que adapte el código (ya documentado) |
| Masterización "lenta" (44 s) en demo | Presets con prebuilt lookup (~1.5 s) para la demo; el render full queda como feature |
| Gestos compiten entre "tocar" y "controlar" | Modo dedicado `--mode studio` + gesto modificador (puño = control); decisión UX del Dev 5 |
| Scope creep en 7 días | Freeze de features el día 7; cada feature nueva entra por backlog y la aprueba Dev 5 |
| Sesiones en memoria de WaveAI (se pierden al reiniciar) | Para la demo: mantener el backend vivo; Redis queda post-hackaton |
| Escalado del filtro percibido como "saltos" | Escalado **logarítmico** CC→Hz (200–12000 Hz son ~6 octavas) — implementado en `gesture_to_params.py`, testeado por Dev 4 |

## 9. Métricas de éxito del equipo

1. **Día 3:** el simulador de LiveParams mueve los knobs del Live Engine (integración contract-first probada).
2. **Día 5:** primer loop completo gesto real → bridge → WebSocket → filtro audible.
3. **Día 7:** demo E2E — track → master → performance en vivo con gestos + grabación; 26 tests de HumanMidi, suite de backend y suite del bridge en verde; checklist UX aprobado.
4. **Cero conflictos de merge no resueltos:** los dominios solo se tocan por contratos y PRs.
5. **Cualquier dev ausente no bloquea:** los contratos permiten sustitución (LSP organizacional).

---

*Documento: 07_estrategia_equipo_5devs.md · Hackaton midiMastering · 2026-08-20*
