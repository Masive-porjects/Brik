# SETUP.md — Runbook local (IA-first, verificado 2026-08-29)

> Instrucciones para levantar el entorno **completo** en una máquina nueva.
> Cualquier agente de IA puede seguir esto literalmente: comandos exactos, output esperado, pitfalls reales.
> Stack: Studio (Next.js :3000) · AudioMind (FastAPI :8000) · Convex (cloud). El Live Engine es standalone (Web Audio, sin WS ni MIDI — bridge y simulator fueron removidos).

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

## 3. Convex (único servicio cloud — los datos se aislan por dev)

```bash
cd apps/studio
npx convex login        # flujo device: te da URL + código (5 min); autoriza en el navegador
npx convex dev          # elige "choose an existing project" (o créalo) → pushea schema, genera:
                        #   convex/_generated/   (NO se commitea — ver .gitignore)
                        #   .env.local           (NEXT_PUBLIC_CONVEX_URL — NO se commitea)
                        # queda corriendo como watcher (déjalo en una terminal aparte)
```

**Esperado:** `✔ Convex functions ready!` y `convex/_generated/api.d.ts` + `server.d.ts` existentes.

Si `_generated/api.d.ts` quedó incompleto (faltan internal functions):
```bash
npx convex codegen      # regenera los bindings
```

**Para el resto del equipo:** el dueño del proyecto los invita en dashboard.convex.dev → Settings → Members. Cada dev hace su propio login + `convex dev` (su dev deployment es aislado; el schema es compartido).

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
npx tsc --noEmit        # ⚠️ errores residuales en convex/mastering.ts (ciclo de tipos) — NO son tuyos
npx vitest run          # 57/57 passing
npm run build           # OK

# Python
cd apps/audiomind && ../../.venv/bin/python -m pytest tests/ -q      # 628/628 passing
```

---

## 7. Pitfalls verificados (no los vuelvas a descubrir)

| # | Pitfall | Detalle |
|---|---|---|
| 1 | npm vs bun | el equipo migró a bun. `npm install` regenera package-lock y ensucia el repo. Usar `bun install` |
| 2 | `convex/_generated/` | NO se commitea (`.gitignore` de apps/studio). Se regenera con `npx convex dev` |
| 3 | `.env.local` | NO se commitea. `convex dev` lo genera con la URL del deployment propio |
| 4 | `@midimastering/agent` | apunta a `dist/` — sin `bun run build` previo, el studio no lo resuelve (TS2307) |
| 5 | typecheck global | los 3 errores de `convex/mastering.ts` son de Tomás (ciclo `api.d.ts` ↔ `mastering.ts`). No tocarlos sin avisarle |
| 6 | contrato live_params | `packages/contracts/live_params.schema.json` es la fuente de verdad. Si cambia: `packages/contracts/scripts/gen_types.sh` (regenera TS + Python). Nunca editar tipos generados a mano |

---

## 8. Estado conocido del repo (2026-08-29; verificado 2026-09-23)

- ✅ audiomind 628 tests · studio tsc (salvo mastering.ts) + 57 vitest + build · contrato live_params congelado
- ✅ HumanMidi **removido del producto** (2026-09-11) — ver `../archive/HUMANMIDI_REMOVAL_REPORT.md`; bridge y simulator **removidos** también — ver `../ESTADO_PROYECTO.md` §5 (el Live Engine es standalone)
- ⚠️ Convex: deployment de David `proper-scorpion-625` (WaveIA) — el del equipo llega cuando Tomás comparta el suyo
- ⚠️ CI inexistente — la verificación es manual (sección 6)
