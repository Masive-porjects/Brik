# SETUP.md — Runbook local (IA-first, verificado 2026-08-29)

> Instrucciones para levantar el entorno **completo** en una máquina nueva.
> Cualquier agente de IA puede seguir esto literalmente: comandos exactos, output esperado, pitfalls reales.
> Stack: Studio (Next.js :3000) · AudioMind (FastAPI :8000). El Live Engine fue eliminado (`ba3b4a6`); el contrato live_params queda dormido. Convex fue eliminado por completo (ver sección 3).

---

## 0. Requisitos

| Requisito | Versión | Por qué |
|---|---|---|
| Python | **3.12** (NO 3.14) | el proyecto declara 3.12 en los pyproject de los apps Python |
| bun | ≥ 1.3 | el equipo usa **bun** (`bun.lock`); NO usar npm (package-lock fue eliminado) |
| Node | 18+ | Studio |

---

## 1. Clonar e instalar dependencias

```bash
git clone <repo> && cd <repo>
bun install          # workspaces: apps/* (studio, agent) + packages/contracts
```

**Esperado:** sin errores. `node_modules/@midimastering/agent` debe existir como symlink al workspace.

---

## 2. Entorno Python (venv del repo)

```bash
python3.12 -m venv .venv

# AudioMind va editable (src-layout): expone `audiomind.main:app` y sus deps
# (uvicorn, fastapi, librosa, pedalboard...) al venv compartido.
./.venv/bin/pip install -e apps/audiomind
```

**Esperado:** `uvicorn --version` sin errores.

En Windows el venv queda en `.venv\Scripts\` (no `.venv/bin`):
`py -3.12 -m venv .venv` y `.\.venv\Scripts\pip install ...`.

---

## 3. Convex — ELIMINADO (nada que levantar)

El scaffold `convex/` fue removido del repo (verificado 2026-10-13: `git ls-files | rg -i convex` → vacío; sin deps en `apps/studio/package.json`; 0 referencias en `apps/studio/src`). **No se necesita `convex login` ni `convex dev`**: el studio no consulta Convex. El flujo histórico queda en el historial de git.

---

## 4. Workspace `@midimastering/agent` (Miguel)

El paquete apunta a `dist/` — requiere build antes de que el studio lo resuelva:

```bash
cd apps/agent && bun run build && cd ../..
```

**Esperado:** `apps/agent/dist/index.d.ts` existe (nota: `@google/genai` puede faltar si el lock no está al día — es dep de Miguel; el build emite igual).

---

## 5. Levantar el stack (2 terminales)

```bash
# T1 — AudioMind (DSP)
cd apps/audiomind && ../../.venv/bin/uvicorn audiomind.main:app --port 8000

# T2 — Studio
cd apps/studio && bun run dev                           # http://localhost:3000
```

---

## 6. Verificación (corre esto antes de declarar algo terminado)

```bash
# Studio
cd apps/studio
bun run lint            # 0 errores / 33 warnings (no funcionales)
bun run test            # 8 archivos / 72 tests passing
bun run build           # OK (Next 16.2.11)

# Python
cd apps/audiomind && ../../.venv/bin/python -m pytest tests/ -q      # 887 passed, 0 failed
```

---

## 7. Pitfalls verificados (no los vuelvas a descubrir)

| # | Pitfall | Detalle |
|---|---|---|
| 1 | npm vs bun | el equipo migró a bun. `npm install` regenera package-lock y ensucia el repo. Usar `bun install` |
| 2 | `@midimastering/agent` | apunta a `dist/` — sin `bun run build` previo, el studio no lo resuelve (TS2307) |
| 3 | contrato live_params | **dormido** (Live Engine eliminado en `ba3b4a6`): no consumirlo ni regenerarlo. Fuente de verdad histórica: `packages/contracts/live_params.schema.json` |

---

## 8. Estado conocido del repo (verificado 2026-10-13)

- ✅ audiomind **887 passed, 0 failed** · studio vitest **8 archivos / 72 tests** · eslint **0 errores / 33 warnings** (no funcionales) · build OK (Next 16.2.11)
- ✅ HumanMidi **removido** (2026-09-11) — ver `../archive/HUMANMIDI_REMOVAL_REPORT.md`; bridge y simulator **removidos**; Live Engine eliminado (`ba3b4a6`); contrato `live_params` **dormido** — ver `../ESTADO_PROYECTO.md` §5
- ✅ Convex **eliminado** — sin scaffold, sin deps, sin referencias en el studio
- ✅ **CI activa**: `.github/workflows/studio-ci.yml` (bun) — lint + build bloqueantes; ver `../ESTADO_PROYECTO.md` §6.2
- ✅ i18n real: hook `useTranslation()` + `apps/studio/src/i18n/locales/{es,en}.json` (765 claves hoja, paridad)
