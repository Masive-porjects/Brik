# 08 — Prompt de Implementación para LLM: crear midiMastering completo

> **⚠️ 2026-09-11 · ACTUALIZADO:** El prompt originalmente incluía HumanMidi (gestos → MIDI). HumanMidi fue **removido del producto**; las fases de visión/cámara/gestos de este prompt no deben implementarse. El resto (WaveAI mastering + Live Engine + Bridge MIDI + Simulator) sigue vigente. Ver `../../archive/HUMANMIDI_REMOVAL_REPORT.md`.

> **Qué es este documento:** un prompt de implementación autocontenido para que un agente de código (Claude Code, Codex, OpenCode, etc.) genere el proyecto **midiMastering** completo: mastering offline (WaveAI) + Live Engine Web Audio + bridge de gestos (HumanMidi → FX en vivo).
>
> **Cómo usarlo:** copia este archivo como prompt inicial del agente, junto con la ruta al repo donde trabajar. El agente DEBE leer los documentos fuente antes de escribir código (sección 0).

---

## 0. PRIMERO: lee estos documentos (obligatorio antes de escribir código)

```
MASTERING_ECOSYSTEM_SPEC.md        # La spec verificada de WaveAI: DSP, presets, API, diseño
README.md                          # HumanMidi: modos, config, pitfalls
ARCHITECTURE.md                    # HumanMidi: SOLID y estructura
Hackaton-midiMastering/01_vision_unificada.md
Hackaton-midiMastering/03_waveai_backend_mastering.md
Hackaton-midiMastering/04_waveai_sistema_diseno.md
Hackaton-midiMastering/05_live_engine_gestos_a_master.md
Hackaton-midiMastering/07_estrategia_equipo_5devs.md
```

Todos los valores numéricos de este prompt (presets, rangos, tokens, endpoints) provienen de esos documentos. **No inventes valores DSP ni de diseño: extráelos de los fuentes.** Si un detalle no está en los fuentes ni en este prompt, usa un valor razonable y documéntalo en un TODO.

---

## 1. Contexto del proyecto

**midiMastering** une dos ideas:

1. **WaveAI** — estudio de mastering asistido por IA (Next.js + FastAPI). El usuario sube WAV/MP3, el backend analiza (loudness, espectro, tempo, género) y corre una cadena DSP **proporcional** (no preset-driven) para producir un master WAV/MP3 con A/B player.
2. **HumanMidi** — app Python que convierte gestos de la mano (MediaPipe) en MIDI en tiempo real.

**La unión:** WaveAI masteriza primero (offline, una vez). El master se carga en un **Live Engine** (Web Audio API en el navegador) con cadena de FX en tiempo real (filtro → drive → delay/echo → reverb). Un **bridge** Python escucha el puerto MIDI virtual de HumanMidi y traduce los gestos (CC) a `LiveParams` que envía por WebSocket al navegador. Todo en una misma interface (pestaña "Live" del studio).

**Filosofía de diseño (no negociable):**
- Motor de mastering proporcional, NO preset-driven (los presets definen carácter; los valores DSP se calculan por track).
- Neutral = sin efecto (parámetro neutral = bypass bit-exacto / audio idéntico).
- El audio NUNCA viaja por el socket — solo parámetros y estado.
- SOLID en el código: SRP por módulo, Strategy para gestos y slots FX, DIP hacia los contratos.

---

## 2. Requisitos previos del entorno

- Python 3.12 (pin `mediapipe==0.10.14` — 0.10.21+ depreca `mp.solutions.hands`; 0.10.9 no tiene wheels 3.12+)
- Node.js 20+ / npm
- ffmpeg (para export MP3 del backend)
- macOS (IAC Driver) o Windows (loopMIDI) para el puerto MIDI virtual
- Webcam para HumanMidi

---

## 3. Estructura del monorepo a crear

