# PLAN.md — División de trabajo (5 personas)

> Fuente de verdad de **quién hace qué**.
> Las reglas técnicas no negociables siguen viviendo en [`AGENTS.md`](../../AGENTS.md).
> Los contratos de datos son la única interfaz entre módulos.
>
> **⚠️ 2026-09-11:** HumanMidi (área de David, `apps/humanmidi/`) fue **removido del producto**. Las referencias de este plan quedan como histórico; el Live Engine y el Bridge se mantienen. Ver `HUMANMIDI_REMOVAL_REPORT.md`.

---

## 1. El producto

Plataforma web de mastering asistido por IA, con reproducción en vivo del master con FX (Live Engine Web Audio).

```
1. Login
2. Panel · adjuntar audio
3. Chat IA · "quiero que suene de tal manera"
4. Dashboard · perillas, acentos, módulos
5. Procesar → finalizar
6. Descargar + Live Engine (FX en vivo con knobs)
```

---

## 2. Arquitectura — decisiones tomadas

Estas cuatro decisiones cierran las contradicciones del plan original. **No se re-discuten sin acuerdo del equipo.**

### D1 · Convex orquesta, AudioMind ejecuta

Convex **no puede correr el motor de mastering** (es Python: librosa, pedalboard, demucs-onnx). La flecha `Convex → Mastering Engine` no es directa.

```
Browser ──upload──> Convex Storage
   │                    │
   │                    └── signed URL
   ▼                             │
Convex (auth, projects,          ▼
  chat, settings, jobs) ──HTTP──> AudioMind (FastAPI, stateless)
   ▲                             │
   └──── resultado + métricas ───┘
```

- **El audio nunca viaja como payload de función Convex.** Convex Storage guarda el archivo; a AudioMind se le pasa una URL firmada.
- AudioMind se despliega aparte (Railway / Fly / Render). Hoy guarda sesiones en un `dict` en memoria: **se vuelve stateless**, Convex es la única fuente de verdad del estado.

### D2 · Tres capas de parámetros, nunca mezcladas

| Capa | Qué es | Cuántos campos | Dueño |
|---|---|---|---|
| `IntentProfile` | Lo que **la IA** entiende del usuario. Vocabulario semántico. | ~12 | Miguel |
| `MasteringSettings` | Lo que **el motor** ejecuta. Parámetros técnicos reales. | ~40 | Brickman |
| `LiveParams` | Lo que el **Live Engine** mueve en tiempo real. Nodos Web Audio. | 8 | — |

**La IA no emite parámetros técnicos.** Emite `IntentProfile`; un **mapper propiedad de Brickman** lo traduce a `MasteringSettings`. Así Brickman ajusta el sonido sin tocar el prompt, y Miguel mejora el agente sin tocar el DSP.

```
Lenguaje natural → IA → IntentProfile → [mapper] → MasteringSettings → Motor → Audio
                                ↑                          ↑
                          validación Zod           validación Pydantic
```

### D3 · El Live Engine controla `LiveParams`, no `MasteringSettings`

Ya está implementado y funcionando. El Live Engine **no reprocesa el track**: son nodos Web Audio sobre el master ya renderizado. Las perillas del Dashboard (paso 4) y las del Live (paso 6) son **conjuntos distintos** y se ven distinto en la UI.

### D4 · La IA nunca escribe en el motor

`MasteringSettings` solo se escribe desde: (a) el mapper, (b) las perillas del usuario, (c) un preset. Nunca desde el LLM directamente.

---

## 3. Contratos — se congelan en las primeras 2 horas

Viven en [`packages/contracts/`](packages/contracts/). **Nadie escribe código de integración antes de que existan.**

| Archivo | Estado | Responsable |
|---|---|---|
| `live_params.schema.json` | ✅ ya existe | David |
| `mastering_settings.schema.json` | ⬜ generar desde `MasteringParameters` | Brickman |
| `intent_profile.schema.json` | ⬜ escribir | Miguel |
| `project_state.schema.json` | ⬜ escribir (estados del job) | Tomás |

