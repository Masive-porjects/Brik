# Índice Central de Documentación — WaveAI

Este documento es la **fuente única de verdad** sobre la estructura documental de **WaveAI**: qué documento existe, dónde está ubicado, cuál es su propósito y la convención de nomenclatura estándar del proyecto (`MAYUSCULAS_MAYUSCULAS.md`).

```text
Audio → AudioMind (FastAPI DSP) → Master → Studio Live Engine (Web Audio) → Knobs/Meters/Audio
```

---

## 🗂️ Estructura y Propósito de Carpetas en `docs/`

| Directorio | Propósito Principal | Convención de Archivos |
|---|---|---|
| **`docs/` (Raíz)** | Documentos globales de estado del proyecto, hoja de ruta técnica e índice canónico. | `ESTADO_PROYECTO.md`, `IMPLEMENTATION_PLAN.md`, `README.md` |
| **`docs/evidence/`** | Mediciones empíricas, auditorías de RAM/CPU, benchmarks de audio y **reportes formales de fase** en `reports/`. | `DEMO_*.md`, `evidence/reports/REPORT_FASE_X.md` |
| **`docs/reference/`** | Especificaciones canónicas del producto, contratos de DSP, sistema de diseño y specs técnicas (`specs/`). | `COMPLIANCE_*.md`, `DESIGN.md`, `DSP_*.md` |
| **`docs/runbooks/`** | Guías operativas paso a paso para levantar entornos de desarrollo local, contenedores y despliegues. | `SETUP.md`, `DOCKER.md`, `DEPLOY_RUNBOOK.md`, `DEMO_*.md` |
| **`docs/manual/`** | Documentación de producto orientada al usuario final y mapas de experiencia y navegación. | `USER_MANUAL.md`, `UX_MAP.md` |
| **`docs/presentation/`** | Materiales de presentación comercial, activos de marca y plantillas visuales. | `propuesta-waveAi.html`, `waveai-logo.jpg` |
| **`docs/archive/`** | Archivo histórico inmutable de decisiones previas (remoción de HumanMidi, desacople de Convex). | `INTEGRATION_REPORT.md`, `PLAN.md`, etc. |