```
midimastering/
├── README.md                        # índice del repo
├── package.json                     # workspace raíz (npm workspaces: studio)
├── apps/
│   ├── studio/                      # Next.js (App Router) + TypeScript + Tailwind
│   │   ├── package.json
│   │   ├── next.config.mjs
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.ts
│   │   └── src/
│   │       ├── app/
│   │       │   ├── layout.tsx       # tema pre-hydration (localStorage waveai-theme)
│   │       │   ├── page.tsx         # orquestación + pestañas (upload / estudio / live)
│   │       │   └── globals.css      # tokens de diseño (sección 9 de este prompt)
│   │       ├── components/
│   │       │   ├── DropZone.tsx · ModulePanel.tsx · PlatformSelector.tsx
│   │       │   ├── Player.tsx · AnalysisPanel.tsx · ProcessingOverlay.tsx
│   │       │   ├── ModuleSheet.tsx · PaintedModule.tsx · LicenseGuard.tsx
│   │       │   ├── FloatingGhosts.tsx · FloatingNotes.tsx · BigGhostWithNotes.tsx
│   │       │   └── live/
│   │       │       ├── LiveView.tsx         # contenedor pestaña Live (3 columnas)
│   │       │       ├── FxSlotPanel.tsx      # 4 slots FX con Knob3D
│   │       │       ├── GestureBadge.tsx     # "pulgar derecho → Filtro"
│   │       │       ├── CameraOverlay.tsx    # <video> getUserMedia
│   │       │       └── LiveMeters.tsx       # LUFS/true peak de salida
│   │       └── lib/
│   │           ├── api.ts · presets.ts · motion.ts
│   │           └── live/
│   │               ├── liveParams.gen.ts    # generado de packages/contracts
│   │               ├── audioGraph.ts        # cadena de nodos Web Audio
│   │               ├── fxPresets.ts         # clean/dub/big_room/radio
│   │               ├── liveSocket.ts        # cliente WebSocket
│   │               ├── useLiveEngine.ts     # hook React
│   │               └── recorder.ts          # MediaRecorder → WAV
│   ├── humanmidi/                   # Python (migrar del repo actual si existe, si no recrear)
│   │   ├── run.py · quick_start.py · requirements.txt · config/config.yaml
│   │   └── src/
│   │       ├── main.py              # HumanMidiApp (Facade)
│   │       ├── core/                # camera_handler.py · hand_detector.py · midi_sender.py
│   │       ├── gestures/            # base_gesture.py · drums_gesture.py · piano_gesture.py
│   │       │                        #   · cc_thumbs.py · cc_controller.py · studio_gesture.py
│   │       ├── mappers/             # gesture_mapper.py · zone_mapper.py
│   │       ├── ui/                  # visualizer.py · console.py
│   │       └── config/              # settings.py · defaults.py
│   └── bridge/                      # Python: MIDI → LiveParams → WebSocket
│       ├── main.py                  # asyncio: MIDI listener + WS server
│       ├── midi_listener.py         # rtmidi MidiIn → cola asyncio
│       ├── gesture_to_params.py     # tabla CC→LiveParams + escalado (log para filtro)
│       ├── smoother.py              # EMA + dead zone + debounce
│       ├── ws_server.py             # broadcast live_params, heartbeat 5 s
│       ├── latency.py               # medición round-trip
│       ├── requirements.txt
│       └── tests/                   # test_gesture_to_params.py · test_smoother.py
├── backend/                         # FastAPI "AudioMind" (mastering)
│   ├── requirements.txt
│   ├── uploads/ · outputs/ · prebuilt/   # directorios runtime (gitignore)
│   └── src/audiomind/
│       ├── main.py                  # CORS, routers /api, GET /health
│       ├── config.py
│       ├── api/upload.py · mastering.py
│       ├── models/audio.py          # SessionData, ProcessingStatus, MasteringParameters
│       ├── analysis/analyzer.py     # métricas librosa, género, already-mastered
│       ├── processing/              # engine.py · presets.py · loudness.py · truepeak.py
│       │                            #   · clipper.py · multiband.py · dyn_eq.py · exciter.py
│       │                            #   · tape.py · spatial.py · stereo_imaging.py
│       │                            #   · adaptive_comp.py · mono.py · dither.py · oversample.py
│       └── storage/cache.py
├── packages/
│   └── contracts/
│       ├── live_params.schema.json  # LA fuente de verdad (sección 5)
│       └── scripts/gen_types.sh     # genera TS (studio) + dataclass (bridge)
├── simulator/                       # emisor de LiveParams sintéticos (tests/UX sin manos)
│   └── main.py                      # escenarios: sweep, presets, random walk
└── e2e/                             # Playwright
    └── tests/master_to_live.spec.ts
```