### `IntentProfile` — propuesta inicial

Todos los ejes van de `0.0` a `1.0`, donde **`0.5` = neutral = master transparente**.

```json
{
  "warmth":        0.5,
  "punch":         0.5,
  "clarity":       0.5,
  "brightness":    0.5,
  "width":         0.5,
  "bass_weight":   0.5,
  "vocal_focus":   0.5,
  "vintage":       0.5,
  "loudness":      0.5,
  "target_platform": "spotify",
  "reference_genre": "reggaeton",
  "notes": "el usuario pidió voz al frente sin perder graves"
}
```

### Mapper `IntentProfile → MasteringSettings` (Brickman define los valores exactos)

| Eje semántico | Parámetros reales que mueve |
|---|---|
| `warmth` | `saturation_warmth_db`, `tape_enabled`, `tape_drive_db` |
| `punch` | `transient_boost_db`, `adaptive_comp_ratio`, `adaptive_comp_attack_ms` |
| `clarity` | `clarity_wet`, `dyn_eq_enabled` |
| `brightness` | `clarity_brightness_db`, `exciter_enabled` |
| `width` | `stereo_width`, `stereo_imaging_*_width` |
| `bass_weight` | `multiband_low_threshold_db`, `multiband_low_ratio`, `stereo_imaging_mono_below_hz` |
| `vocal_focus` | `dyn_eq` banda media |
| `vintage` | `tape_hysteresis`, `tape_bias`, `tape_rolloff_amount` |
| `loudness` | `target_lufs_db`, `limiter_ceiling_db` |

**Regla dura:** con todos los ejes en `0.5`, el mapper debe devolver los **defaults exactos** de `MasteringParameters` — es decir, bypass bit-exacto. Es el test que valida el mapper entero.

---

## 4. División por persona

### 🎨 Andrés — Diseño, UX/UI

**Dueño de:** `apps/studio/src/components/`, `apps/studio/src/app/`, sistema visual.

| Pantalla | Entregable |
|---|---|
| Login | Registro, login, recuperación, estados de carga/error |
| Panel | Dashboard, dropzone, historial de proyectos, estado del job |
| Chat IA | Burbujas, typing indicator, sugerencias rápidas, tarjeta de "configuración propuesta" con diff vs. actual |
| Dashboard mastering | Perillas por módulo (Claridad, Fuego, Cinta, Espacial, Loudness), acentos, valor + unidad visible |
| Procesar | Botón, progreso, mensajes de estado, errores |
| Resultado | Player A/B antes/después, descarga, métricas (LUFS, true peak), entrada al Live Engine |

**Ya existe y se reutiliza:** `Knob3D`, `ModulePanel`, `SignalChain`, `Player`, `DropZone`, `ProcessingOverlay`, `PresetSelector`, `ThemeToggle`.

**No toca:** lógica de Convex, prompts de IA, valores DSP.

**Listo cuando:** cada pantalla existe, es responsive, y tiene sus estados de carga/vacío/error. Microcopy en español rioplatense (voseo): "Subí", "Ajustá", "Probá de nuevo".

---

### 🤖 Miguel — Agente de IA

**Dueño de:** `apps/agent/` (nuevo), `packages/contracts/intent_profile.schema.json`, la lógica del chat.

**Entregables:**

1. `intent_profile.schema.json` + tipos generados (TS y Python).
2. **Prompt principal** del agente: rol, vocabulario, cuándo preguntar, cuándo no inventar.
3. **Interpretación de intención**: lenguaje natural → `IntentProfile` validado.
4. **Memoria de conversación** por proyecto (persiste en Convex, no en RAM).
5. **Preguntas de aclaración**: si la intención es ambigua ("que suene mejor"), pregunta en vez de adivinar.
6. **Explicación en lenguaje natural** de lo que cambió y por qué — es lo que hace que la demo se entienda.
7. **Validación**: `IntentProfile` fuera de rango se rechaza, no se clampea en silencio.
8. Integración con Convex (action que llama al LLM) y con el chat de Andrés.

