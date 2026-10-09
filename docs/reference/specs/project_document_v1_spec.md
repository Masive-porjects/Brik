# Project Document V1 — Spec de diseño (multi-tenant Moises)

> **Estado:** diseño aprobado, pendiente de migración (WU4) + compiler (WU5).
> **Alcance:** V1 acotada. Todo claim es trazable al código citado; los enums y
> rangos fueron verificados contra el motor en ejecución, no contra suposiciones.

## 1. Contexto y decisión

La migración multi-tenant estilo Moises introduce tres tablas
(`supabase/migrations/20261008120000_create_project_document.sql`):

- `projects` — raíz del documento por usuario (`name`, `bpm`, `musical_key`).
- `audio_assets` — original, stems y masters como llaves R2 durables.
- `project_states` — el mix **vivo** como JSONB (faders, undo/redo).

Falta la cuarta pieza: **`project_documents`**, que guarda la **intención y la
estructura** del proyecto. Esta spec define su schema V1, el contrato de
ownership que evita split-brain, y el compiler que alimenta el DSP.

### Decisiones de alcance (aceptadas por el producto)

1. **Estrictamente los 4 stems de Demucs**: `("drums", "bass", "other", "vocals")`
   — `processing/splitter.py:33`, `processing/demucs_worker.py:36`.
2. **Sin timeline ni rango temporal.** El MixPlan V1 es solo parámetros globales.
   La automatización por compases queda para `schema_version: 2`.
3. **Sin split-brain:** `project_states` sigue siendo el write target del usuario
   en vivo; `project_documents` queda como lectura de intención y estructura.

### Por qué no se modelan roles finos (kick/snare/guitarra)

El motor separa en 4 stems fijos. Un documento que prometiera `kick`, `snare` o
`guitar` describiría un motor que no existe — exactamente el error de diseñar
para el motor soñado en vez del que corre hoy.

---

## 2. Contrato de ownership — cada dato, una casa, un escritor

La regla que elimina el split-brain **no es un mecanismo de merge: es
no-overlap**. Si un dato vive en una sola tabla, no hay conflicto que resolver.

| Dato | Casa | Único escritor | ¿Llega al DSP? |
|---|---|---|---|
| Faders (`stem_trims`), toggles vivos (`dimension_enabled`, `auto_balance`), `undo_stack` | `project_states.state` | **Solo el store del frontend** (autosave) | Sí |
| Identidad + presentación de los 4 stems (`display_name`, `order`, `group_id`, `color`) | `project_documents.structure` | CRUD de estructura (usuario) | Validación de claves |
| Propuestas de la IA (faders / toggles / master) | `project_documents.mix_intent.proposals` | Intelligence | **No, hasta que se apliquen** |
| Intención de master (`preset_id`, `platform_target`, `format`, `output_bit_depth`, `parameters`) | `project_documents.master_intent` | Usuario + Intelligence | Sí |
| Metadata (`name`, `bpm`, `musical_key`) | `projects` | Análisis / usuario | No |

**Las claves no se solapan entre `project_states` y `project_documents`.** Por
eso no existe una precedencia que definir: no hay dos fuentes para el mismo knob.

### Tres invariantes

- **I1 — Un solo escritor en `project_states`:** solo el store del frontend vía
  autosave. Ni la IA ni el compiler escriben esa tabla. Esto mantiene intacto el
  `undo_stack`, que vive en la misma fila: si un segundo escritor la mutara, el
  undo se rompería.
- **I2 — El compiler es una función pura:** lee ambas tablas, escribe ninguna.
- **I3 — El DSP no tiene tabla de knobs persistente:** los parámetros viajan en
  el request de cada job. Lo durable es `dsp_jobs` (meta/resultado); las sesiones
  están en memoria. "Actualizar el DSP" = producir el plan para esa corrida.

---

## 3. JSON Schema V1

Almacena en `project_documents.document_json`, validado contra este schema.

- `version` (concurrencia optimista) vive **solo** en la fila, nunca en el
  JSON — una sola fuente, sin drift. El PUT compara `expected_version` contra
  la fila y escribe condicionalmente (`.eq("version", expected)`).