---

## 4. FASE 1 — Contratos (`packages/contracts/`) — hacer ESTO PRIMERO

### 4.1 `live_params.schema.json` (copiar EXACTO)

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

### 4.2 Protocolo WebSocket (bridge ↔ navegador)

```
Bridge → Navegador:  { "type": "hello",        "data": { "version": "1.0", "midi_port": "HumanMidi", "gesture_mode": "studio" } }
Bridge → Navegador:  { "type": "live_params",  "data": LiveParams }        # máx ~30 msg/s (debounce)
Navegador → Bridge:  { "type": "state",        "data": { "playing", "loop", "position_s", "output_lufs", "output_true_peak", "gesture_mode" } }
```

- Mensajes completos (no deltas): el último estado gana.
- Navegador ignora mensajes con `ts` menor al último aplicado (reordenación).
- Heartbeat cada 5 s. Si el socket cae > 2 s → Live Engine vuelve a neutral (defaults).
- Puerto del bridge: **WS en `localhost:8765`**.

### 4.3 Generador de tipos

`scripts/gen_types.sh`:
- TS: `json-schema-to-typescript` → `studio/src/lib/live/liveParams.gen.ts`
- Python: `jsonschema` + dataclass manual (o `datamodel-code-generator`) → `bridge/live_params.py` con los defaults del schema.

---

## 5. FASE 2 — Backend mastering (FastAPI "AudioMind")

**Lee `MASTERING_ECOSYSTEM_SPEC.md` (Parte I) y `Hackaton-midiMastering/03_*.md` y respeta TODO lo que dicen.** Resumen de lo no negociable:

### 5.1 Reglas de producto
- Inputs: `.wav`, `.mp3`, máx 50 MB. Outputs: WAV float y MP3 320 kbps (ffmpeg).
- Bit-depth: 16 (dither Lipshitz) o 24 (default). Target loudness default: −14 LUFS.
- Sesiones en memoria (dict de módulo + `SessionCache`), `ProcessingStatus`: `uploaded → analyzing → processing → completed | error`.
- `POST /api/session/{id}/process` con `ThreadPoolExecutor(4)` (prefix "dsp"); progreso 0..1 en la sesión; polling del cliente 500 ms.
- **Lookup prebuilt:** si `preset_id` viene y existe `backend/prebuilt/{filename_stem}_{preset_id}.wav` (size > 0) → copiar y devolver COMPLETED progreso 1.0 SIN correr DSP.
- Licencia: gate en `/process` y `/download/*` (header `X-License-Key`); en entornos dev sin licencia, pasar gratis.

### 5.2 Cadena DSP (`processing/engine.py`, `process_audio`) — 13 etapas en orden
1. Gain staging (peak-normalize −6 dBFS)
2. High-pass 30 Hz (pedalboard `HighpassFilter`)
3. Match EQ (delta = (target−current)×1.8; ×0.8 si already-mastered; clamp ±2 dB; skip < 0.3 dB)
4. Clarity shelf 8 kHz Q0.6 (gain = brightness; skip 0)
5. Warmth tilt 10 kHz Q0.5 (skip 0)
6. Compresor (threshold = −16 − 1.5·punch; ratio ×0.8 si mastered; attack max(3, 20−3·punch) ms; release 200 ms)
7. Board render pedalboard (una pasada)
7a. Compresor adaptativo (opcional; neutral ratio 1.0 = bypass bit-exacto)
7b. Multiband LR4 150 Hz/3 kHz (opcional; neutral = bypass)
7c. Dynamic EQ cuts-only (opcional; neutral = bypass)
7d. Excitador armónico 4 bandas (opcional; neutral = bypass)
—. Bloque espacial (M/S, reverb side, Haas; opcional; check correlación < 0 → safety)
7e. Stereo imaging LR4 (opcional; neutral = bypass)
8. Saturación (tape real o tanh legacy; neutral = untouched)
9. Mono compat lows < 120 Hz (skipped si 7e ya colapsó lows)
10. Loudness target (explícito o derivado del ceiling: −14 + (1 − ceiling/−0.3)·6, clamp [−14, −8]; corrección −12…+6 dB)
11a–b. Codec pre-matching (ceiling seguro por crest)
11b′. Soft clipper 16× oversampled erf-knee (threshold = safe ceiling − 1.5 dB)
11c. True-peak limiter 8× oversampled lookahead (L=4 ms, release ~30 ms, safety net 0 dBFS)
12. Safety normalize (sample > 1.0 → 0.99)
—. Dither (16-bit: TPDF + noise shaping Lipshitz; 24-bit: nada)
13. DR validation (warn si output/input DR < 0.8)
Write: float WAV con `pedalboard.io.AudioFile`.