> [!NOTE]
> Las **reglas normativas de comportamiento para agentes de IA** (como commits obligatorios por tarea, estándares de multiidioma, cursor pointer y arquitectura limpia) se administran en la raíz nativa de reglas del sistema:
> - [`.agents/rules/ui-and-i18n-guidelines.md`](file:///c:/Users/Maria%20Angelica%20Diaz/Desktop/trabajo/brikmanproject/WaveIA/.agents/rules/ui-and-i18n-guidelines.md)
> - [`.agents/rules/architecture-and-code-guidelines.md`](file:///c:/Users/Maria%20Angelica%20Diaz/Desktop/trabajo/brikmanproject/WaveIA/.agents/rules/architecture-and-code-guidelines.md)
> - [`.agents/rules/audio-and-dsp-guidelines.md`](file:///c:/Users/Maria%20Angelica%20Diaz/Desktop/trabajo/brikmanproject/WaveIA/.agents/rules/audio-and-dsp-guidelines.md)
> - [`.agents/rules/git-and-workflow-guidelines.md`](file:///c:/Users/Maria%20Angelica%20Diaz/Desktop/trabajo/brikmanproject/WaveIA/.agents/rules/git-and-workflow-guidelines.md)
> - [`AGENTS.md`](file:///c:/Users/Maria%20Angelica%20Diaz/Desktop/trabajo/brikmanproject/WaveIA/AGENTS.md)

---

## 📑 Índice Detallado de Documentos

### 1. Documentos Centrales (`docs/`)
- [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md): Relevamiento exhaustivo del estado actual del sistema (motores DSP, frontend, auth, suites y ramas).
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md): Plan maestro de implementación paso a paso por fases (Fases 0 a 7), política de ramas y control de entregables.
- [`README.md`](README.md): Este índice central unificado.

---

### 2. Evidencias y Reportes de Fase (`docs/evidence/`)
- **Reportes Formales de Fase (`docs/evidence/reports/`)**:
  - [`reports/REPORT_FASE_0.md`](evidence/reports/REPORT_FASE_0.md): Cierre Fase 0 — Erradicación de Convex y gobierno técnico inicial.
  - [`reports/REPORT_FASE_1.md`](evidence/reports/REPORT_FASE_1.md): Cierre Fase 1 — Arquitectura limpia por features y modularidad.
  - [`reports/REPORT_FASE_2.md`](evidence/reports/REPORT_FASE_2.md): Cierre Fase 2 — Navegación desacoplada y Composition Root.
  - [`reports/REPORT_FASE_3.md`](evidence/reports/REPORT_FASE_3.md): Cierre Fase 3 — Sistema multiidioma i18n extensible (ES/EN).
  - [`reports/REPORT_FASE_4.md`](evidence/reports/REPORT_FASE_4.md): Cierre Fase 4 — Autenticación con Supabase Auth y control de roles (RBAC).
  - [`reports/REPORT_FASE_5.md`](evidence/reports/REPORT_FASE_5.md): Cierre Fase 5 — Persistencia 1:N, drafts no destructivos y consolidación de masters.
- **Mediciones y Auditorías**:
  - [`DEMO_RESOURCE_AUDIT.md`](evidence/DEMO_RESOURCE_AUDIT.md): Auditoría de consumo de RAM, tiempos de respuesta y límites técnicos.
  - [`DEMO_LOCAL_VALIDATION.md`](evidence/DEMO_LOCAL_VALIDATION.md): Validación local de métricas y latencia de audio.
  - [`DEMO_FEASIBILITY.md`](evidence/DEMO_FEASIBILITY.md): Factibilidad técnica y análisis de dependencias.

---

### 3. Especificaciones y Referencias Canónicas (`docs/reference/`)
- [`COMPLIANCE_PHASE1.md`](reference/COMPLIANCE_PHASE1.md): Contrato técnico de entrega (Modo Transparente, bypass bit-exacto, platform targets).
- [`DSP_INDUSTRY_REVIEW.md`](reference/DSP_INDUSTRY_REVIEW.md): Revisión de la cadena de mastering contra estándares profesionales de la industria.
- [`DESIGN.md`](reference/DESIGN.md): Especificación del UI del Studio: layout, responsive, componentes y microcopy.
- [`specs/08_implementacion_llm.md`](reference/specs/08_implementacion_llm.md): Valores exactos de DSP, presets, rangos, tokens y endpoints.
- [`specs/03_waveai_backend_mastering.md`](reference/specs/03_waveai_backend_mastering.md): Arquitectura de la cadena DSP en FastAPI.
- [`specs/04_waveai_sistema_diseno.md`](reference/specs/04_waveai_sistema_diseno.md): Sistema de diseño, paleta analógica y tokens CSS.
- [`specs/05_live_engine_gestos_a_master.md`](reference/specs/05_live_engine_gestos_a_master.md): Motor de audio Web Audio API en tiempo real.

---

### 4. Guías Operativas (`docs/runbooks/`)
- [`SETUP.md`](runbooks/SETUP.md): Puesta en marcha del entorno local (venv, bun, dependencias y pitfalls reales).
- [`DOCKER.md`](runbooks/DOCKER.md): Ejecución del stack completo con Docker Compose.
- [`DEPLOY_RUNBOOK.md`](runbooks/DEPLOY_RUNBOOK.md): Procedimiento de despliegue en Vercel (Frontend) y Railway (Backend).
- [`DEMO_DEPLOYMENT_PLAN.md`](runbooks/DEMO_DEPLOYMENT_PLAN.md): Plan de despliegue de arquitectura para entornos productivos.

---

### 5. Manuales de Producto (`docs/manual/`)
- [`USER_MANUAL.md`](manual/USER_MANUAL.md): Guía de uso para el productor / usuario final en el Studio.
- [`UX_MAP.md`](manual/UX_MAP.md): Diagrama de estados, navegación y flujo funcional de usuario.

---

### 6. Histórico Inmutable (`docs/archive/`)
- [`INTEGRATION_REPORT.md`](archive/INTEGRATION_REPORT.md): Reporte histórico del bloque de integración.
- [`HUMANMIDI_REMOVAL_REPORT.md`](archive/HUMANMIDI_REMOVAL_REPORT.md): Registro formal de la remoción de componentes heredados.
- [`HANDOFF_BACKEND_CONVEX.md`](archive/HANDOFF_BACKEND_CONVEX.md), [`WORKPLAN.md`](archive/WORKPLAN.md), [`PLAN.md`](archive/PLAN.md).

---

## 🔍 Guía Rápida: "¿Dónde busco X?"

| Pregunta o Necesidad | Ruta Directa |
|---|---|
| ¿Cómo levanto el proyecto localmente? | [`docs/runbooks/SETUP.md`](runbooks/SETUP.md) |
| ¿Cuál es la hoja de ruta y fases del proyecto? | [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) |
| ¿Dónde están los reportes formales de cierre de cada fase? | [`docs/evidence/reports/`](evidence/reports/) |
| ¿Cuáles son las reglas de código y comportamiento de IA? | [`.agents/rules/`](../.agents/rules/) y [`AGENTS.md`](../AGENTS.md) |
| ¿Cómo funciona la cadena DSP y sus parámetros exactos? | [`docs/reference/specs/08_implementacion_llm.md`](reference/specs/08_implementacion_llm.md) |
| ¿Cómo desplegar en producción? | [`docs/runbooks/DEPLOY_RUNBOOK.md`](runbooks/DEPLOY_RUNBOOK.md) |
| ¿Qué ve el usuario final y cuál es el mapa UX? | [`docs/manual/USER_MANUAL.md`](manual/USER_MANUAL.md) |