- `schema_version`, `updated_by` y `updated_at` sí pertenecen al documento (el
  schema los exige/declara) y **el servidor los pisa en cada escritura**:
  `updated_at` con su reloj, `schema_version` con `1`, `updated_by` desde el
  valor validado del payload (default `user`). El cliente no puede falsearlos.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://waveia.app/schemas/project_document.v1.json",
  "title": "ProjectDocument",
  "description": "Intention + structure of one project. Deliberately excludes timeline, automation, and live faders.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "structure", "mix_intent", "master_intent"],
  "properties": {
    "schema_version": { "const": 1 },
    "structure":     { "$ref": "#/$defs/structure" },
    "mix_intent":    { "$ref": "#/$defs/mixIntent" },
    "master_intent": { "$ref": "#/$defs/masterIntent" },
    "updated_by":    { "enum": ["user", "intelligence", "system"], "default": "user" },
    "updated_at":    { "type": "string", "format": "date-time" }
  },
  "$defs": {
    "stemName": { "enum": ["drums", "bass", "other", "vocals"] },

    "structure": {
      "type": "object",
      "additionalProperties": false,
      "required": ["stems"],
      "properties": {
        "stems": {
          "type": "object",
          "additionalProperties": false,
          "required": ["drums", "bass", "other", "vocals"],
          "description": "Object-keyed: requires all 4 Demucs stems, forbids duplicates and extras structurally.",
          "properties": {
            "drums":  { "$ref": "#/$defs/stemNode" },
            "bass":   { "$ref": "#/$defs/stemNode" },
            "other":  { "$ref": "#/$defs/stemNode" },
            "vocals": { "$ref": "#/$defs/stemNode" }
          }
        },
        "groups": {
          "type": "array",
          "default": [],
          "items": { "$ref": "#/$defs/group" },
          "description": "UI-only in V1. build_mix has no bus routing, so groups do not affect DSP."
        }
      }
    },

    "stemNode": {
      "type": "object",
      "additionalProperties": false,
      "required": ["display_name", "order"],
      "properties": {
        "display_name": { "type": "string", "minLength": 1, "maxLength": 64 },
        "order":        { "type": "integer", "minimum": 0, "maximum": 3 },
        "group_id":     { "type": ["string", "null"] },
        "color_token":  { "type": "string", "maxLength": 64 },
        "hidden":       { "type": "boolean", "default": false }
      }
    },

    "group": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "display_name"],
      "properties": {
        "id":           { "type": "string", "minLength": 1, "maxLength": 64 },
        "display_name": { "type": "string", "minLength": 1, "maxLength": 64 },
        "order":        { "type": "integer", "minimum": 0 },
        "color_token":  { "type": "string", "maxLength": 64 }
      }
    },

    "mixIntent": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "genre":     { "type": ["string", "null"], "maxLength": 64 },
        "character": { "type": ["string", "null"], "maxLength": 256 },
        "proposals": {
          "type": "array",
          "default": [],
          "items": { "$ref": "#/$defs/proposal" }
        }
      }
    },

    "proposal": {
      "description": "Pending intent change. NEVER audible until explicitly applied to project_states.",
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "kind", "payload", "status", "created_at"],
      "properties": {
        "id":         { "type": "string", "format": "uuid" },
        "kind":       { "enum": ["fader", "toggle", "master"] },
        "payload":    {
          "type": "object",
          "description": "Partial knob change, e.g. {\"vocals_db\": 2.0}"
        },
        "rationale":  { "type": "string", "maxLength": 1024 },
        "status":     { "enum": ["pending", "accepted", "rejected"] },
        "created_at": { "type": "string", "format": "date-time" },
        "decided_at": { "type": ["string", "null"], "format": "date-time" }
      }
    },

    "masterIntent": {
      "type": "object",
      "additionalProperties": false,
      "description": "Mirrors the TOP-LEVEL fields of MasterJobPayload (services/dsp_worker.py), not MasteringParameters.",
      "properties": {
        "preset_id": {
          "enum": ["universal", "fuego", "claridad", "cinta",
                   "natural", "espacial", "cinematico", "empuje"]
        },
        "platform_target": {
          "enum": ["spotify", "apple_music", "youtube", "tidal", "club", "cd", "custom"],
          "description": "7-value payload set. NOT the 5-value MasteringParameters.platform_target."
        },
        "format":           { "enum": ["wav", "mp3"], "default": "wav" },
        "output_bit_depth": { "type": "integer", "minimum": 16, "maximum": 32, "default": 24 },
        "master_name":      { "type": ["string", "null"], "maxLength": 128 },
        "parameters": {
          "type": ["object", "null"],
          "default": null,
          "description": "Partial override of MasteringParameters (models/audio.py, ~870 lines). NOT inlined here — Pydantic is the authority; validated server-side on submit."
        }
      }
    }
  }
}
```

### Notas de diseño del schema

1. **`stems` es un objeto con `required` las 4 claves y `additionalProperties:
   false`.** La restricción "estrictamente los 4 de Demucs" queda **estructural**:
   un JSON con 3, 5, o una clave `snare` ni siquiera valida. Es más fuerte que un
   array con `minItems/maxItems`, que no impide duplicados.
2. **`platform_target` usa el set de 7** porque `master_intent` se proyecta a los
   campos top-level de `MasterJobPayload` (`services/dsp_worker.py:96-99`).
   `MasteringParameters.platform_target` (`models/audio.py:183`) acepta solo 5
   (sin `club`/`cd`); meter el valor ahí dentro produciría un 422. El compiler
   setea `payload.platform_target` y **nunca** `parameters.platform_target`.
3. **No hay `faders`, ni `timeline`, ni `automation`** — deliberadamente. Los
   faders son de `project_states` (invariante I1); la automatización queda para
   `schema_version: 2`.
4. **`structure.stems` no referencia `asset_id`.** Los assets de stem se crean y
   se reemplazan en la separación (nuevo `media_hash` ⇒ nuevas filas). El
   documento identifica por `stem_name`; el compiler resuelve
   `stem_name → audio_assets` al momento de compilar, así el documento no queda
   apuntando a assets viejos.

---

## 4. Proyección de `project_states` que consume el compiler

`project_states.state` es `jsonb` frontend-owned — la migración lo declara
explícitamente: *"shape evolves with the Studio"*. El compiler **no** valida el
objeto completo; proyecta solo lo que necesita y **defaultea a neutral** en lo
que falte:

| Campo | Tipo | Rango | Default | Fuente |
|---|---|---|---|---|
| `faders.drums_db` | float | `[-6.0, 6.0]` | `0.0` | `TRIM_STEM_RANGE` — `processing/stem_balance.py:39` |
| `faders.bass_db` | float | `[-6.0, 6.0]` | `0.0` | ídem |
| `faders.other_db` | float | `[-6.0, 6.0]` | `0.0` | ídem |
| `faders.vocals_db` | float | `[-6.0, 6.0]` | `0.0` | ídem |
| `toggles.dimension_enabled` | bool | — | `true` | `api/mix.py:72` |
| `toggles.auto_balance` | bool | — | `false` | `api/mix.py:74` |

Las llaves del request son `{stem}_db`, derivadas de `STEM_NAMES`:
`_STEM_TRIM_KEYS = tuple(f"{name}_db" for name in STEM_NAMES)` — `api/mix.py:38`.

**Neutral = bypass = master idéntico al original.** Un `state` malformado o
hostil no rompe el compile ni inyecta valores fuera de rango; y el backend
re-valida `stem_trims` contra `TRIM_STEM_RANGE` en el submit (`api/mix.py:77-96`),
tal como ya lo hace hoy.

---

## 5. El compiler — función pura

**Archivo:** `apps/audiomind/src/audiomind/services/compile_project.py`

```python
"""Compila (document, state) -> MixPlan. Puro: sin I/O de escritura."""