### 5.3 Presets backend (`processing/presets.py`) — tabla exacta

| Preset | HP | EQ firma | Comp (ratio/atk/rel) | Saturación | Mono< | LUFS | Ceiling | Genres |
|---|---|---|---|---|---|---|---|---|
| Universal | 30 | 250 −2 (Q1.0), 3k +1 (Q0.8) | 1.5/30/200 | — | 120 | −14 | −1.0 | Rock, Pop, Electrónica, Alternativa |
| Fuego | 25 | 80 lowshelf +6 (Q0.7), 250 −3 (Q1.2), 2.5k +2 (Q0.8) | 4.0/10/100 | soft_clip 1.5 | 120 | −9 | −0.3 | Trap, Experimental, Reguetón |
| Claridad | 40 | 12k hshelf +4 (Q0.5), 3k +1.5 (Q0.7), 400 −2 (Q1.0) | 1.8/25/180 | — | 100 | −12 | −1.5 | Clásica, R&B, Cantautor, Jazz, Alternativa, Indie, Rock |
| Cinta | 35 | 200 +2 (Q0.8), 3k +0.5 (Q0.7), 8k −2 (Q0.6) | 2.5/40/300 | tape 2.0 | 120 | −12 | −1.0 | Acústico, Jazz, Cantautor |
| Natural | 20 | (ninguna) | 1.1/60/400 | — | 80 | −14 | −2.0 | Ambiente, Experimental, Electrónica |
| Espacial | 30 | 8k hshelf +2.5 (Q0.5), 200 +1 (Q0.8) | 1.6/30/250 | — | 100 | −12 | −1.0 | Banda sonora, Orquestal, Clásica (width 1.4) |
| Cinemático | 25 | 60 +4 (Q0.7), 250 −2 (Q1.0), 4k +3 (Q0.8) | 5.0/8/80 | tape 3.0 | 120 | −8 | −0.3 | Hip-hop, Trap, R&B |
| Empuje | 20 | 60 lowshelf +6 (Q0.6), 250 −2 (Q1.0), 3k +1.5 (Q0.8), 10k hshelf +5 (Q0.5) | 6.0/6/60 | soft_clip 1.0 | 120 | −8 | −0.3 | EDM, House, Techno |

### 5.4 `MasteringParameters` (Pydantic, `models/audio.py`)
Campos: `clarity_wet` (0–1, .15), `clarity_brightness_db` (±6, +1.0), `compression_ratio` (1–10, 2.0), `limiter_ceiling_db` (−3…0, −1.0), `transient_boost_db` (0), `saturation_drive_db` (0), `saturation_warmth_db` (0), `stereo_width` (1.0), `haas_delay_ms` (0), `output_bit_depth` (16/24, 24), `target_lufs_db` opcional + grupos opt-in (`multiband_*`, `dyn_eq_*`, `exciter_band*`, `tape_*`, `adaptive_comp_*`, `stereo_imaging_*` con `*_enabled`; neutral = bypass).

### 5.5 Análisis (`analysis/analyzer.py`)
- Métricas: `integrated_lufs` (BS.1770-4), `true_peak_db` (sample-domain), `dynamic_range_db` (RMS frame 2048/hop 512, 10% más fuerte − 10% más suave), `spectral_centroid`, `tempo_bpm` (beat_track), `crest_factor_db`, `duration_seconds`, `sample_rate`, `channels`.
- Género rule-based con scores (tabla completa en la spec §4.2): hip_hop 0.8, electronic 0.85, reggaeton 0.8, jazz 0.7, classical 0.75, acoustic 0.7, pop 0.6, rock 0.65; fallback "other" 0.3.
- Already-mastered: score acumulado, umbral ≥ 0.8 (tabla de puntos en spec §4.3). Si detectado: `am_factor = 0.8` + 0.4 dB headroom limiter + banner "Audio ya masterizado".

