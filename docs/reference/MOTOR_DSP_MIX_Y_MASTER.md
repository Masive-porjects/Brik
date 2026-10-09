# Motor DSP de WaveAI — cómo se procesa una mezcla y después el master

> Documento de referencia técnica. Describe, contra el código real, el recorrido completo de una canción por el **Mix Engine** (mezcla) y el **Mastering Engine** (master), el orden exacto de etapas, los parámetros que las gobiernan y el contrato de neutralidad.
>
> Fuente de verdad del código: `apps/audiomind/src/audiomind/processing/` y `apps/audiomind/src/audiomind/models/`.
> Última revisión del documento: contra el estado actual del repo.

---

## 0. Resumen en una frase

`Audio → split (Demucs) → cadena por stem (pan → EQ → compresor → dimensión) → sum → bus compressor → QC → mix.wav` y después `mix.wav (u original) → gain staging → gate → de-esser → EQ/EQ de carácter → compresión → multibanda → dyn-EQ → exciter → espacial → time FX → cinta → mono-compat → loudness → soft-clip → true-peak limiter → dither → master.wav`.

Dos motores independientes, con un **handshake** de metadatos que va de Mix a Master para que el master no re-procese lo que la mezcla ya hizo.

---

## 1. Los dos motores y quién manda

| | Mix Engine | Mastering Engine |
|---|---|---|
| Archivo | `processing/mix_engine.py` (`build_mix`) | `processing/engine.py` (`process_audio`) |
| Entrada | Audio crudo de la sesión | `original` o `mix` (elegible por `source`) |
| Salida | `outputs/{session_id}_mix.wav` (+ versiones) | `outputs/..._master.wav` |
| Análisis | FastAPI separa con Demucs en 4 stems | Opera sobre un único estéreo |
| Decisión de "qué hacer" | `mix_mapper.map_intent_to_mix` | `mapper.map_intent_to_mastering` |
| Guarida de neutralidad | Faders 0 dB → `stem_trims=None` | `params == MasteringParameters()` → fast-path bit-exacto |

El **mapper de intención** es el único lugar que traduce ejes semánticos (warmth, punch, clarity, …) a knobs. El motor **solo sabe cómo**; el mapper decide **qué pidió el usuario**. Un mismo `IntentProfile` alimenta los dos mappers, así una frase del tipo "voz más al frente, más punch" mueve la mezcla y el master de forma coherente.

---

## 2. Contrato "Neutral = bypass"

Regla no negociable del repo (`AGENTS.md`, spec 08): un parámetro neutral debe producir audio **bit-idéntico**. Matices verificados en código:

- **Mastering:** `MasteringParameters()` con todos los defaults ⇒ **fast-path bit-exacto** (`process_audio` escribe los samples leídos tal cual con subtype FLOAT, sin pasar por pedalboard, porque el writer de pedalboard baja a PCM16 y rompería la igualdad).
- **Mix:** el contrato es **0 dB de ganancia con suma 1:1**, no igualdad bit-exacta. La re-suma **no** es idéntica al original porque **Demucs es lossy por naturaleza** (pitfall aceptado y documentado, `mix_engine.py` líneas 41–45). Lo que sí es bit-exacto por etapa:
  - EQ con bandas vacías / ganancias 0 → bypass exacto.
  - Compresor con perfil `None`/vacío/ratio 1:1 → no-op **mismo objeto**.
  - Dimensión sin tempo válido o con perfiles neutrales → no-op mismo objeto.
  - Faders 0 dB y `stem_trims` con todos 0 → `trim_report` ausente.
- **Cada módulo opt-in del master** (multibanda, dyn-EQ, exciter, cinta, comp adaptativo, delay/echo/reverb, de-esser, stereo imaging) tiene default neutral y **aunque esté `enabled=True` no toca la señal si su knob de acción está en cero** (`is_neutral()`).

---

## 3. Flujo de sesión (capa API)

1. **Upload** → sesión en estado `uploaded`.
2. **Análisis** → `analyzing` → `analyzed` (género, LUFS, tempo, `is_already_mastered`…).
3. **Mezcla** → `POST /api/session/{id}/mix` arma el `MixRequest`, llama `build_mix`, guarda `mix_path`, `mix_analysis`, `mix_status`.
   - Estados de mezcla: `none → processing → completed | failed`. **Solo `completed`** permite masterizar desde la mezcla.
4. **Master** → `POST /process?source=original|mix`. El default listo elige `mix` **solo** cuando `mix_status == "completed"` y el archivo existe; si no, usa `original`. Se pasa `mix_metadata` al motor para el handshake adaptativo.
   - Estados de procesamiento: `uploaded → analyzing → processing → completed | error`.
5. **Entrega** → `MasteringReport` con métricas y warnings en español.

> Nota de memoria: las sesiones viven en un dict en memoria + `SessionCache`; se pierden al reiniciar el backend.

---

## 4. Mix Engine — detalle

### 4.1 Pipeline exacto (`build_mix`, orden real de ejecución)