from pydantic import BaseModel, Field

class StateProjection(BaseModel):
    """Lo mínimo que el compiler exige de project_states.state, con defaults
    neutrales. Cualquier campo ausente o fuera de rango cae al default."""
    faders: dict[str, float] = Field(default_factory=dict)   # {stem}_db -> dB
    toggles: dict[str, bool] = Field(
        default_factory=lambda: {"dimension_enabled": True, "auto_balance": False}
    )

class MixPlan(BaseModel):
    # ── para build_mix (processing/mix_engine.py:490) ──
    stem_trims: dict[str, float] | None     # None si todo es 0.0 (neutral)
    dimension_enabled: bool                 # -> dimension_profiles: None | {}
    auto_balance: bool

    # ── para MasterJobPayload (services/dsp_worker.py:68) ──
    preset_id: str | None
    platform_target: str | None             # set de 7, top-level del payload
    format: str                             # default "wav"
    output_bit_depth: int                   # default 24
    master_name: str | None
    parameters: MasteringParameters | None  # overlay validado por Pydantic


def load_inputs(project_id: str, user_id: str) -> tuple["ProjectDocument | None",
                                                       StateProjection]:
    """SELECT de project_documents y project_states.
    Sin ownership => 404/403. Jamás un UPDATE."""


def compile(document: "ProjectDocument | None",
            state: StateProjection) -> MixPlan:
    """PURO: sin I/O, sin escritura.

    - state ausente/vacío  -> defaults neutrales (0 dB, dimension on, balance off).
    - document ausente     -> estructura derivada de audio_assets kind='stem'
                              + master_intent en defaults.
    - stem_trims           -> None si los 4 faders son 0.0 (neutral = bypass).
    """
