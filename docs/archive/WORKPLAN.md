# WORKPLAN.md — Estado del trabajo (hackathon)

> Fuente de verdad del **estado** de cada área. El *qué hace cada quién* vive en [`PLAN.md`](PLAN.md); las reglas técnicas en [`AGENTS.md`](../../AGENTS.md).
> Regla: se actualiza al cerrar cada tarea, con verificación real (no "está casi"). Commits semánticos + PR a `develop`.
>
> **⚠️ 2026-09-11:** HumanMidi fue **removido del producto** (ya no existe `apps/humanmidi/`, ni `mediapipe` como dependencia). Las entradas de este reporte sobre humanmidi/mediapipe son históricas. Ver `HUMANMIDI_REMOVAL_REPORT.md`.

---

## 0. Baseline del repo (septiembre 2026 — post-cleanup)

| Ítem | Estado | Nota |
|---|---|---|
| `apps/studio` build + typecheck | ✅ OK | `npx tsc --noEmit` + `npm run build` |
| `apps/studio` unit tests | ✅ 6/6 | vitest 2.1.9 + jsdom 24 (nuevo: `npm test`) |
| `apps/studio` lint | ✅ 0 errores | warnings pre-existentes, no bloqueantes |
| `apps/audiomind` pytest | ✅ verde | suite backend de mastering intacta |
| CI | ❌ no existe | la verificación es manual por ahora |

> **Post-cleanup:** el stack de visión/gestos/control en tiempo real fue eliminado del monorepo. El Live Engine es standalone (knobs → Web Audio). La suite de mastering (audiomind) no cambió.

---

## 1. Estado por persona

| Dev | Área (PLAN §4) | Estado | PR / Rama | DoD pendiente |
|---|---|---|---|---|
| **David** | Live Engine (studio/live) | ✅ standalone | post-cleanup | demo: knobs sobre el master real sin cortes |
| **Andrés** | UI/UX (studio components + app) | ⚪ sin datos | — | — |
| **Miguel** | Agente IA (`apps/agent/`, intent_profile) | ⚪ sin datos | rama `miguel` | — |
| **Tomás** | Backend/Convex (`apps/studio/convex/`, deploy) | ⚪ sin datos | rama `feat/backend` | — |
| **Brickman** | Mastering DSP (`apps/audiomind/`, mapper, presets) | ⚪ sin datos | — | — |

> Los que están en ⚪: actualicen su fila al cerrar algo. El camino crítico del hackathon es el vertical slice (login → subir → procesar → descargar), dueños Tomás + Brickman + Andrés.

---

## 2. Detalle área Live (standalone)

| # | Tarea | Estado | Verificación | PR |
|---|---|---|---|---|
| 1 | Fix glitch: grafo no se recrea al cambiar params | ✅ | test de regresión red/green (`useLiveEngine.test.ts`) | — |
| 2 | Grabar + descargar sesión Live | ✅ | UI cableada al hook (antes: callbacks no-op) | — |
| 3 | Conectar master real del flujo de mastering | ✅ | LiveView decodifica `masterAudioUrl` → hook (contrato intacto) | — |
| 4 | Remover stack visión/gestos/control en tiempo real (cleanup) | ✅ | aplicaciones y tooling de entrada real-time eliminados; apps restantes build + tests verdes | — |

### Verificación (post-cleanup)

```bash
cd apps/studio
npx tsc --noEmit          # OK
npm test                  # vitest
npx eslint src/lib/live/  # 0 errores
npm run build             # OK
```

### Pendientes del área live

- [ ] DoD manual: subir track → masterizar → Live → girar knobs 10 s sin cortes de audio (verificación en demo)
- [ ] e2e `master_to_live.spec.ts` contra el flujo real (requiere backend + fixture)

---

## 3. Decisiones del equipo

| Decisión | Estado |
|---|---|
| Flujo de trabajo | ✅ **Ramas `feat/*` desde `develop` + PR a `develop`** (PLAN §7). `main` solo recibe merges de develop. |
| Contratos (Hito 0) | `live_params.schema.json` ✅ · `mastering_settings` ⬜ Brickman · `intent_profile` ⬜ Miguel · `project_state` ⬜ Tomás |
| CI/CD | ❌ pendiente: Playwright job en GitHub Actions (next step del INTEGRATION_REPORT) |
| Stack visión/gestos/control en tiempo real | ✅ **removido** (post-cleanup): aplicaciones y tooling de entrada real-time eliminados; Live Engine standalone con knobs |