| # | Etapa | Módulo | Qué hace | Neutral |
|---|---|---|---|---|
| 0 | Validación creativa | `creative.py` | `creativity ∈ [0,1]`, `variants ≥ 0`, seed obligatorio | — |
| 1 | **Split** | `splitter.py` (`split_audio`) | Demucs → 4 stems: `drums`, `bass`, `other`, `vocals` | — (Demucs lossy) |
| 2 | Lectura + SR común | `_read_stem_channels`, `_common_sr` | stems a `(canales, samples)`; bus al SR más frecuente (empates → el más alto) | — |
| 3 | Resample | `resample.py` | todos los stems al `target_sr` | — |
| 4 | Presencia | `_stem_rms_db` | RMS ≥ **−50 dBFS** ⇒ stem audible (`stem_presence`) | — |
| 5 | **PAN** | `panorama.py` (`validate_positions`) | roles: vocals/bass/drums → centro, other → dentro de extremos; correcciones con pan law −3 dB; mono check | `pan_profiles={}` ⇒ sin pan |
| 6 | **EQ** | `magic_frequencies.py` (`apply_stem_eq`) | "cortar primero, después realzar" (Owsinski p. 32); perfiles por stem | bandas vacías/0 dB → bit-exacto |
| 7 | **Compresor** | `dynamics.py` (`apply_stem_compression`) | recetas por rol; drums por segmento espectral (LR4 150 Hz/3 kHz); release atado al tempo | perfil `None`/ratio 1:1 → mismo objeto |
| 8 | **Dimensión** | `dimension.py` (`apply_stem_dimension`) | delay a tempo (`60000/BPM`) + reverb Schroeder (4 comb + 2 allpass) con pre-delay (0–40 ms) y return EQ por layering | `{}` o sin tempo → no-op / `no_tempo` |
| 9 | **Énfasis de género** | `emphasis.py` | escala los sends de dimensión y el GR target del bus según `vocal_forward`/`groove_forward` | 0.5/0.5 ⇒ valores base exactos |
| 10 | **Auto-balance (opt-in)** | `stem_balance.py` | LUFS por stem processed; corrige **solo la voz** hacia `groove_level + d·6`, `d∈[−1,1]` | `auto_balance=False` (default) ⇒ sin medición |
| 11 | **Faders manuales (opt-in)** | `_apply_stem_trims` | `{stem}_db` ±6 dB al input del bus, DESPUÉS de la cadena | sin trims ≠ 0 ⇒ sin `trim_report` |
| 12 | **Sum** | `mix_engine` | pad al stem más largo + suma 1:1 en bus estéreo (0 dB, sin normalizar) | — |
| 13 | **Bus compressor** | `dynamics.py` (`apply_bus_compression`) | técnica **Jerry Finn** (attack lento / release rápido), 2–3 dB totales, "breathing" al tempo | perfil base/scaled igual ⇒ misma ruta |
| 14 | **QC** | `quality_checks.py` (`run_qc_checks`) | sobre el **bus final**: mono, fase, sibilancia 5k, muddy 250, honky 500, low-level listen | **flags nunca bloquean** |
| 15 | **Write** | `io_write.py` | `outputs/{session_id}_mix.wav` a 24-bit | — |
| 16 | **Versiones** | `render_versions.py` | 5 WAVs desde los mismos stems processed, re-suma y **mismo** bus comp | `with_versions=False` ⇒ se omiten |
| 17 | **Modo creativo** | `creative.py` | N variantes dentro del envelope estándar, re-ruteadas desde los stems crudos, rejection sampling contra pan/QC | `creativity=0` ⇒ bit-idéntico al principal |
| 18 | **Análisis final** | `analysis/analyzer.py` | LUFS/DR/centroid por stem + tempo/género del mix | — |
| 19 | **Handshake** | `_compute_mix_metadata` | arma `MixMetadata` y lo adjunta a `mix_metadata` | — |

### 4.2 El orden importa

- La cadena por stem es **`pan → EQ → compresor → dimensión(sends)`** (cadena DAW: fader → pan → EQ → comp → sends). El compressor va **entre** el EQ y los sends para que la dimensión reciba material ya controlado.
- **La PAN se aplica antes del EQ** sobre el stem remuestreado (se mide la posición M/S antes de corregir).
- **El bus comprime DESPUÉS de la suma** de stems, no por stem.
- Los faders (auto-balance T3 y manual T5) aterrizan **al input del bus**, luego de toda la cadena del stem — el lugar real de "fader board".
- Las **versiones** re-suman los stems ya procesados y **vuelven a pasar por el mismo bus compressor**: el 2-bus reacciona al movimiento del fader, como en un DAW.

### 4.3 Reportes del payload

`build_result` incluye (según lo que esté activo): `mix_path`, `sample_rate`, `duration_seconds`, `analysis`, `stem_presence`, `tempo_bpm`, `genre`, `genre_confidence`, `eq_profiles_applied`, `qc_report`, y opcionalmente `versions`, `pan_report`, `dimension_report`, `compressor_report`, `emphasis_report`, `creative_report`, `balance_report`, `trim_report`, `mix_metadata`.

Claves **ausentes** cuando la etapa se neutraliza (no hay claves vacías): `dimension_report` si `dimension_profiles={}`, `compressor_report` si `compressor_profiles={}`, `emphasis_report` si `emphasis_profiles={}`, etc. Esto mantiene la forma del payload del paso anterior.

#### QC (Paso 07) — 5 chequeos informativos

Cada check devuelve `{"ok": bool, "details": {...}}` y el reporte agrega `summary` (`all_ok` / `flagged`) más la nota "los flags nunca bloquean". Reutiliza internals de `panorama`:

- **mono** — `panorama.mono_compat_loss_db`, umbral `MONO_COMPAT_MIN_DB = −3 dB`.
- **phase** — correlación L↔R vía `panorama.measure_stereo_position`, piso `CORRELATION_SAFETY_FLOOR = −0.1`.
- **sibilance_5k** (4–7 kHz), **muddy_250** (200–300 Hz), **honky_500** (450–600 Hz), **low_level_listen** (proxy perceptual).

#### Versiones (Paso 07)

`render_versions.VERSION_TRIMS_DB`: `principal` (0.0 dB), `vocal_up` / `vocal_down` (±0.75 dB solo voz), `instrumental` y `tv_mix` (silencian la voz). El principal es byte-idéntico con o sin versiones.

#### Modo creativo (Paso 08)

- Espacio **continuo/aleatorio acotado**, no presets finitos: gaussiana centrada en el estándar con `sigma = creativity × (max − min)/2`, clampeada al envelope.
- `creativity=0` ⇒ cada variante reproduce el routing base (principal bit-idéntico).
- Rejection sampling contra la validación posicional (Paso 03) y el QC (Paso 07); `MAX_CREATIVE_ATTEMPTS` por variante; el lote nunca bloquea. `creative_manual=True` marca `non_standard` en vez de rechazar.
- Archivos: `outputs/{session_id}_mix_creative_{i}.wav`.

### 4.4 Handshake Mix → Master (`_compute_mix_metadata`)

Calcula, desde el **bus final**:

- `side_energy_ratio = RMS(Side) / RMS(Mid)` (encode M/S).
- `applied_spatial_width`: base 1.0 + `0.2 × avg_reverb_mix` (si dimensión activa) + `0.15 × avg_dim_send` (si énfasis activo) + ajuste legacy + 0.2 si stereo imaging; clip a `[1.0, 2.5]`.
- `stem_lufs`: LUFS integrado por stem.
- `transient_headroom_db = limiter_ceiling(−1.0) − true_peak_del_bus`.
- `mix_status = "completed"`.

Contrato `MixMetadata` (`models/mix_metadata.py`): `schema_version=1`, `extra="allow"` para extensibilidad.

---

## 5. Mastering Engine — detalle

### 5.1 Modos de procesamiento

| Modo | Cuándo | Qué corre |
|---|---|---|
| **Transparent delivery** | `processing_mode == "transparent"` | Solo delivery: SRC opcional, loudness+limiter si hay `target_lufs_db`, dither a 16-bit. **Cero tone shaping**, sin target automático |
| **Neutral fast-path** | `params.model_dump() == MasteringParameters().model_dump()` | Escribe los samples leídos tal cual (subtype FLOAT), mide y retorna. Bit-exacto |
| **Master** | Cualquier otro caso | Cadena completa adaptativa |