```

### Mapeo de la salida a los motores

| `MixPlan` | Destino | Nota |
|---|---|---|
| `stem_trims` | `build_mix(stem_trims=...)` | Claves `{stem}_db`, rango ±6 dB. `None` ⇒ routing bit-exacto |
| `dimension_enabled=True` | `dimension_profiles=None` | Perfiles `DIMENSION_PROFILES` por defecto |
| `dimension_enabled=False` | `dimension_profiles={}` | Dimension deshabilitado, routing idéntico al Paso 03 |
| `auto_balance` | `build_mix(auto_balance=...)` | Default `False` |
| `preset_id`, `platform_target`, `format`, `output_bit_depth`, `master_name` | `MasterJobPayload` top-level | Set de 7 en `platform_target` |
| `parameters` | `MasterJobPayload.parameters` | `MasteringParameters`; overlay parcial, Pydantic valida |

### Por qué el compiler no puede pisar `project_states`

1. **No tiene ruta de escritura.** `compile()` es pura; `load_inputs()` solo
   ejecuta `SELECT`. No existe ningún `UPDATE project_states` en el módulo.
2. **El DSP no tiene knobs persistente** (invariante I3): el plan se inyecta en
   `build_mix(...)` / `MasterJobPayload` solo para esa corrida.
3. **Un solo escritor** (invariante I1): el store del frontend, vía autosave.

---

## 6. Los tres flujos

### 6.1 Usuario vivo (camino existente, sin cambios)

```
1. Usuario arrastra un fader
     -> store actualiza en memoria
     -> autosave (debounce) PATCH /project_states { state, undo_stack }
2. Usuario pulsa "Mezclar"
     -> POST /projects/{id}/jobs/mix        (server-compiled)
3. Compiler: load_inputs() -> compile(document, state) -> MixPlan
4. MixPlan -> build_mix(...) -> audio en outputs
5. Resultado registrado en audio_assets (kind='master')
```

El frontend solo escribe `project_states`; el documento no participa salvo para
validar las claves de estructura.

### 6.2 Propuesta de IA — "la IA propone, el usuario aplica"

Este es el flujo que protege `project_states` y el `undo_stack`:

```
1. Intelligence decide "vocals +2 dB"
     -> ESCRIBE en project_documents:
        mix_intent.proposals.push({
          id, kind: "fader",
          payload: { "vocals_db": 2.0 },
          rationale: "...",
          status: "pending",
          created_at
        })
     -> NO toca project_states                    [invariante I1]

2. Frontend detecta la propuesta (poll / Realtime)
     -> UI: "La IA sugiere: voz +2 dB — Aplicar / Rechazar"

3a. Usuario pulsa APLICAR
     -> el store aplica { "vocals_db": 2.0 } a su estado en memoria
     -> la MISMA ruta de autosave PATCHea project_states
     -> proposal.status = "accepted" en el documento

