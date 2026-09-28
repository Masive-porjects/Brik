# AGENTS.md — Guía para agentes de código

Este repo es **IA-first**: está diseñado para que agentes (Claude Code, Codex, OpenCode, Hermes, etc.) trabajen sin romper nada. Lee esto completo antes de escribir código.

## Qué es esto

**WaveAI** = mastering IA (Next.js + FastAPI): análisis, mezcla y master. El Live Engine Web Audio se retiró (`ba3b4a6`).

Pipeline: `Audio → AudioMind (FastAPI) → Master / Mix → Studio (UI + Web Audio) → Audio`

## LEER PRIMERO (obligatorio antes de escribir código)

0. `docs/README.md` — índice central de documentación (mapa de qué leer y dónde).
1. `docs/runbooks/SETUP.md` — runbook de entorno verificado (venv, bun, Convex, stack local, pitfalls reales). Síguelo literal si el entorno no está levantado.
2. `docs/reference/specs/08_implementacion_llm.md` — prompt de implementación con TODOS los valores exactos (presets, rangos, tokens, endpoints, fases, criterios de éxito, pitfalls). **No inventes valores DSP ni de diseño: extráelos de los fuentes.**
3. `docs/archive/INTEGRATION_REPORT.md` — estado del bloque de integración.
4. Según el área: `docs/reference/specs/03_*.md` (backend mastering), `04_*.md` (sistema de diseño). `05_live_engine_gestos_a_master.md` es **histórico**: describe el engine retirado.

## Mapa del repo

| Ruta | Stack | Rol |
|---|---|---|
| `apps/studio/` | Next.js 16 + React 19 + TS + Tailwind 4 | Mastering UI + Mezcla (Web Audio) |
| `apps/audiomind/` | Python/FastAPI, librosa, pedalboard | MSP de mastering (análisis + cadena de 13 etapas) + Mix Engine (mezcla IA+DSP) |
| `packages/contracts/` | JSON Schema + generador | `live_params.schema.json` = contrato **dormido** (ver nota) |
| `e2e/` | Playwright | flujo master → mezcla |

> ⚠️ El **Live Engine fue eliminado** (`ba3b4a6`): su tab solo mostraba un "próximamente" y ningún archivo fuera del cluster lo importaba. `apps/bridge/` y `simulator/` también están removidos. Quedan únicamente el schema y sus tipos generados, como contrato dormido: **no los regeneres ni los consumas** salvo que se reactive el engine explícitamente. Ver `docs/ESTADO_PROYECTO.md` §5.

## Reglas NO negociables (de la spec 08 §11–12)

- **`packages/contracts/live_params.schema.json` es la fuente de verdad** del protocolo. Si cambia, regenera tipos con `packages/contracts/scripts/gen_types.sh` (TS → `packages/contracts/liveParams.gen.ts`). Nunca edites los tipos generados a mano. Como el Live Engine está eliminado, este contrato está **dormido**: no lo consumas ni lo regeneres sin una reactivación explícita.
- **Neutral = bypass**: en el backend, parámetro neutral = audio idéntico (bypass bit-exacto). Presérvalo en TODAS las rutas.
- **Todo cambio de parámetro Web Audio con `setTargetAtTime(value, ctx.currentTime, 0.02)` — NUNCA asignación directa** (anti-zipper). Aplica a cualquier nodo Web Audio con parámetros; hoy el único Web Audio en vivo es el análisis estéreo de `useStereoField.ts`, que solo lee.
- **Sesiones del backend en memoria** (dict + `SessionCache`) — se pierden al reiniciar el backend. `ProcessingStatus`: `uploaded → analyzing → processing → completed | error`.
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