### 5.2 Pipeline exacto (`process_audio`, orden real)

| # | Etapa | Detalle / módulo | Neutralidad |
|---|---|---|---|
| 0 | Lectura | `AudioFile` de pedalboard | — |
| 1 | **Input QC** | `_run_input_qc`: hard-clip count + true peak; `strict_mode` ⇒ `InputQcError` → HTTP 422 | — |
| 2 | `am_factor` | `0.8` si `is_already_mastered` (score ≥ 0.8), si no `1.0` | — |
| 3 | **SRC** | `resample_audio` a `output_sr` (VHQ) si difiere | — |
| 4 | **Neutral fast-path** | escritura FLOAT + métricas | bit-exacto |
| 5 | **Gain staging** | `gain_stage` a pico **−6 dBFS** | — |
| 6 | **Smart gate** | `decide_smart_gate` → `intensity_scales` por módulo (0.3–1.0). **Advisory, nunca bloquea a 0.0** y nunca toca etapas críticas (HPF, espacial, mono-compat, loudness, soft-clip, limiter, dither) | inactivo ⇒ full strength |
| 7 | **De-esser dinámico** | `deesser.py`, 3–8 kHz, ANTES de la cadena tonal | `enabled=False` o `amount 0` ⇒ bit-exacto |
| 8 | **Board (pedalboard)**: | | |
| 8a | HPF correctivo | `HighpassFilter(30 Hz)` fijo | — |
| 8b | **Match EQ** | `build_match_eq` contra perfil de género, escala `intensity_multiplier × match_eq_intensity` | escala ≤ 0.05 ⇒ salta |
| 8c | **EQ de carácter** | `build_character_eq(params.eq_bands)`, escala por `am_factor`. **Nunca gated** (es la identidad del preset) | `eq_bands=[]` ⇒ sin plugins |
| 8d | Claridad (8 kHz) | `PeakFilter(8000 Hz, gain = clarity_brightness_db × clarity_intensity, Q 0.6)` | gain 0 ⇒ no se agrega |
| 8e | Calidez (10 kHz) | `PeakFilter(10000 Hz, gain = saturation_warmth_db × warmth_intensity, Q 0.5)` | gain 0 ⇒ no se agrega |
| 8f | **Compresión** | Fija: `Compressor(threshold = −16 − 1.5·transient_boost, ratio = compression_ratio × comp_intensity, attack = max(3, 20 − 3·transient_boost), release 200)` | o comp adaptativo si `adaptive_comp_enabled` |
| 9 | `board(audio, sr)` | ejecuta EQ + compresión | — |
| 10 | **Comp adaptativo** | `adaptive_compress` si `adaptive_comp_enabled` y ratio ≠ 1 | ratio 1.0 ⇒ bit-exacto |
| 11 | **Multibanda** | `multiband_compress` (LR4 150 Hz/3 kHz) | ratio 1:1 ⇒ bit-exacto |
| 12 | **Dyn-EQ** | `dynamic_eq` (cortes, 400 Hz / 2.5 kHz / 8 kHz) | ratio 1.0 ⇒ bit-exacto |
| 13 | **Exciter** | `excite` (4 bandas Ozone) + `_match_peak` | amount 0 ⇒ bit-exacto |
| 14 | **Adaptación Mix→Master** | `_adapt_spatial_for_mix_context` si llega `mix_metadata` | sin metadata ⇒ intacto |
| 15 | **Espacial (bloque legacy)** | si `clarity_wet>0` o ancho ≠ 1 o Haas>0 o side HPF: M/S encode → reverb en Side → Haas → side HPF → ancho broadband (`mid·2/(1+w)`, `side·w`) → decode → chequeo de correlación (si `corr<0` ⇒ `safety_enforce_correlation`) | condición falsa ⇒ salta el bloque |
| 16 | **Stereo Shuffler 3 bandas** | `apply_frequency_dependent_width` (LR4 phase-zero) si `enabled` | `False` ⇒ salta |
| 17 | **Stereo imaging per-band** | `apply_stereo_imaging` si `enabled` y no neutral; marca `stereo_imaging_mono_applied` | widths 1.0 / mono 0 ⇒ bit-exacto |
| 18 | **Time FX** | delay → echo → reverb (cada uno si `enabled` y no neutral) | mix 0.0 ⇒ bit-exacto |
| 19 | **Cinta/Saturación** | si `tape_enabled` y no neutral → `tape_saturate` + `_match_peak`; si no, `_apply_saturation` tanh con `sat_drive = saturation_drive_db × intensity_multiplier × sat_intensity` | drive 0 / neutral ⇒ sin efecto |
| 20 | **Mono-compat** | `enforce_mono_compatibility(120 Hz)` salvo si `stereo_imaging_mono_applied` | — |
| 21 | **Loudness target** | `target_lufs`; explícito o automático `clip(−14 + (1 − ceiling/−0.3)·6, −14, −12)` | — |
| 22 | **Codec pre-matching** | `calculate_crest_factor` → `compute_codec_safe_ceiling` | — |
| 23 | **Soft-clipper** | `soft_clip(threshold = safe_ceiling − 1.5 dB)`, 16× oversampling, knee erf | bajo threshold ⇒ bit-exacto |
| 24 | **True-peak limiter** | `true_peak_limit(ceiling = safe_ceiling)`, 8× oversampling, lookahead | — |
| 25 | Seguridad | si `max > 1.0` ⇒ `/max · 0.99` | — |
| 26 | **Dither** | 16-bit ⇒ Lipshitz 2do orden; 24-bit ⇒ sin shaping | — |
| 27 | DR validation | `measure_dynamic_range` entrada vs salida → `dr_ratio` | — |
| 28 | **Write** | `write_output` (PCM explícito, honra bit depth) | — |
| 29 | Métricas finales | true peak, LUFS, LRA, correlación | — |

### 5.3 Reglas de orden críticas

- **De-esser ANTES del brillo** (8 kHz): el shelf enfatiza material ya de-essed en vez de re-calentar la aspereza, y los compresores no bombean con drive sibilante.
- **El soft-clipper va ANTES del true-peak limiter**, para que el limiter sostenga el cuerpo en vez de atrapar cada pico (estilo "modern loudness").
- **Time FX antes de cinta**: los ecos alimentan el modelo de cinta real (insert clásico "tape echo").
- **Mono-compat de 120 Hz** se saltea si el stereo imaging per-band ya colapsó los graves (no es idempotente).
- **La saturación y el exciter** re-matchean el pico (`_match_peak`) para no empujar más duro al limiter.

