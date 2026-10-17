# 05 — Live Engine: Primero el Master, Después los Efectos en Vivo

> **⚠️ 2026-10-13 · DOCUMENTO HISTÓRICO:** HumanMidi, el **Live Engine**, el **Bridge** y el **Simulator** fueron **todos eliminados** del producto (`ba3b4a6` 27-Sep para el Live Engine; `92c79bf` y `38c1246` para el stack de gestos/MIDI). Este documento se conserva solo como registro del diseño original y **no describe estado vigente**. Ver `../../ESTADO_PROYECTO.md` §3.3 y §5.

> El punto de unión de las dos ideas, rediseñado: **WaveAI masteriza la canción primero (offline) y el resultado se toca en vivo con efectos controlados por gestos de HumanMidi, todo en una misma interface.**

## 1. El nuevo flujo (invertido respecto a la v1)

```
[Track original WAV/MP3]
        │
        ▼
┌─────────────────────────── WaveAI (FASE OFFLINE, una sola vez) ───────────────────────────┐
│  Análisis IA → DSP proporcional (44 s por track de 3 min) → [Master WAV]                     │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────── LIVE ENGINE (FASE EN VIVO, tiempo real) ──────────────────────────┐
│  Master WAV → [Filtro] → [Drive] → [Delay/Echo] → [Reverb] → Salida en vivo                 │
│                              ▲                                                               │
│        HumanMidi: Cámara → MediaPipe → Gestos → CC → knobs del Live Engine                  │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

**La masterización NO es un efecto en vivo**: es un proceso pesado (oversampling 8×/16×, limiter lookahead, análisis librosa) que tarda decenas de segundos. Por eso se ejecuta **una vez, offline**. Lo que sí puede ser tiempo real son los efectos de actuación (reverb, delay, echo, filtro, drive) — y esos los controla HumanMidi con las manos.

## 2. Dos motores, dos presupuestos

| | Motor de mastering (WaveAI) | Live Engine |
|---|---|---|
| Momento | Offline, una sola vez por track | Online, cada frame |
| Presupuesto | Minutos (44 s / track 3 min) | < 10 ms de latencia de audio |
| Naturaleza | DSP proporcional, determinista | Efectos de performance, expresivos |
| Parámetros | `MasteringParameters` (Pydantic) | `LiveParams` (nodos de audio en tiempo real) |
| Control | Presets + knobs de ajuste fino | **Gestos de HumanMidi** |
| Neutral | Bypass bit-exacto | Pasa el audio intacto (dry/wet = 0) |

## 3. Arquitectura del Live Engine

Dos implementaciones posibles:

### Opción A — Web Audio API en el navegador (recomendada)
La interface unificada ES el studio WaveAI (Next.js). Una pestaña/modo **"Live"** carga el master WAV y monta una cadena de nodos Web Audio:

```
AudioBufferSourceNode (master WAV, loop) 
        → BiquadFilterNode (filtro: LP/BP, cutoff + Q)
        → WaveShaperNode (drive/saturación)
        → DelayNode + GainNode feedback (delay/echo)
        → ConvolverNode (reverb con IR) + GainNode dry/wet
        → GainNode master → AnalyserNode (meters) → AudioContext.destination
