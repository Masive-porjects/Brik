# WaveAI × midiMastering — Integration Report

> **Branch:** `test/integration-midimastering`  
> **Date:** 2026-08-25  
> **Status:** ✅ Complete — All blocks delivered, build passing, 7 semantic commits ready for PR
> **Update 2026-09-11:** **HumanMidi fue removido del producto** (baja definitiva). Ver `HUMANMIDI_REMOVAL_REPORT.md`. Este reporte conserva la estructura histórica con la sección Block B marcada como removed.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Monorepo Structure](#monorepo-structure)
3. [Blocks Summary](#blocks-summary)
4. [Shared Contract (LiveParams)](#shared-contract-liveparams)
5. [Block A — Contracts & Monorepo](#block-a--contracts--monorepo)
6. [Block B — HumanMidi (removed)](#block-b--humanmidi-removed)
7. [Block C — Bridge](#block-c--bridge)
8. [Block D — Live Engine & UI](#block-d--live-engine--ui)
9. [Block E — Simulator & E2E](#block-e--simulator--e2e)
10. [Git History](#git-history)
11. [How to Run](#how-to-run)
12. [Next Steps](#next-steps)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     WaveAI Ecosystem                         │
├──────────┬──────────┬──────────┬──────────────────────────────┤
│  bridge  │  studio  │audiomind │        simulator             │
│ (Python) │ (Next.js)│ (Python) │        (Python)              │
├──────────┴────┬─────┴──────────┴─────────────────────────────┤
│  WS :8765     │        Web Audio Graph                        │
│  Protocol     │  Filter→Drive→Delay→Reverb→Master             │
└───────────────┴──────────────────────────────────────────────┘

Pipeline: MIDI Source → Bridge → WS → Studio → Audio
```

### Data Flow

```
[MIDI Source] ──CC/Note──→ [Bridge] ──WebSocket──→ [Studio Live Engine]
                            (smoother)               (Web Audio API)
                                                        ↓
                                                   [UI Knobs]
                                                   [Meters]
                                                   [FxSlotPanel]
                                                   [Recorder]
```

---

## Monorepo Structure

```
WaveAI/
├── packages/
│   └── contracts/                 # Shared schema + type generators
│       ├── live_params.schema.json  # Source of truth (JSON Schema)
│       ├── liveParams.gen.ts        # Generated TypeScript types
│       └── scripts/
│           ├── gen_types.py         # Python type generator
│           └── gen_types.sh         # Shell wrapper
│
├── apps/
│   ├── audiomind/                 # DSP backend (Python/FastAPI)
│   │   ├── src/audiomind/
│   │   │   ├── api/               # mastering.py (GET/POST endpoints)
│   │   │   ├── analysis/          # audio analyzer
│   │   │   └── intelligence/      # genre knowledge base
│   │   ├── tests/                 # pytest suite
│   │   └── Dockerfile
│   │
│   ├── bridge/                    # MIDI → WebSocket (Python)
│   │   ├── src/
│   │   │   ├── midi_listener.py
│   │   │   ├── gesture_to_params.py
│   │   │   ├── smoother.py        # EMA + dead zone + rate limiting
│   │   │   ├── ws_server.py       # WebSocket server
│   │   │   └── latency.py         # RTT tracker
│   │   ├── live_params.py         # Generated from schema
│   │   ├── tests/                 # 53/53 passing
│   │   └── pyproject.toml
│   │
│   └── studio/                    # Next.js 16 + Turbopack
│       ├── src/
│       │   ├── lib/live/          # Live Engine core
│       │   │   ├── audioGraph.ts   # Web Audio node chain
│       │   │   ├── liveSocket.ts   # WS client + auto-reconnect
│       │   │   ├── useLiveEngine.ts# Orchestrator hook
│       │   │   ├── fxPresets.ts    # preset definitions
│       │   │   ├── recorder.ts     # MediaRecorder + MIME detection
│       │   │   └── liveParams.gen.ts # Generated types
│       │   ├── components/live/    # Live UI components
│       │   │   ├── LiveView.tsx     # 3-column layout
│       │   │   ├── FxSlotPanel.tsx  # 4 knobs + preset selector
│       │   │   ├── Knob3D.tsx       # 3D rotary knob
│       │   │   ├── LiveMeters.tsx   # VU/Peak meters
│       │   │   └── LiveRecorderBar.tsx # Record controls
│       │   └── components/dock/   # Dock navigation
│       │       ├── ModuleDock.tsx
│       │       └── types.ts       # MasteringTab includes "live"
│       ├── tests/                 # Vitest suite
│       └── package.json
│
├── simulator/                     # Mock Bridge for E2E
│   ├── main.py                    # CLI entry point
│   ├── mock_bridge.py             # WS server (replicates Bridge protocol)
│   ├── scenarios.py               # 5 deterministic scenarios
│   ├── midi_injector.py           # Optional: rtmidi → virtual port
│   └── requirements.txt
│
├── e2e/                           # Playwright E2E tests
│   ├── playwright.config.ts       # Chromium + headless flags
│   ├── fixtures/
│   │   └── generate_fixture.py    # WAV audio generator
│   ├── helpers/
│   │   └── simulator.py           # Mock Bridge lifecycle helper
│   └── tests/
│       ├── master_to_live.spec.ts # Upload → master → live flow
│       ├── live_params.spec.ts    # Sweep + presets + random walk
│       └── live_reconnect.spec.ts # Reconnection + chaos
│
├── frontend/                      # Legacy (moved to apps/studio)
├── backend/                       # Legacy (moved to apps/audiomind)
├── package.json                   # Root workspace config
└── .gitignore
```

---

## Blocks Summary

| Block | Description | Status | Tests |
|-------|-------------|--------|-------|
| **A** | Contracts + Monorepo restructure | ✅ Done | Schema valid |
| **B** | HumanMidi (Vision → MIDI) | ❌ Removed (2026-09-11) | — |
| **C** | Bridge (MIDI → WebSocket) | ✅ Done | 53/53 passing |
| **D** | Live Engine + UI hardening | ✅ Done | Build passing |
| **E** | Simulator + E2E | ✅ Done | 3 specs ready |

---

## Shared Contract (LiveParams)

### Source of Truth

`packages/contracts/live_params.schema.json`

### Generated Types

| Language | Output Path | Generator |
|----------|-------------|-----------|
| TypeScript | `apps/studio/src/lib/live/liveParams.gen.ts` | `packages/contracts/scripts/gen_types.py` |
| Python | `apps/bridge/live_params.py` | `packages/contracts/scripts/gen_types.py` |

### CC Mapping (MIDI → Parameters)

| CC / Note | Parameter | Range | Curve |
|-----------|-----------|-------|-------|
| CC74 | `filter_cutoff` | 200–12000 Hz | Logarithmic |
| CC92 | `reverb_mix` | 0–1 | Linear |
| CC71 | `delay_time` | 50–800 ms | Linear |
| CC73 | `echo_feedback` | 0–0.8 | Linear |
| CC16 | `drive` | 0–1 | Linear |
| Note 36 | `fx_preset` → "clean" | — | — |
| Note 38 | `fx_preset` → "dub" | — | — |
| Note 42 | `fx_preset` → "big_room" | — | — |
| Note 49 | `fx_preset` → "radio" | — | — |

### WS Protocol

```
→ Client connects
← {"type":"hello","data":{"version":"1.0.0","midi_port":"...","gesture_mode":"studio","client_id":"...","server_time":...}}

→ {"type":"PARAM_UPDATE","timestamp":...,"params":{...}}
→ {"type":"PING","t":...}
← {"type":"PONG","t":...,"server_t":...}

→ {"type":"state","data":{"filter_cutoff":4500,...}}  // client echo
```

---

## Block A — Contracts & Monorepo

### What was done

- Created `packages/contracts/` with JSON Schema and type generators
- Set up root `package.json` with npm workspaces
- Generated TypeScript types for Studio
- Generated Python types for Bridge

### Key files

- `packages/contracts/live_params.schema.json` — Source of truth
- `packages/contracts/scripts/gen_types.py` — Dual-language generator
- `packages/contracts/liveParams.gen.ts` — Generated TS types
- `packages/apps/bridge/live_params.py` — Generated Python types

---

## Block B — HumanMidi (removed)

> **❌ Removido del producto el 2026-09-11.** HumanMidi (visión por cámara, MediaPipe, hand tracking, gestos → MIDI) dejó de pertenecer a WaveAI. El directorio `apps/humanmidi/`, sus tests, configs y dependencias (`mediapipe`, `cv2` legacy) fueron eliminados; `CameraOverlay` y `GestureBadge` salieron del Live Engine; todos los scripts de arranque/verificación fueron limpiados. Detalle completo: `HUMANMIDI_REMOVAL_REPORT.md`.

### Lo que era (histórico)

- Hand tracking with MediaPipe (camera_handler + hand_detector)
- Gesture engine with configurable gesture classes
- Studio gesture: exact CC mapping matching Bridge expectations
- MIDI sender for virtual port output
- Full config system (config.yaml + defaults.py + settings.py)

### Test results (históricos): 49/49 passing

### Key files (históricos, eliminados)

| File | Purpose |
|------|---------|
| `src/core/camera_handler.py` | Camera feed management |
| `src/core/hand_detector.py` | MediaPipe hand detection |
| `src/core/midi_sender.py` | MIDI CC output |
| `src/gestures/studio_gesture.py` | CC mapping (CC74→filter, CC92→reverb, etc.) |
| `src/gestures/cc_controller.py` | CC value management |
| `src/main.py` | Application entry point |
| `run.py` | CLI runner |
| `config/config.yaml` | Runtime configuration |

---

## Block C — Bridge

### What was done

- WebSocket server on port 8765
- MIDI listener (rtmidi-based)
- Gesture → LiveParams conversion
- Smoother: EMA filter + dead zone + rate limiting
- Latency tracker (RTT via PING/PONG)
- Pydantic validation against LiveParams schema

### Test results: 53/53 passing

### Key files

| File | Purpose |
|------|---------|
| `src/ws_server.py` | WebSocket server (Bridge → Studio) |
| `src/midi_listener.py` | MIDI CC input listener |
| `src/gesture_to_params.py` | MIDI CC → LiveParams mapping |
| `src/smoother.py` | EMA + dead zone + throttle |
| `src/latency.py` | RTT measurement |
| `live_params.py` | Generated Pydantic model |
| `tests/test_*.py` | 5 test files, 53 tests total |

---

## Block D — Live Engine & UI

### What was done

- Web Audio graph: `Source → Filter → Drive → Delay → Reverb → Master → Analyser`
- WebSocket client with auto-reconnect and ping/pong
- FX presets (clean, dub, big_room, radio)
- MediaRecorder with MIME detection
- useLiveEngine orchestrator hook
- Complete UI: LiveView, FxSlotPanel, Knob3D, LiveMeters, LiveRecorderBar
- Dock tab "live" integration

### Hardening fixes applied

| Component | Fix |
|-----------|-----|
| useLiveEngine.ts | Date.now() lazy init in useState |
| recorder.ts | Auto MIME detection + MediaRecorderErrorEvent typed |
| Knob3D.tsx | `as any` removed (React.TouchEvent typed) |
| FxSlotPanel.tsx | `as any` removed (parameter typed) |
| audioGraph.ts | `any` → ValidPreset type guard |
| liveSocket.ts | HelloData includes client_id + server_time |

### Build status: ✅ Passing

### Lint status

Pre-existing warnings (not from integration):
- DropZone.tsx: missing useCallback dependency
- MobileDrawer.tsx: unused imports
- StereoField.tsx: unused variables
- Knob3D.tsx: unused variable
- LiveMeters.tsx: unused import

---

## Block E — Simulator & E2E

### Simulator

CLI tool that mocks the Bridge WS server for E2E testing.

```bash
# Run simulator
python -m simulator.main --mode server --scenario sweep --port 8765

# Available scenarios
--scenario sweep          # Deterministic parameter sweep (step-mode)
--scenario presets        # Note-triggered preset changes
--scenario random_walk    # Bounded random walk (fixed seed)
--scenario idle           # Hello + PING/PONG only
--scenario chaos          # Intentionally invalid payloads
```

### E2E Tests (Playwright)

| Spec | What it tests |
|------|---------------|
| `master_to_live.spec.ts` | Upload audio → master → switch to live tab |
| `live_params.spec.ts` | Sweep step values + presets + random walk validation |
| `live_reconnect.spec.ts` | WS reconnection + chaos resilience |

### Chromium flags (non-negotiable)

```
--autoplay-policy=no-user-gesture-required
--use-fake-ui-for-media-stream
--use-fake-device-for-media-stream
--mute-audio
```

### How to run E2E

```bash
# Generate audio fixture (once)
python e2e/fixtures/generate_fixture.py

# Run all E2E tests
cd apps/studio && npx playwright test --config=../../e2e/playwright.config.ts

# Run with UI
npx playwright test --config=../../e2e/playwright.config.ts --ui
```

---

## Git History

```
df477be test(e2e): playwright test suite, audio fixtures and helpers
3299d20 test(simulator): mock ws bridge server and deterministic scenarios
06f5f83 feat(studio): live engine, web audio graph, knobs and dock integration
74b937c feat(bridge): realtime midi listener, smoother and ws server
ad69a59 feat(humanmidi): vision tracker, gesture engine and studio midi mapper
78b02bf feat(audiomind): dsp backend integration and session endpoints
f3b6311 feat(contracts): schema, generators and monorepo root setup
```

### Commit breakdown

| # | Hash | Message | Files | Lines |
|---|------|---------|-------|-------|
| 1 | `f3b6311` | feat(contracts): schema, generators and monorepo root setup | 7 | +7,323 |
| 2 | `78b02bf` | feat(audiomind): dsp backend integration and session endpoints | ~50 | ~5,000 |
| 3 | `ad69a59` | feat(humanmidi): vision tracker, gesture engine and studio midi mapper *(removed 2026-09-11)* | 49 | ~4,000 |
| 4 | `74b937c` | feat(bridge): realtime midi listener, smoother and ws server | 18 | +2,222 |
| 5 | `06f5f83` | feat(studio): live engine, web audio graph, knobs and dock integration | 88 | +16,274 |
| 6 | `3299d20` | test(simulator): mock ws bridge server and deterministic scenarios | 6 | +1,127 |
| 7 | `df477be` | test(e2e): playwright test suite, audio fixtures and helpers | 10 | +568 |
| | | **Total** | **~228** | **~36,514** |

---

## How to Run

### Prerequisites

- Node.js 18+ (Studio)
- Python 3.10+ (Bridge, Simulator)
- npm (monorepo workspaces)

### Studio (Frontend)

```bash
cd apps/studio
npm install
npm run dev        # Development server
npm run build      # Production build
```

### HumanMidi (removed)

> ❌ Eliminado el 2026-09-11. Ya no existe `apps/humanmidi/`. El Live Engine se controla con el Simulator (`python -m simulator.main`) o cualquier fuente MIDI externa vía Bridge.

### Bridge

```bash
cd apps/bridge
pip install -e ".[dev]"
python -m bridge   # Starts WS server on :8765
```

### Simulator (Mock Bridge)

```bash
cd simulator
pip install -r requirements.txt
python -m simulator.main --mode server --scenario sweep --port 8765
```

### E2E Tests

```bash
cd apps/studio
npx playwright install chromium
cd ../..
python e2e/fixtures/generate_fixture.py
cd apps/studio
npx playwright test --config=../../e2e/playwright.config.ts
```

---

## Next Steps

1. **Open PR** from `test/integration-midimastering` → `develop`
2. **Add `data-testid`** to 11 UI components for E2E stability
3. **Run E2E suite** against local Studio dev server
4. **CI/CD**: Add Playwright job to GitHub Actions with `webServer` config
5. **Hardware validation**: Test with real MIDI controller
6. **Performance**: Profile WS latency end-to-end (target: <20ms)

---

*Generated by WaveAI integration pipeline — 2026-08-25*