### 5.4 Handshake adaptativo (`_adapt_spatial_for_mix_context`)

Con `mix_metadata` presente (source = mix), ajusta una copia de los params:

- `applied_spatial_width > 1.2` ⇒ baja `stereo_width` (hasta `excess × 0.5`).
- `applied_spatial_width > 1.15` y `stereo_imaging_enabled` ⇒ recorta anchos high/mid.
- `side_energy_ratio > 0.35` ⇒ enciende side HPF (≤ 150 Hz).
- `transient_headroom_db < 1.0` ⇒ `limiter_ceiling_db ≤ −1.5`.

**Punto a revisar:** este bloque escribe `adapted.stereo_imaging_width_high` / `_mid`, pero los campos reales del modelo son `stereo_imaging_high_width` / `stereo_imaging_mid_width` (`models/audio.py`). Con pydantic v2 eso puede levantar error al asignar un campo inexistente. Se dispara solo con `applied_spatial_width > 1.15` **y** `stereo_imaging_enabled`. Conviene verificarlo contra la versión de pydantic usada.

---

## 6. Mappers de intención

### 6.1 Ejes semánticos (`models/intent_profile.py`)

8 ejes en `[0,1]`, **0.5 = neutral**; validación **estricta** (`extra="forbid"`, fuera de rango se rechaza, no se clampa). Contexto no-eje: `target_platform`, `reference_genre`, `notes`. `IntentProfile.neutral()` pone todo en 0.5.

### 6.2 Mix mapper (`mix_mapper.py`)

`MixSettings`: `dimension_enabled=True` (por defecto el motor SÍ corre la dimensión), `auto_balance=False`, `stem_trims`.

| Eje | Destino | Anclas |
|---|---|---|
| `punch` | fader `drums_db` | −3 dB @0.0, 0 @0.5, +3 @1.0 |
| `bass_weight` | fader `bass_db` | −3 / 0 / +3 dB |
| (voz) | `vocals_db` fijo | 0 dB (la Vocal Chain se retiró) |

Solo se emiten faders ≠ 0; si todos son 0 dB, `stem_trims=None`. **Ojo:** la neutralidad acá es solo del fader — la dimensión por defecto sigue corriendo, así que el mix no hereda la transparencia bit-exacta del master.

### 6.3 Master mapper (`mapper.py`)

Todos los anclajes pisan exactamente el default del parámetro en 0.5 ⇒ neutral = `MasteringParameters()`. Umbrales de enganche con `>` estricto: `_TAPE_ENGAGE=0.55` (warmth/vintage), `_MULTIBAND_ENGAGE=0.55` (bass_weight), `_EXCITER_ENGAGE=0.6` (brightness), `_DYN_EQ_ENGAGE=0.6` (clarity).

| Eje | Parámetro(s) | Ancla(s) |
|---|---|---|
| warmth | `saturation_warmth_db` | −3 @0, 0 @0.5, +3 @1 |
| warmth | `tape_drive_db` | 0 @0.5, +2 @1 |
| vintage | `tape_hysteresis` / `tape_bias` / `tape_rolloff_amount` | 0 @0.5 → 0.4 / 0.05 / 0.4 @1 |
| vintage+warmth | `tape_enabled` + escalado de drive | ambos >0.55 ⇒ drive warmth × `(1 − 0.5·vintage_intensity)` |
| punch | `transient_boost_db` | 0 @0.5, +3 @1 |
| punch | `adaptive_comp_ratio` / `_attack_ms` | 1.0 @0.5→3.0 @1 / 30 @0→10 @0.5→5 @1 |
| clarity | `clarity_wet` | 0 @0, 0.15 @0.5, 0.30 @1 |
| clarity | `dyn_eq_enabled` + banda 2 (2.5 kHz) | ratio 1.0 @0.5 → 2.0 @1 |
| brightness | `clarity_brightness_db` | −2 @0, +1 @0.5, +3 @1 |
| brightness | exciter banda 4 (air) | activo > 0.6, amount 0→0.3 |
| width | `stereo_width` | 0.7 @0, 1.0 @0.5, 1.6 @1 |
| bass_weight | `multiband_enabled` + low threshold/ratio + `stereo_imaging_mono_below_hz` | −20→−30 dB / 1.0→2.5 / 0→150 Hz |
| loudness | `limiter_ceiling_db` | −2.5 @0, −1.0 @0.5, −0.3 @1 |
| loudness | `target_lufs_db` | `None` ≤0.5; rampa −14 → **−12** LUFS por encima de 0.5 |

Notas del mapper:

- `punch` mapea `adaptive_comp_ratio/_attack` **pero deja `adaptive_comp_enabled=False` a propósito**: encender el módulo reemplazaría el compresor fijo para todo valor no neutral y cambiaría el carácter del pipeline.
- El cap de loudness es **−12 LUFS** (más caliente que eso las plataformas lo atenúan llevando sobre-compresión).
- El tope de loudness por plataforma (`_apply_platform_defaults`): spotify/tidal/youtube −14 LUFS / −1.0 dBTP, apple_music −16 / −1.0.

---

## 7. Parámetros clave y sus defaults (`MasteringParameters`)

| Grupo | Campo | Default | Rango |
|---|---|---|---|
| Claridad | `clarity_wet` | 0.15 | 0–1 |
| Claridad | `clarity_brightness_db` | 1.0 | −6…6 |
| Fuego | `compression_ratio` | 2.0 | 1–10 |
| Fuego | `limiter_ceiling_db` | −1.0 | −3…0 |
| Fuego | `transient_boost_db` | 0.0 | 0–6 |
| Cinta | `saturation_drive_db` | 0.0 | 0–10 |
| Cinta | `saturation_warmth_db` | 0.0 | −6…6 |
| Espacial | `stereo_width` | 1.0 | 0.5–2.0 |
| Espacial | `haas_delay_ms` | 0.0 | 0–40 |
| Imaging | `stereo_imaging_enabled` | False | — |
| Imaging | `stereo_imaging_*_width` | 1.0 | 0–2 |
| Imaging | `stereo_imaging_mono_below_hz` | 0.0 | 0–400 |
| Side HPF | `side_hpf_enabled` / `side_hpf_hz` | False / 100 | 20–400 |
| Multibanda | `multiband_enabled` | False | — |
| Multibanda | crossovers | 150 / 3000 Hz | — |
| Multibanda | `multiband_*_ratio` | 1.0 | 1–10 |
| Dyn-EQ | `dyn_eq_enabled` | False | — |
| Dyn-EQ | bandas | 400 / 2500 / 8000 Hz, Q 4.0 | — |
| Dyn-EQ | `dyn_eq_band*_ratio` | 1.0 | 1–10 |
| Exciter | `exciter_enabled` | False | — |
| Exciter | bandas | bass 100 Hz even, tube 200 Hz even, tape 200 Hz odd, air 800 Hz odd | — |
| Exciter | `exciter_band*_amount` | 0.0 | 0–1 |
| Cinta real | `tape_enabled` | False | — |
| Cinta real | `tape_drive_db`/`hysteresis`/`bias`/`rolloff` | 0 / 0 / 0 / 0 | bias ≤ 0.2 |
| Comp adapt. | `adaptive_comp_enabled`/`ratio` | False / 1.0 | 1–12 |
| Time FX | `delay/echo/reverb_enabled` | False | — |
| Time FX | `*_mix` | 0.0 | 0–1 |
| Shuffler | `stereo_shuffler_enabled` | False | — |
| Shuffler | widths low/mid/high | 0.0 / 1.0 / 1.3 | — |
| Delivery | `processing_mode` | "master" | master/transparent |
| Delivery | `platform_target` | None | spotify/apple_music/youtube/tidal/custom |
| Delivery | `target_lufs_db` | None | −24…0 |
| Delivery | `strict_mode` | False | — |
| Salida | `output_bit_depth` | 24 | 16–32 |