### 5.6 API (resumen — respetar rutas exactas)
`POST /api/upload` · `POST /api/session/new` · `GET /api/session/{id}` · `POST /api/session/{id}/process` (query `preset_id`) · `GET /api/session/{id}/audio/{original|mastered}` · `GET /api/session/{id}/raw` y `/raw-mastered` · `GET /api/session/{id}/download/{wav|mp3}` · `GET /api/license/status` · `POST /api/license/activate` · `GET /health` (sin prefijo /api).

### 5.7 Verificación backend
```bash
pip install -r backend/requirements.txt
uvicorn audiomind.main:app --port 8000 &
curl -s localhost:8000/health
curl -s -F "file=@demo.wav" localhost:8000/api/upload          # → session id
curl -s -X POST localhost:8000/api/session/{id}/process -H "Content-Type: application/json" -d '{"compression_ratio": 2.0}'
curl -s localhost:8000/api/session/{id}/audio/mastered -o m.wav && file m.wav   # → WAV audio
```

---

## 6. FASE 3 — HumanMidi (Python, gestos → MIDI)

**Si el repo actual ya tiene `humanmidi/` funcional: migrarlo a `apps/humanmidi/` (estructura interna intacta) y verificar sus 26 tests. NO reescribir lo que funciona.**

**Si hay que recrearlo (mínimo funcional):**
- `run.py`: añade la raíz al `sys.path` y llama a `src.main` — **el entry point SIEMPRE es `run.py`** (`src/main.py` directo falla por imports).
- `requirements.txt`: `mediapipe==0.10.14` (pin), `opencv-python`, `python-rtmidi`, `numpy`, `PyYAML`.
- `src/core/camera_handler.py`: captura OpenCV (device id, resolución, FPS desde config).
- `src/core/hand_detector.py`: MediaPipe `mp.solutions.hands`, landmarks, dedos extendidos, modelo complexity 0/1, máx 2 manos.
- `src/core/midi_sender.py`: RtMidi puerto virtual (nombre de config `midi.virtual_port_name`), NoteOn/Off, CC, Pitch Bend.
- `src/gestures/base_gesture.py`: ABC `BaseGesture.detect(landmarks) -> GestureEvent`.
- Gestos: `drums_gesture.py` (4 zonas X, notas 36/38/42/49, velocity por velocidad, cooldown 10 frames), `piano_gesture.py` (5 dedos offsets 0/2/4/5/7, octava por altura 2–6, anti-notas-colgadas), `cc_thumbs.py` (pulgar izq CC 92, pulgar der CC 74, suavizado + dead zone), `cc_controller.py` (legacy: CC74/CC1/pitch bend).
- `src/mappers/gesture_mapper.py` (evento→MIDI), `src/mappers/zone_mapper.py`.
- `src/ui/visualizer.py` (overlays: landmarks, bbox, zonas, FPS, paneles CC), `src/ui/console.py`.
- `src/config/settings.py` (carga YAML/JSON con deep-merge sobre `defaults.py`).
- `config/config.yaml` con secciones `midi`, `camera`, `hand_detector`, `gestures.{drums,piano,cc_controller}`, `ui`.
- Tests mínimos: `tests/test_midi_sender.py`, `test_hand_detector.py`, `test_gestures.py`.

### 6.1 NUEVO: `studio_gesture.py` (modo studio, el puente hacia el Live Engine)

`python run.py --mode studio` — mapea 5 gestos + palmadas a CCs fijos (la tabla EXACTA):

| CC / Nota | Origen (gesto) | Parámetro | Escalado |
|---|---|---|---|
| CC 74 | Pulgar derecho | `filter_cutoff` | LOG: `200 * (12000/200)^(v/127)` Hz |
| CC 92 | Pulgar izquierdo | `reverb_mix` | `v/127` (0–1) |
| CC 71 | Altura de mano | `delay_time` | `50 + 750*(v/127)` ms |
| CC 73 | Apertura de mano | `echo_feedback` | `0.8 * v/127` |
| CC 16 | Posición X | `drive` | `v/127` |
| Nota 36/38/42/49 | Palmada zona 0–3 | `fx_preset` | clean / dub / big_room / radio |