**No toca:** el motor DSP, el mapper (es de Brickman), los valores de `MasteringSettings`.

**Listo cuando:** "quiero que suene más cálida, con la voz al frente" produce un `IntentProfile` válido, el mapper lo convierte, y las perillas del dashboard se mueven solas.

---

### ⚙️ Tomás — Backend, Convex, arquitectura, despliegue

**Dueño de:** `apps/studio/convex/`, despliegue, variables de entorno, CI.

**Modelo de datos:**

```
users
└── projects
     ├── audioFileId        (Convex Storage)
     ├── masteredFileId     (Convex Storage)
     ├── messages[]         (chat IA)
     ├── intentProfile      (última salida de la IA)
     ├── masteringSettings  (lo que se va a procesar)
     ├── job { status, progress, error }
     └── result { lufs, truePeak, crest, ... }
```

**Estados del job:** `pending → processing → completed | failed`
(mapear a los de AudioMind: `uploaded → analyzing → processing → completed | error`)

**Entregables:**

1. Auth (Convex Auth): registro, login, sesión, protección de recursos por `userId`.
2. Schema + queries + mutations + actions.
3. Upload a Convex Storage + URL firmada para AudioMind.
4. Action `startMastering`: **idempotente** — si ya hay un job `processing` para ese proyecto, no lanza otro.
5. Despliegue de AudioMind como servicio HTTP + su URL en variables de entorno.
6. Deploy del studio + CI.

**No toca:** valores DSP, prompts, diseño visual.

**Listo cuando:** dos usuarios distintos no ven los proyectos del otro, y darle 3 veces a "Procesar" genera **un** job.

---

### 🎚️ Brickman — Mastering y procesamiento

**Dueño de:** `apps/audiomind/`, el mapper, los presets, los rangos.