---

## 8. Módulos DSP - fórmulas verificadas

- **Multibanda** (`multiband.py`): crossovers LR4 en 150 Hz / 3 kHz; envelope detector de un polo con attack/release; detector **conjunto (L+R)/2**; gain computer con soft knee `G = T + (x − T)/ratio`; makeup automático por banda.
- **Dyn-EQ** (`dyn_eq.py`): filtros bell de Q fijo, **solo cortes** `G(t) = min(0, −(E(t) − T)·(1 − 1/R))`; reutiliza `multiband.detect_envelope`; biquad RBJ constant 0 dB peak gain.
- **Exciter** (`exciter.py`): camino paralelo; even = rectificador de onda completa (H2 ≈ 0.42), odd = tanh; `(1−blend)·even + blend·odd`; high-pass de orden 4 sobre el contenido excitado.
- **Cinta** (`tape.py`): recursión de histéresis `y[n] = tanh(drive·x[n] + bias + k·y[n−1]·(1 − |y[n−1]|))`, acotada a ±1; `hysteresis == 0` ⇒ soft-clip plano; `bias ≤ 0.2`.
- **De-esser** (`deesser.py`): dinámico 3–8 kHz; `ratio_db = band_env_db − total_env_db`; envelope 15 ms/150 ms; gates `band_db > −55 dBFS` y spike sobre rolling reference 500 ms.
- **Soft-clipper** (`clipper.py`): 16× oversampling; knee erf `y(r) = thr + (1 − thr)·erf(a(r − thr)/(1 − thr))`, `a = sqrt(π)/2`; bit-idéntico bajo el threshold.
- **True-peak limiter** (`truepeak.py`): 8× oversampling (`TP_OVERSAMPLE`), lookahead 4 ms, 2 etapas + hard clipper.
- **Loudness** (`loudness.py`): BS.1770-4, bloques 400 ms con 75 % de solape, gate −70 LKFS, offset −0.691, K-weighting.
- **Smart gate** (`smart_gate.py`): tolerancias `COMMERCIAL_LUFS_TOLERANCE_DB=0.8`, `COMMERCIAL_CREST_MINIMUM_DB=4.5`, `COMMERCIAL_TRUE_PEAK_MARGIN_DB=0.3`; escalas `SCALE_FLOOR=0.3`, `CORRECTIVE_SCALE=0.4`, `SIGNATURE_SCALE_FLOOR=0.7`; bypass por env `SMART_GATE_BYPASS=true`.
- **Stereo imaging** (`stereo_imaging.py`): constant-power `mid' = mid·sqrt(2/(1+w))`, `side' = side·sqrt(2w/(1+w))`; `SAFETY_SIDE_GAIN=0.7`; `mono_below_hz`.
- **Espacial** (`spatial.py`): encode M/S, `SIDE_HPF_DEFAULT_HZ=100.0`.
- **Dimensión** (`dimension.py`): delay `60000/BPM`; reverb Schroeder (4 comb + 2 allpass); pre-delay (0, 40) ms; layering "longest = brighter"; guard `no_tempo`.
- **Panorama** (`panorama.py`): pan law −3 dB; `CORRELATION_SAFETY_FLOOR = −0.1`; corrección máx 6 dB.
- **Dinámica** (`dynamics.py`): vocals 4:1 (4–6 dB GR), bass ~∞:1 implementado como ratio ≥ 20:1 (3–4 dB GR), other 9:1, bus 2–3 dB GR (Jerry Finn).

---

## 9. Deuda técnica / gotchas detectados

Estos no cambian el "cómo procesa" pero conviene tenerlos a mano:

1. **`engine.py` cabecera (líneas 1–18)** define helpers antes del docstring del módulo: `_match_peak`, `measure_correlation(*args) → 0.0` (**stub**, siempre devuelve 0.0 — el motor usa `spatial.measure_stereo_correlation` para medir), `measure_lufs = integrated_loudness`, `calculate_crest_factor`. El `_match_peak` real usado por las etapas es el de la cabecera.
2. **`generate_report`** (líneas 1573–1613): después del `return report` hay un bloque de código muerto (un docstring huérfano + cuerpo de un `_match_peak` viejo), inalcanzable.
3. **`validation_loop` / `_adjust_trim` / `_adjust_ceiling` / `_clamp_trim`** (FASE 3) llaman `process_audio(input_path=None, ...)` y referencian globales `target_lufs`/`target_dbtp` inexistentes: es andamiaje legacy de una fase anterior, **no** está cableado al path de la API. El loop de validación real vive en la capa de validación/reporte, no acá.
4. **`_adapt_spatial_for_mix_context`** escribe campos inexistentes (`stereo_imaging_width_high` / `_mid`) — ver §5.4.
5. **Demucs es lossy**: la mezcla re-suman nunca es bit-exacta al original; el contrato neutral del mix es de ganancia, no de muestras.

---

## 10. Verificación

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

Backend: `pyproject` con `ruff` + `mypy strict` (`apps/audiomind/pyproject.toml`). WAV/MP3 de prueba a `uploads/`/`outputs/` (gitignored) o generados con `apps/audiomind/scripts/generate_samples.py` y `e2e/fixtures/generate_fixture.py`.

---

## 11. Referencias de código