3b. Usuario pulsa RECHAZAR
     -> proposal.status = "rejected"
     -> project_states intacto

4. Siguiente compile ya lee el valor nuevo desde state
```

**Por qué es seguro:** la IA influye en el fader **pasando por el store**,
nunca escribiendo la tabla. Resultado: un solo escritor (I1), `undo_stack`
coherente — el cambio de la IA es un paso de undo más, y el usuario siempre ve
y aprueba el cambio antes de que sea audible.

### 6.3 Primera carga / state vacío

```
1. GET /projects/{id}/state  ->  {}   (fila nueva o sin uso)
2. Proyección -> defaults neutrales:
     4 faders en 0.0, dimension_enabled=True, auto_balance=False
3. compile() -> stem_trims = None  =>  neutral = bypass
```

**No se siembra el state desde el documento.** El documento no tiene faders
audibles por diseño (§3 nota 3); los valores que sí entran al DSP vienen del
state o de propuestas aplicadas explícitamente (§6.2).

---

## 7. Coexistencia con los endpoints existentes

| Endpoint | Quién compila | Estado |
|---|---|---|
| `POST /mix` (sesión, params explícitos) | Cliente | **Se mantiene** — path de sesión anónimo |
| `POST /jobs/master` (payload explícito) | Cliente | **Se mantiene** |
| `POST /projects/{id}/jobs/mix` | Server (`compile_project`) | Nuevo — path multi-tenant |
| `POST /projects/{id}/jobs/master` | Server (`compile_project`) | Nuevo — multi-tenant |

El compiler es un **módulo compartido**, no un reemplazo de los endpoints
existentes. El `MixPlan` viaja en el request del job hacia `dsp_jobs`; esta spec
**no toca** `dsp_jobs`, su drift-guard (`tests/test_dsp_jobs_migration.py`), ni
la idempotencia de separación por `media_hash` (WU2).

---

## 8. Trazabilidad — hechos verificados contra el código

| Hecho | Fuente |
|---|---|
| `STEM_NAMES = ("drums", "bass", "other", "vocals")` | `processing/splitter.py:33`, `processing/demucs_worker.py:36` |
| `TRIM_STEM_RANGE = (-6.0, 6.0)` | `processing/stem_balance.py:39` |
| `_STEM_TRIM_KEYS = (f"{name}_db" ...)` | `api/mix.py:38` |
| Validación de rango en submit | `api/mix.py:93`, `api/jobs.py:152` |
| `dimension_enabled=True`, `auto_balance=False` (defaults) | `api/mix.py:72,74` |
| `build_mix(dimension_profiles, auto_balance, stem_trims, progress_cb)` | `processing/mix_engine.py:490-507` |
| `dimension_profiles=None` ⇒ default; `{}` ⇒ off | `processing/mix_engine.py:760-769` |
| 8 presets | `services/dsp_worker.py:88-89`, `intelligence/schemas/preset_knowledge.py:61` |
| `platform_target` set de 7 (payload) | `services/dsp_worker.py:96-99` |
| `platform_target` set de 5 (params) | `models/audio.py:183` |
| `format: wav\|mp3`, `output_bit_depth: 16..32` | `services/dsp_worker.py:100-108` |
| Tablas y RLS `auth.uid() = user_id` | `supabase/migrations/20261008120000_create_project_document.sql` |
| `dsp_jobs` intacto, contexto en `meta` | ídem, comentario de cabecera L16-20 |

---

## 9. Fuera de alcance V1 (posibles futuros `schema_version`)

- **Timeline y automatización por compases** — el motor no la consume hoy.
- **`stem_trims` con automatización** — solo gain global ±6 dB por stem.
- **Roles finos por sub-stem** (kick/snare/guitar) — Demucs no los produce.
- **Grupos con routing de bus** — `build_mix` no acepta buses; `groups` es UI-only.
- **Escritura de `project_states` por el backend** — prohibida por I1; cualquier
  necesidad futura debe pasar por el flujo de propuestas (§6.2).

---

*Especificación de diseño · V1 · rama `feature/moises-architecture-migration`.*
