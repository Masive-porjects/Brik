# AGENTS.md — Guía para agentes de código

Este repo es **IA-first**: está diseñado para que agentes (Claude Code, Codex, OpenCode, Hermes, etc.) trabajen sin romper nada. Lee esto completo antes de escribir código.

## Qué es esto

**WaveAI** = mastering IA (Next.js + FastAPI) + un **Live Engine** Web Audio controlado en tiempo real.

Pipeline: `Audio → AudioMind (FastAPI) → Master → Studio Live Engine (Web Audio) → Knobs/Meters/Audio`

## LEER PRIMERO (obligatorio antes de escribir código)

0. `docs/README.md` — índice central de documentación (mapa de qué leer y dónde).
1. `docs/runbooks/SETUP.md` — runbook de entorno verificado (venv, bun, Convex, stack local, pitfalls reales). Síguelo literal si el entorno no está levantado.
2. `docs/reference/specs/08_implementacion_llm.md` — prompt de implementación con TODOS los valores exactos (presets, rangos, tokens, endpoints, fases, criterios de éxito, pitfalls). **No inventes valores DSP ni de diseño: extráelos de los fuentes.**
3. `docs/archive/INTEGRATION_REPORT.md` — estado del bloque de integración.
4. Según el área: `docs/reference/specs/03_*.md` (backend mastering), `04_*.md` (sistema de diseño), `05_*.md` (live engine).

## Mapa del repo

| Ruta | Stack | Rol |
|---|---|---|
| `apps/studio/` | Next.js 16 + React 19 + TS + Tailwind 4 | Mastering UI + pestaña Live (Web Audio) |
| `apps/audiomind/` | Python/FastAPI, librosa, pedalboard | MSP de mastering (análisis + cadena de 13 etapas) + Mix Engine (mezcla IA+DSP) |
| `packages/contracts/` | JSON Schema + generador | `live_params.schema.json` = fuente de verdad |
| `e2e/` | Playwright | master → live |

> ⚠️ `apps/bridge/` y `simulator/` fueron **removidos** — el Live Engine es standalone (knobs del navegador, sin WebSocket ni MIDI). Ver `docs/ESTADO_PROYECTO.md` §5.

## Reglas NO negociables (de la spec 08 §11–12)

- **`packages/contracts/live_params.schema.json` es la fuente de verdad** del protocolo. Si cambia, regenera tipos con `packages/contracts/scripts/gen_types.sh` (TS → `studio/src/lib/live/liveParams.gen.ts`, Python → bridge). Nunca edites los tipos generados a mano.
- **Neutral = bypass**: en el backend, parámetro neutral = audio idéntico (bypass bit-exacto); en el Live Engine, defaults del schema = master idéntico al original. Presérvalo en TODAS las rutas.
- **El audio NUNCA viaja por WebSocket** — el Live Engine es **standalone**: los knobs de la UI generan `LiveParams` directamente (sin socket ni MIDI; bridge y simulator removidos). Mensajes completos, no deltas; el último estado gana.
- **Todo cambio de parámetro Web Audio con `setTargetAtTime(value, ctx.currentTime, 0.02)` — NUNCA asignación directa** (anti-zipper).
- **Escalado logarítmico del filtro**: `filter_cutoff = 200 * (12000/200)^(v/127)` (200 Hz–12 kHz ≈ 6 octavas; lineal produce saltos).
- **Sesiones del backend en memoria** (dict + `SessionCache`) — se pierden al reiniciar el backend. `ProcessingStatus`: `uploaded → analyzing → processing → completed | error`.
- **Los knobs del Live Engine NO son `MasteringParameters`** — no reprocesar el track; son nodos Web Audio.
- **El limiter es 8× oversampling** (si tocas MasteringGuide escribe 8×, no 4×).
- **Microcopy y Multiidioma Obligatorio (i18n)**:
  - **Toda nueva integración, componente o pantalla DEBE integrarse con el sistema multiidioma** usando el hook `useTranslation()`.
  - Los textos se deben registrar simultáneamente en `apps/studio/src/i18n/locales/es.json` y `en.json`.
  - **Prohibido el texto "hardcodeado"** en código TSX/JSX y **prohibido el spanglish** (consistencia absoluta: español latino neutro sin voseo en `es.json` e inglés nativo en `en.json`).
  - Ejemplo microcopy: "Carga tu audio", "Ajusta", "Prueba de nuevo", "Elige", "Toca" (sin voseo tipo "Cargá").
- **Estética y Sistema de Diseño WaveIA (Obligatorio en Nuevas Integraciones)**:
  - **Fidelidad al Design System**: Utilizar siempre los tokens de color y superficies del tema oscuro (`var(--bg-base)`, `var(--surface-elevated)`, `var(--bg-glass-elevated)`, `var(--accent-primary)`, `var(--border-subtle)`, `var(--text-primary)`, `var(--text-secondary)`). Prohibido usar colores planos genéricos fuera de la paleta.
  - **Identidad de Marca**: Preservar y aplicar los elementos distintivos de WaveIA (mascota fantasma `BigGhostWithNotes`, `FloatingGhosts`, notas musicales flotantes, gradientes de luz y cristales con `backdrop-blur-2xl`).
  - **Ergonomía y Cero Scroll Innecesario**: Vistas modales, accesos (`/login`, `/register`) y tarjetas compactas deben caber de forma limpia en el viewport (`100vh`) sin barras de scroll verticales forzadas.
  - **Micro-interacciones y Animaciones**: Uso de `framer-motion` para transiciones de estado, micro-indicadores interactivos en tiempo real y retroalimentación visual en hover/focus/loading.
- **Neutral = bypass**: los knobs devueltos a sus defaults del schema = master idéntico al original (sin socket ni heartbeat — estado standalone).
- **SOLID**: SRP por módulo, Strategy para slots FX, DIP hacia los contratos.

## Comandos de verificación (corre esto antes de declarar algo terminado)

```bash
# Backend
cd apps/audiomind && pytest tests/ -q
uvicorn audiomind.main:app --port 8000   # → curl localhost:8000/health

# Studio
cd apps/studio && npm run build && npm run lint
npm run dev                               # http://localhost:3000

# Integral
npm run e2e                               # desde apps/studio
```

## Convenciones

- Commits semánticos (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- Tests junto al código; no rompas la suite existente.
- Backend: pyproject con ruff + mypy strict (`apps/audiomind/pyproject.toml`).
- Los WAV/MP3 de prueba van a `uploads/`/`outputs/` (gitignored) o se generan con `apps/audiomind/scripts/generate_samples.py` y `e2e/fixtures/generate_fixture.py`.