| Área | Archivo |
|---|---|
| Mezcla (pipeline) | `processing/mix_engine.py` |
| Master (pipeline) | `processing/engine.py` |
| Intención → mix | `processing/mix_mapper.py` |
| Intención → master | `processing/mapper.py` |
| Modelos de parámetros | `models/audio.py`, `models/intent_profile.py`, `models/mix_metadata.py` |
| Dinámica | `processing/dynamics.py`, `processing/adaptive_comp.py`, `processing/multiband.py`, `processing/dyn_eq.py` |
| Tono | `processing/magic_frequencies.py`, `processing/exciter.py`, `processing/tape.py` |
| Espacial | `processing/spatial.py`, `processing/stereo_imaging.py`, `processing/panorama.py` |
| Dimensión / tiempo | `processing/dimension.py`, `processing/delay.py`, `processing/echo.py`, `processing/reverb.py` |
| Loudness / entrega | `processing/loudness.py`, `processing/truepeak.py`, `processing/clipper.py`, `processing/dither.py`, `processing/mono.py`, `processing/smart_gate.py` |
| Mezcla: QC / versiones / creativo | `processing/quality_checks.py`, `processing/render_versions.py`, `processing/creative.py`, `processing/stem_balance.py` |
| Presets / API | `processing/presets.py`, `api/mix.py`, `api/mastering.py` |

---

## 12. Arquitectura multi-tenant — la migración estilo Moises

Todo lo de arriba (§1–§11) describe el **motor**. Esta sección y la siguiente describen el **producto alrededor del motor**: cómo el proyecto deja de ser una sesión anónima en memoria y pasa a ser un documento por usuario con historial, intención y estado vivo.

**Rama:** `feature/moises-architecture-migration`. **Referencia:** `docs/reference/specs/project_document_v1_spec.md`.

### 12.1 El problema que resuelve

El backend original era **anónimo y por sesión**: el audio se identificaba por un `session_id` en memoria, las mezclas no persistían y los stems vivían en el disco efímero del contenedor. Al reiniciar, todo se perdía. La migración convierte eso en un **modelo de documento por usuario**, donde cada proyecto tiene identidad, assets durables y un estado de mezcla que sobrevive al reload.

### 12.2 Las tablas (migraciones Supabase)

Dos migraciones introducen el modelo (`supabase/migrations/`):

| Tabla | Migración | Qué guarda |
|---|---|---|
| `projects` | `20261008120000_create_project_document.sql` | Raíz del documento: `name`, `bpm`, `musical_key`. Una fila por proyecto de usuario. |
| `audio_assets` | ídem | Todo archivo del proyecto: original, cada stem separado, cada master. Llave determinística en R2 + `media_hash` opcional. |
| `project_states` | ídem | El **mix vivo** como JSONB: faders, toggles, `undo_stack`. Lo escribe el autosave del frontend. |
| `project_documents` | `20261008140000_create_project_documents.sql` | El cuarto pilar: **intención + estructura**. `structure` (identidad de los 4 stems), `mix_intent` (propuestas de IA), `master_intent` (preset/plataforma/format/overlay). |

Detalles deliberados de la migración:

- **`dsp_jobs` NO se toca.** La separación asíncrona reusa la tabla de jobs existente y guarda su contexto (`user_id`, `project_id`, `media_hash`, `asset_id`) en el JSONB `meta` que ya tenía. Una sola tabla de jobs, un solo vocabulario.
- **RLS real** (`auth.uid() = user_id`): a diferencia de `dsp_jobs`/`sessions` (solo backend, `service_role`, sin políticas), estas tablas las lee y escribe **también** el cliente Studio autenticado. El backend sigue escribiendo con `service_role` para el trabajo de fondo.
- **Idempotentes**: todo está guardado con `if not exists` / drop-then-create, porque el dashboard es la vía de deploy y un doble pegado debe ser no-op.

### 12.3 Invariantes de ownership — la regla que elimina el split-brain

La regla no es un merge: es **no-overlap**. Cada dato vive en una sola casa con un solo escritor, así que no hay precedencia que definir.

| Dato | Casa | Único escritor | ¿Llega al DSP? |
|---|---|---|---|
| Faders (`stem_trims`), toggles (`dimension_enabled`, `auto_balance`), `undo_stack` | `project_states.state` | Solo el store del frontend (autosave) | Sí |
| Identidad/presentación de los stems (`display_name`, `order`, `group_id`, `color`) | `project_documents.structure` | CRUD de estructura (usuario) | Validación de claves |
| Propuestas de la IA (faders/toggles/master) | `project_documents.mix_intent.proposals` | Intelligence | **No, hasta que se apliquen** |
| Intención de master (`preset_id`, `platform_target`, `format`, `output_bit_depth`, `parameters`) | `project_documents.master_intent` | Usuario + Intelligence | Sí |
| Metadata (`name`, `bpm`, `musical_key`) | `projects` | Análisis / usuario | No |

Tres invariantes sostienen esto:

- **I1 — Un solo escritor en `project_states`:** solo el store del frontend vía autosave. Ni la IA ni el compiler escriben esa tabla; si un segundo escritor la mutara, el `undo_stack` (que vive en la misma fila) se rompería.
- **I2 — El compiler es una función pura:** lee ambas tablas, no escribe ninguna.
- **I3 — El DSP no tiene tabla de knobs persistente:** los parámetros viajan en el request de cada job. Lo durable es `dsp_jobs` (meta/resultado). "Actualizar el DSP" = producir el plan para esa corrida.

### 12.4 El compiler — función pura (`services/compile_project.py`)

`compile(document, state) → MixPlan`. Sin I/O de escritura: `load_inputs()` solo hace `SELECT` (404/403 si no hay ownership), y `compile()` es puro.

- **`StateProjection`**: lo mínimo que exige de `project_states.state`, con defaults neutrales (4 faders en `0.0`, `dimension_enabled=True`, `auto_balance=False`). Un `state` ausente, malformado o hostil no rompe el compile.
- **`MixPlan`**: el contrato que se proyecta a los dos motores.

| `MixPlan` | Destino | Nota |
|---|---|---|
| `stem_trims` | `build_mix(stem_trims=...)` | Claves `{stem}_db`, rango ±6 dB. `None` si los 4 faders son `0.0` ⇒ routing neutral |
| `dimension_enabled=True` | `dimension_profiles=None` | Perfiles por defecto |
| `dimension_enabled=False` | `dimension_profiles={}` | Dimensión off |
| `auto_balance` | `build_mix(auto_balance=...)` | Default `False` |
| `preset_id`, `platform_target`, `format`, `output_bit_depth`, `master_name` | `MasterJobPayload` top-level | `platform_target` usa el **set de 7** del payload, no el de 5 de `MasteringParameters` |
| `parameters` | `MasterJobPayload.parameters` | Overlay parcial de `MasteringParameters`, validado por Pydantic en el submit |