Implementar reutilizando `cc_thumbs` para los pulgares + altura/apertura/X de `piano_gesture`/`cc_controller`. Emitir los 6 mensajes en cada frame con suavizado EMA (alpha 0.3) + dead zone ±2 CC.

### 6.2 Verificación HumanMidi
```bash
cd apps/humanmidi && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py --list-midi          # lista puertos MIDI
pytest tests/ -v                   # 26 tests (o los equivalentes recreados) verdes
# Manual (opcional, requiere cámara): python run.py --mode cc-thumbs
```

---

## 7. FASE 4 — Bridge (Python: MIDI → LiveParams → WebSocket)

### 7.1 Archivos y lógica

- `midi_listener.py`: `rtmidi.MidiIn`, `open_port` con el nombre del puerto virtual (config: "HumanMidi"), callback → cola `asyncio.Queue`. Convertir mensajes: CC → (número, valor), NoteOn → (nota, velocity).
- `gesture_to_params.py`: implementar la tabla de la sección 6.1 (CC 74/92/71/73/16 + notas 36/38/42/49) → dict `LiveParams` parcial (solo campos presentes, con `ts = time.time()`). El resto de campos quedan en default.
- `smoother.py`: EMA por parámetro (alpha 0.3), dead zone ±2 CC, debounce: no emitir más de ~30 msg/s; emitir solo si algún valor cambió > umbral.
- `ws_server.py`: servidor `websockets` en `localhost:8765`; broadcast de `{"type": "live_params", "data": LiveParams}` a todos los clientes; heartbeat 5 s (mensaje `ping` o `hello` periódico); recibir `state` del navegador (log).
- `latency.py`: el bridge añade `ts` de emisión; el navegador reporta `latency_ms` en `state`; log si > 50 ms.
- `main.py`: asyncio — levantar MIDI listener + WS server juntos; `--simulate` flag para emitir escenarios sintéticos (para pruebas sin cámara).

### 7.2 Escalado logarítmico del filtro (crítico)
`filter_cutoff = 200 * (12000/200) ** (cc/127)` — 200 Hz–12 kHz son ~6 octavas; escalado lineal haría saltos perceptibles.

### 7.3 Verificación bridge
```bash
cd apps/bridge && pip install -r requirements.txt
python -m src.main &                # escucha MIDI + WS :8765
# Test sintético: python tools/midi_test_send.py   (envía CCs 74/92/71/73/16 + nota por el puerto)
#   → websocat ws://localhost:8765  →  ver live_params con ts
pytest tests/ -q
```

---

## 8. FASE 5 — Studio Next.js + Live Engine

### 8.1 Base del studio (WaveAI frontend)

**Lee `MASTERING_ECOSYSTEM_SPEC.md` Parte II y `Hackaton-midiMastering/04_*.md`** y respeta el sistema de diseño. Resumen:

- App Router, TypeScript, Tailwind. Layout `h-screen overflow-hidden`, 3 columnas flex con scroll independiente.
- Rail lateral: Home · Library · Estudio (abre Macro-Carácter) · **★ Live (nueva)** · Guides · ThemeToggle.
- `page.tsx`: orquestación. Estados: subir audio → análisis (polling 500 ms, timeout 90 s) → procesar (timeout 600 s, AbortController) → player A/B + download.
- Componentes: DropZone, ModulePanel (8 cards macro + Ajuste Fino con 9 knobs: Reverb wet 0–1 .05, Brillo ±6 .5, Ratio 1–10 .5, Ceiling −3…0 .1, Punch 0–6 .5, Drive 0–10 .5, Warmth ±6 .5, Width .5–2 .1, Haas 0–40 ms 1), PlatformSelector (Automático/Spotify −14/Apple −16...), Player (2 WaveSurfer apilados), AnalysisPanel (meters LUFS/TruePeak/Crest + métricas), ProcessingOverlay (anillo SVG progreso), LicenseGuard (sessionStorage `waveai_license_key`, header `X-License-Key`).
- Microcopy en español latino neutro/colombiano (sin voseo): "Sube tu audio", "Ajusta", "Prueba de nuevo".
- Motion: GSAP + Framer Motion; helpers `fadeUp` y `VIEW_TRANSITION` en `lib/motion.ts`; todo con guard `prefers-reduced-motion`; ambient (FloatingGhosts 8, FloatingNotes 16, BigGhostWithNotes) seeded/determinista, `aria-hidden`.

