# Reporte de Implementación — IA ↔ Motor de Mezcla

**Fecha:** 2026-09-28
**Responsable:** Miguel Angel Ariza (IA)
**Rama:** `feat/ia-asistente-mezcla`
**Rama base:** `develop`
**Estado:** 🟡 En curso — sub-entregas 1–3 completadas (mapper de mezcla, contrato IntentProfile, prompt)

---

## 1. Resumen ejecutivo

Objetivo de la línea de trabajo (reunión Wave AI, tareas de Miguel): conectar la inteligencia artificial con los parámetros de **mezcla** y **masterización**, construir el asistente con conocimiento especializado (libros de mezcla, vía chunks + vectores) e incorporar criterios por género.

Estado de partida en `develop`:

- `apps/agent` traduce lenguaje natural → `IntentProfile` (9 ejes 0..1, neutral 0.5) con Gemini.
- `processing/mapper.py` traduce `IntentProfile` → `MasteringParameters`, pero **no está conectado a ningún endpoint** (solo lo usan sus tests).
- La **mezcla no tenía mapper**: la IA no podía mover ningún parámetro del Mix Engine.
- `intelligence/` (Knowledge Core) tiene el esqueleto (schemas, plantillas, carpetas) sin contenido ni vectores.
- Los 4 libros de mezcla **aún no están disponibles** (bloquea el RAG).

## 2. Sub-entrega 1 — Mapper intent → mezcla

**Archivos nuevos** (no se modificó código existente del motor ni de la API):

- `apps/audiomind/src/audiomind/processing/mix_mapper.py` — `map_intent_to_mix(IntentProfile) -> MixSettings`.
- `apps/audiomind/tests/test_mix_mapper.py` — contrato de neutralidad, rangos y compatibilidad con `MixRequest`.

**Diseño:**

- Consume el **mismo `IntentProfile`** que el mapper de mastering: una sola petición del usuario mueve mezcla y master de forma coherente.
- Emite solo los knobs que `POST /session/{id}/mix` ya expone (`MixRequest`); `MixSettings` replica sus nombres y defaults, así que `MixRequest(**settings.model_dump())` siempre es un body válido.
- **Neutral = bypass**: `IntentProfile.neutral()` → `MixSettings()` = defaults de `MixRequest` (`stem_trims=None`, sin `trim_report`).

| Eje | Parámetro de mezcla | Curva |
|---|---|---|
| `vocal_focus` | `stem_trims.vocals_db` | −3 dB @ 0.0 · 0 dB @ 0.5 · +3 dB @ 1.0 |
| `vocal_focus` > 0.6 | `vocal_treatment = true` | mismo umbral que la dyn EQ del mapper de mastering |
| `punch` | `stem_trims.drums_db` | −3 / 0 / +3 dB |
| `bass_weight` | `stem_trims.bass_db` | −3 / 0 / +3 dB |
| warmth, clarity, brightness, width, vintage, loudness | — | ejes de mastering: la mezcla queda intacta |

`auto_balance` y `dimension_enabled` se mantienen en sus defaults (opt-ins independientes del motor).

> ⚠️ **Valores provisionales**: las anclas ±3 dB (mitad de la banda ±6 dB de `TRIM_STEM_RANGE`) deben validarse con Paul Morales (dueño del DSP de mezcla) antes de considerarse canónicas.

## 3. Sub-entrega 2 — Contrato `IntentProfile` alineado (Python ↔ JSON Schema ↔ agente)

`packages/contracts/intent_profile.schema.json` es la fuente de verdad y el agente (Zod) ya la cumplía; el modelo Python que consumen los mappers **había derivado**:

| Campo | Schema / agente | Python (antes) | Python (ahora) |
|---|---|---|---|
| `target_platform` default | `"none"` | `"spotify"` | `"none"` |
| `target_platform` valores | enum `spotify, apple, youtube, club, none` | cualquier string | `Literal[...]` del enum |
| `reference_genre` / `notes` | `maxLength` 60 / 500 | sin límite | `max_length` 60 / 500 |
| campos desconocidos | `additionalProperties: false` | aceptados | rechazados (`extra="forbid"`) |

- `tests/test_intent_profile_contract.py` lee el JSON Schema y verifica campos, ejes, defaults, enum, límites y que el `NEUTRAL_PROFILE` del agente valida — el drift ya no puede volver en silencio.
- `tests/test_mapper.py`: la aserción `target_platform == "spotify"` del perfil neutral pasa a `"none"` (codificaba el drift). Ningún mapper lee `target_platform`, así que el audio no cambia.

## 4. Sub-entrega 3 — Prompt del agente en español neutro

`apps/agent/src/prompt.ts`: se eliminó el voseo de las instrucciones (`movas`, `podes`, `Recibis`, `empezas`, `devolves`, `Recien`) — el modelo tiende a imitar el registro del prompt y la regla del repo es español latino neutro sin voseo. El asistente se presenta como **WaveAI** (antes "midiMastering"). Solo cambian 7 líneas de texto; la lógica y el schema de respuesta quedan iguales.

> Nota: la regla 7 del prompt ("No puedes cambiar la mezcla…") sigue vigente a propósito: el mapper de mezcla aún no está conectado al flujo del chat. Se actualizará cuando lo esté.

## 5. Validación

| Comando | Resultado |
|---|---|
| `pytest tests/test_mix_mapper.py tests/test_intent_profile_contract.py tests/test_mapper.py` | **60 passed** |
| `pytest tests/` (suite completa audiomind) | **742 passed / 12 failed** — los mismos archivos fallan en `develop` sin los cambios de esta rama (ver nota) |
| `ruff check` sobre los archivos tocados | 0 errores |
| `mypy` (strict) sobre `mix_mapper.py` e `intent_profile.py` | Success: no issues found |
| `apps/agent`: `tsc --noEmit` | 0 errores |
| `apps/agent`: `bun run check` (contrato, sin API) | 12/12 OK |

> Fallos preexistentes del entorno local (no de esta rama): `test_songstarter*` (faltan samples — correr `scripts/generate_samples.py`), `test_loudness` (errores de memoria de numpy, intermitentes) y `test_inter_engine_handshake::test_build_mix_returns_mix_metadata` (pipeline real con Demucs). Verificado ejecutando los mismos tests con los cambios en stash.

> Observación: `ruff check src tests` sobre todo el backend reporta errores **preexistentes** en archivos no tocados por esta rama (import order, E501, B904…). `ESTADO_PROYECTO.md` afirma "0 errores" — no se corrigen aquí para no mezclar alcances.

## 6. Próximos pasos

1. Validar con Paul las anclas del mapper de mezcla.
2. Exponer el flujo intent → mezcla/master (endpoint o integración con el chat) — coordinar con Andrés, que centraliza el backend y las llamadas a Gemini.
3. Probar `interpretIntent` con credenciales reales de Gemini.
4. RAG con los libros (chunks + vectores sobre `intelligence/`) cuando estén disponibles.
5. Criterios por género: alimentar al agente con el género detectado y los pesos de énfasis del Mix Engine.