### 12.5 Coexistencia de endpoints

| Endpoint | Quién compila | Estado |
|---|---|---|
| `POST /mix` (sesión, params explícitos) | Cliente | **Se mantiene** — path anónimo |
| `POST /jobs/master` (payload explícito) | Cliente | **Se mantiene** |
| `POST /projects/{id}/jobs/mix` | Server (`compile_project`) | Nuevo — **placeholder** (`api/projects.py:836-855`): compila/encola pendiente |
| `POST /projects/{id}/jobs/master` | Server (`compile_project`) | Nuevo — **placeholder** (`api/projects.py:857-875`): ídem |

El compiler es un **módulo compartido**, no un reemplazo.

### 12.6 Estado real (mapeo por commits de la rama)

Los commits agrupan el trabajo en *work units*:

| WU | Qué se hizo | Commit(s) |
|---|---|---|
| WU1 | Backend multi-tenant: schema `projects`/`audio_assets`/`project_states`, auth JWT, CRUD (`api/projects.py`, `api/auth.py`) | `4ddd4a3` |
| WU2 | Separación de stems asíncrona e **idempotente por `media_hash`** (`services/separate_jobs.py`) | `6dc6732` |
| WU3 | Studio: stores de estado de mezcla y documento + motor multi-stem (`features/projects/store/*`) | `e67d885` |
| WU4 | Tabla `project_documents` + CRUD del documento V1 con **OCC** (concurrencia optimista) | `258678c`, `9008717` |
| WU5 | Módulo `compile_project` (compiler ✅, 6 tests) + endpoints de jobs **placeholder** | `822162e`, `0df2e22`, `8d81a26` |
| fixes | Imports de endpoints + llaves `{stem}_db`; lint gate del Studio | `33dd720`, `c16e5b1` |

**Honestidad de estado:** `compile()` está implementado y testeado; **`load_inputs()` todavía devuelve defaults y no está cableado a Supabase** (el propio docstring del módulo lo declara: "En producción esta función usaría el cliente Supabase token-scoped; aquí devolvemos un documento de ejemplo para que el módulo sea importable"). Los endpoints `POST /projects/{id}/jobs/{mix,master}` son **placeholders** (`api/projects.py:836-875`): devuelven un `job_id` sintético sin compilar ni encolar. Las dos migraciones existen como archivos; su aplicación en la base es una operación de deploy, no verificable desde el repo (la de `dsp_jobs` se aplicó el 02-Oct, según `docs/ESTADO_PROYECTO.md` §17).

---

## 13. Cómo se maneja la IA — camino a la calidad de Moises Studio

**Referencia:** `docs/evidence/reports/REPORT_IA_WAVEAI.md` (conciliación investigativa contra el Moises Studio real) y `intelligence/README.md`.

### 13.1 Las capas de IA del proyecto

| Capa | Dónde | Rol | Estado |
|---|---|---|---|
| **Intérprete de intención** | `apps/agent/` | Chat → `IntentProfile` (8 ejes `[0,1]`) | Compila; llamada real a Gemini **no probada** (sin credenciales) |
| **Mappers** | `processing/mix_mapper.py`, `processing/mapper.py` | `IntentProfile` → parámetros DSP (§6) | Implementados; falta el wiring en la API (IA-03) |
| **Knowledge Core** | `intelligence/` | Fuente de verdad estructurada (schemas Pydantic + Markdown versionado) | Fase 1 hecha (estructura, schemas, templates, 9 dominios) |
| **RAG sobre libros** | `intelligence/rag/` | Evidencia citada de manuales de mezcla | Híbrido BM25 + vectores, funcional en solo-BM25 |
| **Memoria** | `intelligence/memory/` | STM/LTM/Semantic/Procedural/Research/Business | Documentada; implementación futura (Fase 5) |

Principio rector del Knowledge Core: **nunca toca audio**. El DSP nunca escribe conocimiento directamente; la comunicación ocurre a través de agentes que leen conocimiento para decidir y escriben experimentos para registrar resultados.

### 13.2 Intérprete de intención (`apps/agent/`)

`interpretIntent({ historial, perfil, análisis })` es una **función pura**. Modelo `gemini-3.7-flash` con `MODEL_CHAIN` de fallback. Garantías:

- **`needs_clarification` no mueve el perfil** — devuelve el perfil de entrada intacto (evita que el modelo pregunte y ajuste en el mismo turno).
- Fuera de rango se **rechaza** (no se clampa); se rechazan claves desconocidas (`extra="forbid"`).
- `effort: low` por defecto; system prompt estable con `cache_control`.
- Ruta en el Studio: `app/voz/chat/route.ts` → `interpretIntent`. También hay transcripción de voz (`app/voz/escuchar/route.ts`).

**Pendiente:** `IA-08` — probarlo con una `GEMINI_API_KEY` real (nunca se ejecutó la llamada).

### 13.3 RAG sobre libros (`intelligence/rag/`)

Corpus extraído de manuales (Owsinski 1ª ed. EN, Owsinski 5ª ed. ES, Gibson, Roads) → ~2.414 páginas / 1.806 fragmentos con capítulo + página.

- **Recuperación híbrida:** BM25 + vectores fusionados con **RRF**; funciona en modo solo-BM25 si Ollama no está.
- **Embeddings:** `ollama` + `bge-m3` (multilingüe, local).
- **Chunking:** ~320 palabras, solapamiento, sin cruzar capítulos.
- **Citas obligatorias** (`Owsinski, p.xx`) con fragmentos breves/parafraseados.
- **Exclusión estricta:** PDFs, texto extraído, fragmentos y embeddings **NUNCA** van al repo. Solo código, catálogo de metadatos y `eval_questions.json`.

**Estado medido:** solo-BM25 = **5/15 hit@5, MRR 0.30** (esperable: preguntas ES contra libro EN). Objetivo: **> 10/15** con `bge-m3` activo (bloqueado por red, tarea IA-01).

### 13.4 El modelo mental de Moises que hay que portar

El valor de la conciliación no son solo los números, es el **método**:

> **Moises no "suena bonito". Moises mide, calcula, mueve UN parámetro, vuelve a medir y se detiene cuando converge.**

Reglas estructurales que difieren del enfoque "chat-first":