### 8.2 Tokens de diseño (`globals.css`) — valores exactos (dark default)

| Rol | Token | Valor |
|---|---|---|
| Fondo app | `--bg-app` | `#0b0b0c` |
| Sidebar | `--bg-sidebar` | `#09090a` |
| Superficies | `--bg-primary/secondary/tertiary/elevated` | `#0a0a0c / #121216 / #1a1a20 / #22222a` |
| Texto | `--text-primary/secondary/muted` | `#e8e8e8 / #8a8a8a / #555555` |
| Acento | `--accent-primary/secondary` | `#627e84 / #829ca1` |
| Status | `--accent-success/warning/error` | `#34c759 / #ff9500 / #dc2626` |
| Meters | `--meter-safe/warn/clip` | `#34c759 / #ff9500 / #ff3b30` |
| Waveforms | `--waveform-original/mastered` | `#484855 / #00d4aa` |
| Glass | `--bg-glass/elevated` | `rgba(18,18,22,0.6) / rgba(26,26,32,0.55)` |
| Bordes | `--border-subtle/strong` | blanco @ 5% / 12% |
| Sombras | `--shadow-card/heavy` | `0 8px 32px rgba(0,0,0,.3) / 0 25px 60px rgba(0,0,0,.5)` |

Presets identity: universal `#ff3b30/#ff6b35`, fuego `#ff6b00/#ff3b30`, claridad `#ffd700/#ffaa00`, cinta `#ff8c00/#ff6b00`, natural `#34c759/#30d158`, espacial `#af52de/#8944b8`, cinematico `#ff375f/#bf5af2`, empuje `#ff453a/#ff3b30`. Tipografía: Inter 300–700 + Instrument Serif italic para `.serif-accent`. Light theme vía `html[data-theme="light"]` + script pre-hydration.

### 8.3 Live Engine (Web Audio) — `lib/live/`

`audioGraph.ts` — cadena EXACTA de nodos:
```
source (AudioBufferSourceNode, master WAV, loop)
  → filter (BiquadFilterNode, "lowpass", frequency, Q)
  → drive (WaveShaperNode, curva tanh precalculada, 1024 muestras)
  → delay (DelayNode) + fb (GainNode: delay → fb → delay)
  → dry/wet (GainNode reverb_mix) + convolver (ConvolverNode, IR)
  → master (GainNode output_level)
  → analyser (AnalyserNode) → destination
```

Reglas NO negociables:
- `new AudioContext({ latencyHint: "interactive" })`.
- **Todo cambio de parámetro vía `setTargetAtTime(value, ctx.currentTime, 0.02)` — NUNCA asignación directa** (anti-zipper).
- IR de reverb: generado sintéticamente (ruido blanco con decaimiento exponencial ~2 s) o archivo corto incluido.
- Neutral (defaults del schema) = el master suena idéntico al original.
- Socket caído > 2 s → volver a neutral.

`fxPresets.ts`:
- `clean` = todos neutral.
- `dub` = delay_time 320, echo_feedback 0.45, reverb_mix 0.15.
- `big_room` = reverb_mix 0.6, delay_time 200.
- `radio` = filter_cutoff 3000, drive 0.2.

`liveSocket.ts`: conectar a `ws://localhost:8765`; aplicar mensajes `live_params` en orden por `ts`; heartbeat; exponer estado de conexión ("hands_connected" / "mouse_only").

`useLiveEngine.ts`: hook que recibe el master WAV (fetch a `GET /api/session/{id}/audio/mastered`), monta el grafo, suscribe al socket, aplica params, expone meters (LUFS aproximado desde AnalyserNode + true peak) y el estado para la UI.

`recorder.ts`: `AudioContext.captureStream()` + MediaRecorder → descarga WAV/webm.

