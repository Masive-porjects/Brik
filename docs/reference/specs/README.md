# 🎵 Hackaton midiMastering — Arquitectura del Ecosistema Unificado

> **⚠️ 2026-09-11: HumanMidi fue REMOVIDO del producto.** Esta carpeta queda como registro histórico del diseño original (fase *en vivo* = Live Engine + Bridge/Source MIDI). El **Live Engine y el bridge también fueron eliminados** (`ba3b4a6`, `92c79bf`, `38c1246`), así que ninguna doc de esta carpeta describe estado vigente — tampoco `05`, que es solo arquitectura de audio histórica. El reporte de remoción citado antes nunca se commiteó: ver `../../ESTADO_PROYECTO.md` §3.3 y §5.

> **Dos ideas, un solo flujo:** WaveAI **masteriza** la canción primero, y el resultado se **toca en vivo** con efectos (reverb, delay, echo, filtro, drive) controlados por un controlador MIDI — todo en una misma interface.

Este índice reúne la documentación de arquitectura que une las dos ideas del proyecto:

| Idea | Documento fuente | Qué es |
|------|-----------------|--------|
| **1. HumanMidi** ~~(REMOVED 2026-09-11)~~ | `README.md`, `ARCHITECTURE.md` | ~~Gestos de la mano → MIDI en tiempo real (MediaPipe + RtMidi)~~ Eliminado |
| **2. WaveAI** | `MASTERING_ECOSYSTEM_SPEC.md` | Estudio de mastering IA: análisis → DSP → export (FastAPI + Next.js) |
| **Unión** | (docs 01, 05, 06) | Master offline primero + Live Engine de FX controlado por MIDI |

---

## 📚 Documentos

| Doc | Contenido |
|-----|-----------|
| [01_vision_unificada.md](01_vision_unificada.md) | La visión: masterizar primero, tocar el resultado en vivo |
| [03_waveai_backend_mastering.md](03_waveai_backend_mastering.md) | Idea 2 — Capa de producción: backend de mastering (FastAPI) |
| [04_waveai_sistema_diseno.md](04_waveai_sistema_diseno.md) | Idea 2 — Sistema de diseño del studio (Next.js) |
| [05_live_engine_gestos_a_master.md](05_live_engine_gestos_a_master.md) | ⭐ El puente: Live Engine — master + FX en tiempo real con gestos |
| [06_roadmap_unificado.md](06_roadmap_unificado.md) | Roadmap conjunto de ambas ideas |
| [07_estrategia_equipo_5devs.md](07_estrategia_equipo_5devs.md) | ⭐ Estrategia para 5 devs: roles, contratos, SOLID, UX/UI, plan 7 días |
| [08_implementacion_llm.md](08_implementacion_llm.md) | ⭐ Prompt para LLM: crea el proyecto completo (fases, contratos, verificación) |

---

## 🏗️ Mapa del ecosistema en una línea

```
[Track original] ──► [WaveAI: master offline (~44 s)] ──► [Master WAV]
                                                                  │
                    [Cámara] ──► [HumanMidi: gestos → CC] ──► [Live Engine: Filtro → Drive → Delay/Echo → Reverb]
                                                                  │
                                                          [Salida en vivo: master + FX en una sola interface]
```

**WaveAI** es la *fase offline*: convierte el mix en un master listo para plataformas (target LUFS por plataforma).
**HumanMidi + Live Engine** son la *fase en vivo*: el master se reproduce y los gestos mueven las perillas de reverb, delay, echo, filtro y drive en tiempo real.

---

## ⚡ Resumen rápido

### Fase offline — WaveAI (Next.js + FastAPI)
- **Pipeline:** `Upload (WAV/MP3 ≤50MB) → Análisis librosa → DSP chain proporcional → Master WAV/MP3`
- **Filosofía:** motor **proporcional, no preset-driven** — los presets definen carácter; los valores DSP se calculan por track
- **Detalle:** 13 etapas DSP (gain staging, match EQ, comp, multiband, dyn EQ, exciter, tape, spatial, clipper 16×, truepeak 8×, dither), sesiones en memoria, `ThreadPoolExecutor(4)`
- **Presets:** 8 macro (Universal, Fuego, Claridad, Cinta, Natural, Espacial, Cinemático, Empuje) con lookup prebuilt ~1.5 s

### Fase en vivo — HumanMidi + Live Engine
- **HumanMidi (Python):** `Cámara → MediaPipe → Gestos → MIDI` — Drums, Piano, CC Thumbs, CC Controller; SOLID; `run.py` como entry point
- **Live Engine (Web Audio API en el navegador):** el master WAV se reproduce con cadena de FX en tiempo real:
  - 👍 Pulgar derecho → **Filtro** (cutoff 200 Hz – 12 kHz)
  - 👍 Pulgar izquierdo → **Reverb** (mix 0–100 %)
  - Altura de mano → **Delay** (50–800 ms)
  - Apertura de mano → **Echo feedback** (0–0.8)
  - Posición X → **Drive** (0–1)
  - Palmada (4 zonas) → presets de FX
- **Bridge:** gestos (CC) → WebSocket → parámetros de nodos Web Audio (`setTargetAtTime`); el audio nunca viaja por la red
- **Interface única:** pestaña "Live" del studio con cámara + overlay de manos, cadena de FX con Knob3D, y meters de salida

---

## 🔗 Fuentes

- `README.md` (HumanMidi) — raíz del repo
- `ARCHITECTURE.md` (HumanMidi) — patrones y SOLID
- `MASTERING_ECOSYSTEM_SPEC.md` (WaveAI) — spec completa verificada contra código
- `PROJECT_SUMMARY.md` (HumanMidi) — resumen del MVP

*Fecha: 2026-08-20 · Documento generado para el hackaton midiMastering.*
