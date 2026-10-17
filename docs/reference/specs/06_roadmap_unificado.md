# 06 — Roadmap Unificado: Masterizar → Tocar en Vivo

> **⚠️ 2026-09-11 · DOCUMENTO HISTÓRICO:** HumanMidi fue removido del producto; el roadmap que lo incluía quedó desactualizado. Ver `../../ESTADO_PROYECTO.md` §3.3 y §5 (el reporte de remoción citado antes nunca se commiteó).

> Fusión de los roadmaps de ambos proyectos en una sola línea de tiempo orientada al hackaton. **El objetivo: masterizar la canción primero y tocarla en vivo con efectos controlados por gestos en una misma interface.**

## 1. Estado actual

### HumanMidi ✅
- [x] MVP Python standalone (SOLID, clean architecture)
- [x] Modos: Drums, Piano, CC Thumbs ⭐, CC Controller
- [x] Puerto MIDI virtual (IAC / loopMIDI)
- [x] Dos manos con estado independiente + anti-notas-colgadas
- [x] Configuración YAML/JSON (deep-merge sobre defaults)
- [x] 26 tests pasando
- [ ] Validación con músicos — en fase de testing

### WaveAI ✅
- [x] Pipeline completo: upload → análisis IA → DSP proporcional → A/B → export
- [x] Motor proporcional (no preset-driven)
- [x] 8 presets macro (backend `PRESET_CHAINS` + frontend cards)
- [x] Módulos DSP opt-in: multiband, dyn EQ, exciter, tape, adaptive comp, stereo imaging, spatial, clipper, truepeak
- [x] A/B player WaveSurfer + AnalysisPanel con meters
- [x] Sistema de diseño dark completo (tokens, knobs, mascotas, motion)
- [x] Gate de licencia (`X-License-Key`)
- [ ] Redis para sesiones (Fase 2); ML Fase 2 (CNN género, XGBoost recommender)

### Live Engine 🔶 (nuevo — el puente)
- [ ] Cadena de FX en tiempo real (Web Audio API): filtro, drive, delay/echo, reverb
- [ ] Bridge gestos (CC) → WebSocket → nodos de audio
- [ ] Pestaña "Live" en el studio (misma interface)

## 2. Fases del hackaton

### Fase 0 — Preparación (día 0)
- [ ] Verificar HumanMidi corre: `python run.py --mode cc-thumbs` (entry: **run.py**, no `src/main.py`)
- [ ] Verificar WaveAI corre: `POST /health` en `localhost:8000`
- [ ] Setup MIDI virtual: IAC Driver (macOS) / loopMIDI (Windows) con nombre en `config.yaml → midi.virtual_port_name`
- [ ] Preparar track demo (WAV ~30 s) + clave de licencia de dev

### Fase 1 — Master primero (días 1–2)
- [ ] Subir el track a WaveAI y masterizarlo (presets + prebuilt lookup ~1.5 s)
- [ ] Confirmar el master WAV se sirve por `GET /audio/mastered` y `/download/wav`
- [ ] El master entra al Live Engine en loop (AudioBufferSourceNode)
- [ ] **Entregable:** canción masterizada sonando en el navegador

### Fase 2 — Live Engine (días 3–4)
- [ ] Cadena de nodos Web Audio: BiquadFilter → WaveShaper → Delay+feedback → Convolver → master
- [ ] Knob3D por slot (ajuste con mouse) — reutilizar `ModulePanel` del studio
- [ ] Meters de salida (AnalyserNode → LUFS / True Peak)
- [ ] **Entregable:** FX en tiempo real sobre el master, operable con mouse

### Fase 3 — Gestos → perillas (días 5–6)
- [ ] **Vía A:** bridge que escucha el puerto MIDI virtual de HumanMidi y traduce CC → LiveParams → WebSocket
- [ ] Mapeos: pulgar derecho → filtro, pulgar izquierdo → reverb, altura → delay, apertura → echo, X → drive
- [ ] Suavizado + debounce (100–200 ms) + `setTargetAtTime` (anti-zipper)
- [ ] Cámara con overlay de manos incrustada en la pestaña Live
- [ ] **Entregable:** master tocado en vivo con las manos, una sola pantalla

### Fase 4 — Pulido y demo (día 7)
- [ ] Presets de FX por palmadas (4 zonas: clean/dub/big_room/radio)
- [ ] Grabación de la salida en vivo (MediaRecorder / captureStream)
- [ ] Estados vacíos y errores del bridge
- [ ] Video demo: track → master → performance en vivo con gestos
- [ ] Repo limpio: prototipos fuera, deps sin uso eliminadas

## 3. Roadmap medio plazo (post-hackaton)

| Trimestre | HumanMidi | WaveAI | Live Engine / Integración |
|---|---|---|---|
| Q1 | Validación con músicos; presets de gestos; grabación/reproducción de gestos | Redis para sesiones; corrección "4x vs 8x oversampling" en MasteringGuide | Bridge Vía B (modo `--mode studio` en run.py); 9 perillas mapeadas |
| Q2 | Plugin JUCE/C++ (VST3/AU/AAX); GUI profesional | ML Fase 2: CNN género + XGBoost recommender | Los gestos disparan presets recomendados por IA para el master |
| Q3 | Aceleración GPU; versión móvil | Deploy/CI, Docker, monitoring | Live Engine multi-usuario: master en la nube, gestos como control remoto |
| Q4 | Comunidad: presets compartidos, cloud sync | Monetización y licencias por volumen | Performance completa: tocar, masterizar y reinterpretar en vivo |

## 4. Métricas de éxito del hackaton

1. **Demo en vivo funcional:** track → master (~1.5 s con prebuilt o ~44 s full) → FX controlados por gestos con latencia perceptible < 50 ms.
2. **Cero regresiones:** 26 tests de HumanMidi siguen pasando; endpoints de WaveAI intactos.
3. **Desacoplamiento probado:** HumanMidi sigue funcionando sin WaveAI y viceversa; el Live Engine funciona con mouse sin gestos.
4. **Audio nunca por la red:** solo parámetros viajan por WebSocket; el sonido es 100% local.
5. **Evidencia:** grabación de pantalla del flujo completo master → performance en vivo.

## 5. Notas de mantenimiento (pitfalls conocidos)

- **MediaPipe:** fijar `0.10.14`; 0.10.9 no tiene wheels Python 3.12+; 0.10.21+ depreca `mp.solutions.hands` (eliminado en 0.10.35).
- **Entry point HumanMidi:** siempre `run.py` (añade raíz al sys.path).
- **WaveAI:** sesiones en memoria (process-local) — se pierden al reiniciar el backend.
- **Divergencia frontend/backend presets:** `PRESET_INFO` difiere de `PRESET_CHAINS` (solo afecta UI, no audio).
- **Limiter:** implementación 8× oversampling; guía educativa dice 4× — corregir texto.
- **Mastering ≠ FX en vivo:** los knobs del Live Engine NO son `MasteringParameters` — no reprocesar el track; son nodos Web Audio en tiempo real.
- **Zipper en cambios de parámetro:** usar `setTargetAtTime` (time constant ~20 ms), nunca asignación directa.
