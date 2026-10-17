# 01 — Visión Unificada: Masterizar primero, Tocar el resultado en vivo

> **⚠️ 2026-09-11 · DOCUMENTO HISTÓRICO:** HumanMidi (gestos de mano → MIDI) fue removido del producto. La visión vigente hoy = **WaveAI** (mastering offline) + **Mix Engine**. El **Live Engine y el bridge también fueron eliminados** (`ba3b4a6`, `92c79bf`, `38c1246`), así que la fase *en vivo* ya no existe. Ver `../../ESTADO_PROYECTO.md` §3.3 y §5 (el reporte de remoción citado antes nunca se commiteó).

## 1. Por qué unir estas dos ideas

El proyecto **HumanMidi** resuelve la *entrada*: convertir gestos de la mano en MIDI en tiempo real, sin tocar un instrumento físico. El proyecto **WaveAI** resuelve la *producción*: convertir una mezcla en un master profesional listo para plataformas, con análisis IA y DSP proporcional.

**La unión rediseñada:** WaveAI masteriza la canción primero (offline, una sola vez) y el resultado se reproduce en un **Live Engine** — una cadena de efectos en tiempo real (reverb, delay, echo, filtro, drive) que HumanMidi controla con las manos, todo en una misma interface.

```
┌────────────────────────── FASE OFFLINE ──────────────────────────┐
│  WaveAI: Track → Análisis IA → DSP proporcional → Master WAV │
└──────────────────────────────────────────────────────────────────┘
                              │  (una sola vez, ~44 s por track)
                              ▼
┌────────────────────────── FASE EN VIVO ──────────────────────────┐
│  Live Engine: Master WAV → Filtro → Drive → Delay/Echo → Reverb  │
│                    ▲  controlado por gestos                      │
│  HumanMidi: Cámara → MediaPipe → Gestos → CC → knobs             │
└──────────────────────────────────────────────────────────────────┘
```

**Por qué así:** la masterización es un proceso pesado y determinista (oversampling 8×/16×, limiter lookahead, análisis librosa) — no se puede ejecutar en tiempo real. Los efectos de actuación (reverb, delay, echo, filtro) sí son tiempo real. Separar las dos fases permite que cada motor tenga su presupuesto correcto: minutos para el master, milisegundos para el live.

## 2. Principios compartidos de diseño

| Principio | HumanMidi | WaveAI | Live Engine |
|-----------|-----------|------------|-------------|
| **Modularidad** | SOLID, Strategy (BaseGesture) | Módulos DSP separados | Slots de FX intercambiables (filtro/drive/delay/reverb) |
| **Neutral = sin efecto** | Gesto no detectado = sin evento | Parámetro neutral = bypass bit-exacto | Mix 0 = audio intacto |
| **Configurable sin tocar código** | `config/config.yaml` | `MasteringParameters` (Pydantic) | `LiveParams` (JSON por socket) |
| **Estado independiente** | Estado por mano (2 manos sin interferencia) | Sesiones por upload (uuid) | Estado por nodo de audio |
| **Seguridad ante fallo** | Anti-notas-colgadas (Note Off) | Safety normalize + DR validation | Bypass total si el gesto desaparece |
| **Proporcional, no preset** | Gesto→CC continuo (0–127) | Análisis→parámetros continuos | CC→parámetro de nodo continuo |

## 3. Flujo creativo completo (visión de producto)

1. **Grabar:** el músico toca (con HumanMidi o cualquier instrumento) y exporta un mix WAV/MP3.
2. **Masterizar (offline):** el mix entra a WaveAI → análisis IA → DSP proporcional → master WAV con target LUFS por plataforma.
3. **Tocar el master en vivo:** el master se carga en el Live Engine (loop o one-shot).
4. **Perform con las manos:** los gestos abren el filtro (pulgar derecho), mandan reverb (pulgar izquierdo), ajustan delay (altura de mano), echo (apertura) y drive (posición X).
5. **Grabar la performance:** la salida en vivo se graba tal cual suena.

El círculo se cierra: **crear → masterizar → reinterpretar en vivo**, todo desde una pantalla.

## 4. Stack tecnológico unificado

| Capa | Tecnología | Rol |
|------|-----------|-----|
| Visión | MediaPipe `mp.solutions.hands` (0.10.14) | Hand tracking 21 landmarks |
| Cámara | OpenCV | Captura de frames |
| MIDI | RtMidi | Puerto virtual (IAC / loopMIDI) |
| Performance | Python 3.8+ | HumanMidi standalone |
| Mastering offline | FastAPI "AudioMind" + pedalboard + librosa | Análisis + DSP pesado |
| Frontend studio | Next.js + WaveSurfer + GSAP | UI unificada, player A/B |
| **Live Engine** | **Web Audio API (navegador)** | **FX en tiempo real: reverb, delay, echo, filtro, drive** |
| **Bridge** | **WebSocket** | **Gestos (CC) → parámetros del Live Engine** |

## 5. Reglas de oro del ecosistema

1. **El motor de mastering es proporcional, no preset-driven** — los presets definen carácter y targets; los valores reales se calculan por track.
2. **Masterizar y tocar son fases separadas** — el master se produce una vez (offline); los efectos se tocan siempre (tiempo real). Nunca mezclar los dos presupuestos.
3. **Cada capa es independiente** — HumanMidi funciona sin WaveAI (MIDI a cualquier DAW); WaveAI funciona sin HumanMidi (sube un archivo y masteriza); el Live Engine funciona sin gestos (knobs con mouse). La integración es un añadido, no un acoplamiento.
4. **El audio no viaja por el socket** — solo parámetros y estado; el sonido es local en el navegador (cero latencia de red para el audio).
5. **Evidencia verificable** — toda afirmación numérica de la spec de WaveAI es trazable a código; los claims no verificados se omiten.