```

- **Ventajas:** el audio corre 100% local en el navegador (cero latencia de red para el sonido); la cámara de HumanMidi se muestra en la misma página; nada que instalar.
- **Control:** HumanMidi (Python) → bridge → **WebSocket** → los nodos se actualizan en tiempo real (parámetros con `setTargetAtTime` para evitar zippers).

### Opción B — Motor Python (sounddevice + numpy)
El Live Engine corre en la misma máquina que HumanMidi (callback de audio en tiempo real procesando buffers numpy).

- **Ventajas:** sin navegador; más control DSP; misma pila que HumanMidi.
- **Desventajas:** la "misma interface" hay que construirla (el visualizer de HumanMidi + knobs), o exponer un mini-servidor HTTP/WebSocket para la UI.

**Recomendación hackaton:** Opción A — es la que cumple "una misma interface" con el menor esfuerzo: el studio WaveAI ya tiene el diseño de knobs, el player y los meters; solo hay que añadir la cadena de FX y el socket.

## 4. Cadena de efectos en vivo (propuesta)

| Slot | Efecto | Nodo Web Audio | Parámetros |
|---|---|---|---|
| 1 | Filtro | `BiquadFilterNode` | `filter_cutoff` (200 Hz – 12 kHz), `filter_res` (Q 0.5–12) |
| 2 | Drive | `WaveShaperNode` | `drive` (0–1, curva tanh precalculada) |
| 3 | Delay/Echo | `DelayNode` + feedback `GainNode` | `delay_time` (50–800 ms), `echo_feedback` (0–0.8) |
| 4 | Reverb | `ConvolverNode` (IR) | `reverb_mix` (0–1, dry/wet) |
| Out | Master | `GainNode` + `AnalyserNode` | `output_level`, meters de salida |

Orden pensado para performance: el filtro modela el "color" (como el CC 74 que HumanMidi ya envía), el drive añade carácter, el delay/echo crea espacio rítmico, y el reverb envuelve. Todos los slots tienen **bypass natural** (mix 0 o neutral) para que el master suene igual si no hay gestos.

## 5. Mapeo gesto → perilla (reutiliza el vocabulario de HumanMidi)

| Gesto HumanMidi (existente) | Perilla del Live Engine | Rango | Nota |
|---|---|---|---|
| 👍 Pulgar derecho (CC 74) | `filter_cutoff` | 200 Hz – 12 kHz | Natural: CC 74 ya es Filter en el ecosistema MIDI |
| 👍 Pulgar izquierdo (CC 92) | `reverb_mix` | 0 – 100 % | Suavizado + dead zone ya implementados en `cc_thumbs` |
| Altura de la mano (piano) | `delay_time` | 50 – 800 ms | Octava baja = delay corto, octava alta = largo |
| Apertura de la mano (CC 1) | `echo_feedback` | 0 – 0.8 | Mano cerrada = sin eco, abierta = repeticiones largas |
| Posición X (Pitch Bend) | `drive` | 0 – 1 | Barrido lateral = saturación progresiva |
| Palmada (4 zonas drums) | Presets de FX | — | Zona 0 = limpio, zona 1 = dub, zona 2 = big room, zona 3 = radio |

**Clave:** los gestos producen valores continuos con suavizado y dead zone — exactamente lo que un knob en vivo necesita. El ecosistema completo es "proporcional": HumanMidi mapea gesto→CC continuo, el Live Engine mapea CC→parámetro de nodo continuo.

## 6. Bridge de control (gestos → navegador)

```
HumanMidi (Python)                          WaveAI Live (Navegador)
┌──────────────────────┐   WebSocket/JSON   ┌─────────────────────────────┐
│ run.py --mode studio │ ──────────────────► │ /live/ws (socket.io/ws)     │
│  CC Thumbs / Piano   │   LiveParams        │  → setTargetAtTime en nodos │
│  + overlay cámara    │ ◄────────────────── │  → estado + meters de vuelta│
└──────────────────────┘                     └─────────────────────────────┘
```

- **Vía A (desacoplada):** el bridge escucha el **puerto MIDI virtual** de HumanMidi y traduce CC → `LiveParams` → WebSocket. HumanMidi no se toca.
- **Vía B (directa):** HumanMidi emite `LiveParams` directamente (integración en `run.py` con un modo `--mode studio`). Menos latencia, más acoplamiento.
- **Recomendación:** Vía A primero (demo en 1 día, cero cambios en HumanMidi), Vía B después.

## 7. La misma interface: pestaña "Live" del studio

Extensión del sistema de diseño existente (doc 04), sin romper nada:

```
Left rail                    Canvas (Live mode)                  Right panel
├─ Home                      ├─ Cámara con overlay de manos      ├─ Meters de salida (LUFS/True Peak)
├─ Library                   ├─ Cadena de FX visualizada         ├─ Estado de gestos (qué CC llega)
├─ Estudio (mastering)       │  Filtro → Drive → Delay → Reverb  └─ Record en vivo (grabar salida)
├─ ★ Live (nuevo)            ├─ Knob3D por slot (ajuste fino con mouse TAMBIÉN)
│   └─ abre el live engine   └─ Player del master (loop / one-shot)
└─ ThemeToggle (bottom)
```

- Los **mismos `Knob3D`** del Ajuste Fino se reutilizan: al moverlos con el mouse se ve que el gesto los empuja igualmente (o viceversa).
- El **overlay de cámara** de HumanMidi (landmarks, bbox, FPS) se incrusta en el canvas como fuente de video — la interface es una sola pantalla.
- Los **meters** del AnalysisPanel (LUFS, True Peak) se reutilizan para la salida en vivo (AnalyserNode → mismos números).
- Micro-copy en español latino neutro/colombiano (sin voseo): "Sube el pulgar para abrir el filtro".

## 8. Contrato de datos (LiveParams)

```json
// Bridge → Navegador (WebSocket, ~30 msg/s máximo con debounce)
{
  "filter_cutoff": 4200,
  "filter_res": 2.5,
  "drive": 0.35,
  "delay_time": 210,
  "echo_feedback": 0.4,
  "reverb_mix": 0.22,
  "output_level": 0.9,
  "fx_preset": null          // o "dub" | "big_room" | "radio" | "clean"
}

// Navegador → Bridge (estado)
{
  "playing": true, "loop": true, "position_s": 12.4,
  "output_lufs": -12.1, "output_true_peak": -1.3,
  "gesture_mode": "cc-thumbs"
}
```

**Reglas:**
- Debounce 100–200 ms tras estabilización del gesto (no enviar cada frame).
- En reposo, todos los valores = neutral (audio intacto).
- El audio NUNCA viaja por el socket — solo parámetros y estado.

## 9. Demo del hackaton (flujo completo)

1. **Masterizar (offline, una vez):** subir track → presets → `POST /process` → master WAV (~44 s para 3 min, o ~1.5 s con prebuilt).
2. **Abrir Live:** el master entra al Live Engine en loop.
3. **Tocar:** pulgar derecho = filtro, pulgar izquierdo = reverb, altura = delay, apertura = echo, X = drive.
4. **Grabar la salida en vivo** (MediaRecorder / captureStream del AudioContext).
5. **Resultado:** canción masterizada + performance en vivo con efectos, todo desde una pantalla.

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Masterización no es tiempo real (44 s) | Es offline por diseño — el Live Engine solo reproduce el resultado |
| Latencia del socket para el control | El audio es local (navegador); el socket solo lleva parámetros → control perceptiblemente instantáneo con `setTargetAtTime` |
| Jitter del gesto → zipper en los nodos | Reutilizar suavizado + dead zone de `cc_thumbs`; `setTargetAtTime` con time constant ~20 ms |
| Dos manos compitiendo entre "tocar" y "controlar" | Modos dedicados (`--mode studio` = control FX; `--mode piano` = performance) o gesto modificador (puño = modo control) |
| MediaPipe 0.10.14 fijo (wheels Python 3.12+) | No subir versión sin adaptar código |
| Reproducción con latencia del buffer Web Audio | `AudioContext({ latencyHint: "interactive" })` + `AudioWorklet` si hace falta |