1. **Undo a nivel de proyecto, no de chat.** Pista + máster = **2 pasos**, no 10. Volver atrás es un clic. El transporte (playhead/loop/metrónomo) es estado de sesión, fuera del undo.
2. **Los resultados viven en el proyecto.** Tempo/tonalidad/acordes/secciones se escriben como marcadores + mapa de tempo. Renders y stems terminan como pistas y clips con nombre y posición, nunca como enlaces al chat.
3. **Separar a stems es el ÚNICO camino para cambiar BALANCE.** Con un bounce estéreo, EQ/comp/saturación solo cambian **COLOR**, no balance. Tratar un bounce como si tuviera balance separable es el error conceptual a evitar.
4. **Los números mandan.** True peak → techo; LUFS integrado → sonoridad; crest + LRA → demuestran que no se aplastó.
5. **Techo UNA sola vez**, únicamente en el **Stereo Out** (sin limitador en pista): dos limitadores en serie recortan dinámica dos veces.
6. **Orden Correcto: Corregir → Comprimir → Colorear** (EQ primero, saturación al final del bus con compensación, reverb/delay por envío a bus).
7. **Bucle de corrección:** Medir → Calcular → **mover 1 parámetro** → Medir. Máx **4 medidas**; **1 corrección por pasada**; parar cuando **converge**, no cuando "suena bien".
8. **Guardrail dinámico:** si el **crest factor baja > 4 dB** respecto a la entrada → **revertir**. Preservar dinámica es parte del objetivo de máster.
9. **Sin espectro → sin EQ quirúrgico.** Fuera del HPF del máster, ninguna banda se justifica sin medición.
10. **"Efecto con script":** la IA no expone un editor DSP genérico. Devuelve **código validado + mandos**, y el motor monta la cadena.

### 13.5 Fórmula programable (limitador vs trim)

```
threshold_limitador ≈ (LUFS_partida − LUFS_objetivo) + |trim_dB|
```

Caso "Vintage" del reporte: `(−14.3 − (−14)) + 1.3 = −1.6 dB`. El **trim (Utility) fija el techo real**; el limitador es el **drive** (cada 1 dB de umbral ≈ 1 dB de LUFS).

### 13.6 Plan de acción hacia el nivel Moises

| ID | Tarea | Prio |
|---|---|---|
| IA-01 | Activar embeddings `bge-m3` (desbloqueo de red) + rebuild index + `eval` | P0 |
| IA-02 | Conectar RAG al agente (top 4–6 fragmentos **por turno**, no en system prompt, con citas) | P0 |
| IA-03 | Conectar `IntentProfile` → `mix_mapper`/`mapper` en `POST /mix` y `/process` | P0 |
| IA-04 | Portar la fórmula del limitador + guardrail crest a `mix_mapper`; techo solo en master; saturador paralelo mix 0.3 con compensación | P0 |
| IA-05 | Constantes versionadas `intelligence/constants/mix.v1.json` + tests de integridad | P0 |
| IA-06 | Decidir vectores de producción (Supabase pgvector / Atlas / Ollama propio) | P0 |
| IA-07 | Ampliar `eval_questions.json` a ~50 preguntas reales | P1 |
| FE-01 | Panel de métricas en tiempo real (LUFS, true peak, RMS, crest, LRA, clipping, convergencia) | P0 |
| FE-02 | Aviso "bounce estéreo único → cambiar balance requiere stems" | P0 |
| FE-05 | Wiring `IntentProfile` → backend | P0 |
| DSP-01 | Implementar procesadores con los valores exactos (HPF 28/25, Q0.8, automakeup OFF, sat paralelo 0.3, trim separado) | P0 |
| DSP-05 | Bloquear limitador en pista (techo solo en master) | P0 |

### 13.7 Gap analysis — qué falta para paridad con Moises

| Capacidad Moises | En WaveAI | Brecha |
|---|---|---|
| Documento por usuario con historial | ✅ `projects`/`project_documents`/`project_states` + stores | Falta cablear `load_inputs()` a Supabase |
| Separación a stems idempotente | ✅ `separate_jobs.py` por `media_hash` (WU2) | — |
| Intent por lenguaje natural → parámetros | 🟡 `interpretIntent` + mappers existen | Sin wiring a endpoints (IA-03) y sin llamada real probada |
| Evidencia citada (conocimiento) | 🟡 RAG híbrido funcional en BM25 | Sin `bge-m3` (IA-01); sin conectar al agente (IA-02) |
| **Bucle de convergencia** (medir→mover→medir) | ⬜ El motor corre cadena fija en un paso | **Brecha principal**: falta el loop con guardrail de crest |
| Fórmula programable del limitador | ⬜ No está en `mix_mapper` | IA-04 |
| Panel de métricas en vivo + convergencia | ⬜ | FE-01 |
| Undo de proyecto (no chat) | 🟡 `undo_stack` vive en `project_states` | Falta el flujo visible de "pista + máster = 2 pasos" |
| Propuestas de IA que el usuario aplica | ✅ `mix_intent.proposals` (I1) | Falta el emisor (Intelligence) que las genere |
| Constantes de referencia versionadas | ⬜ | IA-05 (`intelligence/constants/mix.v1.json` no existe) |
| Memoria persistente multi-tipo | ⬜ | Fases 3–5 de `intelligence/README.md` |

**Lectura del gap:** lo estructural (multi-tenant + separación idempotente + compiler + stores) ya está construido. Lo que falta para el "nivel Moises" es de naturaleza distinta: **el bucle numérico de convergencia** (medir → calcular → mover un parámetro → medir, con guardrail de crest) y **la capa que cierra IA ↔ DSP ↔ evidencia** (IA-02/IA-03/IA-04/IA-05). Sin el loop, WaveAI aplica una cadena buena de una pasada; con el loop, empieza a *razonar* como Moises.

### 13.8 Referencias de esta sección

| Área | Archivo |
|---|---|
| Spec de la migración | `docs/reference/specs/project_document_v1_spec.md` |
| Reporte de conciliación IA/Moises | `docs/evidence/reports/REPORT_IA_WAVEAI.md` |
| Knowledge Core | `apps/audiomind/src/audiomind/intelligence/README.md` |
| RAG | `apps/audiomind/src/audiomind/intelligence/rag/` |
| Agente de intención | `apps/agent/src/agent.ts`, `apps/agent/src/intentProfile.ts` |
| Compiler | `apps/audiomind/src/audiomind/services/compile_project.py` |
| Tablas / RLS | `supabase/migrations/20261008120000_create_project_document.sql`, `supabase/migrations/20261008140000_create_project_documents.sql` |
| Stores Studio | `apps/studio/src/features/projects/store/mixStateStore.ts`, `.../projectDocumentStore.ts` |
| API multi-tenant | `apps/audiomind/src/audiomind/api/projects.py`, `.../api/auth.py`, `.../services/separate_jobs.py` |