**Punto de partida — buena noticia:** los parámetros **ya están definidos** en [`apps/audiomind/src/audiomind/models/audio.py:37`](apps/audiomind/src/audiomind/models/audio.py#L37), con min/max/default/descripción por campo. El trabajo no es inventarlos, es curarlos.

**Entregables:**

1. **Podar la lista**: de ~40 campos, elegir los ~10–14 que el usuario ve como perillas. El resto queda interno.
2. `mastering_settings.schema.json` generado desde `MasteringParameters`.
3. **El mapper** `IntentProfile → MasteringSettings` con los valores exactos.
4. **Test de neutralidad**: todos los ejes en `0.5` → defaults exactos → audio bit-exacto al original.
5. **Presets** por género + reglas de combinación (qué no se puede subir junto sin romper el master).
6. Endpoint stateless `POST /api/master` (audio URL + settings → audio + métricas).
7. Validar que lo que produce la IA suene bien de verdad.

**No toca:** Convex, prompts, UI.

**Listo cuando:** el test de neutralidad pasa y 3 intenciones distintas ("cálida", "agresiva", "moderna") suenan claramente distintas y ninguna distorsiona.

---

### 🎚️ Live Engine — FX en vivo (sobre el master real)

**Dueño de:** `apps/studio/src/lib/live/`, `apps/studio/src/presentation/components/live/`.

**Punto de partida — buena noticia:** el Live Engine **ya funciona** como reproductor standalone: knobs (mouse/teclado) → `LiveParams` → Web Audio → knobs y meters. La visión/gestos/MIDI/bridge fueron eliminados.

**Entregables:**

1. Conectar el Live Engine al **master real** del proyecto (hoy es independiente del flujo).
2. Grabar la salida del Live (`recorder.ts` ya existe) y poder descargarla.
3. Robustez de audio: sin glitches al girar knobs mientras suena.

**No toca:** el motor de mastering offline, el schema de Convex, prompts.

**Listo cuando:** se sube una canción, se masteriza, se abre Live, y los knobs mueven el filtro y el delay sobre el master real, sin glitches de audio.

---

## 5. Orden de ataque

### Hito 0 · Contratos (primeras 2 h — los 5 juntos)

Se escriben y congelan los 4 schemas. Nadie integra antes de esto.

### Hito 1 · Vertical slice (lo más importante)

**Login → subir → procesar con defaults → descargar.** Sin IA, sin dashboard bonito.
Demuestra que la tubería completa funciona de punta a punta. Si esto no está, nada más importa.

- Tomás: auth + storage + job + llamada a AudioMind
- Brickman: endpoint stateless
- Andrés: las 3 pantallas en versión mínima
- Miguel: avanza en paralelo sin bloquear

### Hito 2 · Inteligencia y control

- Miguel: chat → `IntentProfile`
- Brickman: mapper + presets
- Andrés: dashboard de perillas completo
- Tomás: persistencia de chat y settings

### Hito 3 · Live Engine y pulido

- Live: publisher del Live sobre el master real + grabación
- Andrés: A/B, métricas, pantalla de resultado
- Todos: ensayo de demo

> ⚠️ **Riesgo principal del hackathon:** reconstruir en Convex lo que ya funciona en FastAPI puede quemar todo el tiempo. Convex suma **auth, proyectos, chat y estado** — no reemplaza el motor. Si Convex se atrasa, el Hito 1 puede correr contra AudioMind directo y Convex se enchufa después.

---

## 6. Dependencias — quién bloquea a quién

```
Contratos (todos) ──> desbloquea a todos

Brickman ──[mastering_settings]──> Miguel  (necesita el target del mapper)
Brickman ──[lista de perillas]───> Andrés  (necesita saber qué dibujar)
Tomás    ──[schema Convex]───────> Miguel, Andrés
Miguel   ──[intent_profile]──────> Andrés  (tarjeta de propuesta en el chat)
```

**Regla anti-bloqueo:** si estás esperando a alguien, trabajá contra el **schema** con datos falsos. El contrato existe justamente para eso.

---

## 7. Reglas de trabajo

- **Ramas:** `feat/<area>` desde `develop`. PR a `develop`. `main` solo recibe merges de `develop`.
  Áreas: `ui`, `agent`, `backend`, `dsp`, `live`.
- **Commits semánticos:** `feat:`, `fix:`, `test:`, `docs:`, `chore:`.
- **Contratos primero.** Si cambia un schema, se avisa al equipo y se regeneran los tipos. Nunca se editan tipos generados a mano.
- **Neutral = bypass.** Parámetro neutral ⇒ audio idéntico. En el motor y en el Live Engine. Se preserva en todas las rutas.
- **El audio nunca viaja por la red del Live** — los knobs escriben `LiveParams` directamente en el grafo Web Audio del navegador.
- **Web Audio:** todo cambio con `setTargetAtTime(value, ctx.currentTime, 0.02)`, nunca asignación directa.
- **Microcopy en español rioplatense** (voseo).
- Tests junto al código. No se rompe la suite existente.

---

## 8. Definición de "listo" — por paso del flujo

| # | Paso | Listo cuando |
|---|---|---|
| 1 | Login | Un usuario no ve los proyectos de otro |
| 2 | Adjuntar audio | WAV/MP3 sube, se ve la forma de onda y el análisis (LUFS, BPM, género) |
| 3 | Chat IA | Una frase en lenguaje natural produce un `IntentProfile` válido y explicado |
| 4 | Dashboard | Las perillas reflejan la propuesta de la IA y se pueden corregir a mano |
| 5 | Procesar | Un solo job, progreso real, resultado descargable |
| 6 | Live Engine | Los knobs mueven el master real en tiempo real, sin glitches |

---

## 9. Estado del repo

- `main` y `develop` en el mismo commit.
- Instalado y verificado localmente: `apps/studio` (:3000), `apps/audiomind`, `ffmpeg`.
- **Falta por crear:** `apps/studio/convex/`, `apps/agent/`, los 3 schemas nuevos.

Cómo levantar cada pieza: ver [`README.md`](../../README.md).