### 8.4 Pestaña Live (`components/live/`)
- `LiveView.tsx`: 3 columnas — cámara (`CameraOverlay`, getUserMedia) | cadena FX (`FxSlotPanel` con 4 slots, cada uno con Knob3D + `GestureBadge` "pulgar derecho → Filtro") | meters + estado (`LiveMeters`, badge de conexión, botón grabar).
- Knobs también operables con mouse/teclado (accesibilidad; funciona sin gestos).
- Empty states: sin master → "Sube un audio para masterizar" (CTA → Estudio); bridge caído → banner con "Sigue con el mouse".

### 8.5 Verificación studio
```bash
cd apps/studio && npm install && npm run dev
# http://localhost:3000 — flujo: subir WAV → masterizar → pestaña Live → knobs con mouse
npm run build && npm run lint
```

---

## 9. FASE 6 — Simulador y E2E

### 9.1 `simulator/main.py`
Emite `LiveParams` sintéticos por WS a `localhost:8765` (o directo al navegador):
- `--scenario sweep`: barre `filter_cutoff` 200→12000 en 10 s.
- `--scenario presets`: cicla clean→dub→big_room→radio cada 3 s.
- `--scenario random`: random walk de todos los parámetros (suavizado).
Útil para desarrollar el Live Engine y para la demo sin cámara.

### 9.2 `e2e/tests/master_to_live.spec.ts` (Playwright)
1. Subir WAV demo → esperar masterización → ver A/B player.
2. Abrir pestaña Live → ver cadena FX renderizada.
3. Lanzar simulador `presets` → verificar que los knobs cambian (estado visible) y el badge de conexión.
4. (Opcional) captura de pantalla para la demo.

---

## 10. Orden de implementación recomendado (fases bloqueantes)

```
FASE 1 contracts (schema + protocolo)      ← hacer primero, todo depende de esto
FASE 2 backend mastering                   ← verificar con curl
FASE 3 humanmidi (migrar o recrear)        ← verificar con pytest
FASE 4 bridge                              ← verificar con midi_test_send.py
FASE 5 studio + Live Engine                ← verificar con npm run dev + simulador
FASE 6 simulador + e2e                     ← verificación integral
```

Puedes paralelizar FASE 2, 3 y 4 después de FASE 1 (no dependen entre sí). FASE 5 depende de FASE 2 (master WAV) y FASE 4 (socket) — pero el simulador (FASE 6, escribirlo temprano) desbloquea el desarrollo del Live Engine sin esperar.

---

## 11. Criterios de éxito finales (todos deben cumplirse)

1. `curl localhost:8000/health` → ok; upload → process → download WAV válido.
2. `pytest apps/humanmidi/tests -v` verde (26 tests) y `pytest apps/bridge/tests -q` verde.
3. `npm run build` en studio verde; página carga sin errores de consola.
4. El master suena en loop en la pestaña Live; con LiveParams neutral, es idéntico al original (A/B).
5. `simulator --scenario sweep` mueve el filtro en vivo sin clicks (anti-zipper OK).
6. Con cámara + HumanMidi `--mode studio`: pulgar derecho abre el filtro, pulgar izquierdo sube el reverb, palmadas cambian presets.
7. Socket caído → el audio vuelve a neutral en < 2 s.
8. Demo reproducible: track → master → performance en vivo → grabación de salida.

## 12. Pitfalls (NO ignorar)

- `mediapipe==0.10.14` pin. 0.10.21+ depreca `mp.solutions.hands` (eliminado en 0.10.35); 0.10.9 no tiene wheels Python 3.12+.
- Entry point HumanMidi SIEMPRE `run.py` (sys.path).
- Sesiones de WaveAI en memoria — se pierden al reiniciar el backend.
- `PRESET_INFO` del frontend puede diferir del backend (solo UI, no audio) — no "arreglar" el backend para que coincida.
- El limiter es 8× oversampling (la guía educativa dice 4× — si creas MasteringGuide, escribe 8×).
- Los knobs del Live Engine NO son `MasteringParameters` — no reprocesar el track; son nodos Web Audio.
- El escalado del filtro es logarítmico (sección 7.2) — lineal produce saltos.
- Neutral = bypass bit-exacto en el backend; neutral = audio idéntico en el Live Engine. Preservarlo en TODAS las rutas.
