# IA de WaveAI — qué se hizo y qué sigue

**Responsable:** Miguel Angel Ariza (línea de IA)
**Rama:** `feat/ia-asistente-mezcla` (base `develop`, sin PR todavía)
**Última actualización:** 2026-10-05
**Estado:** 🟡 En curso. Ya funcionan IA → mezcla y la búsqueda en los libros; falta conectarlo al chat y activar los embeddings.

> **Para quién es:** Paul, Andrés y quien retome esta línea. Explica qué hay en la rama, cómo correrlo, qué decisiones se tomaron y qué falta, con lo que se necesita de cada uno.

---

## 1. Resumen en 30 segundos

Según la reunión, mi tarea es **conectar la IA con la mezcla y el mastering** y **construir el asistente con el conocimiento de los libros**. Hasta hoy:

1. **La IA ya puede mover la mezcla.** Hay un mapper nuevo: la misma intención que interpreta el agente ("voz al frente, más pegada") se traduce en faders de voz, batería y bajo para `POST /mix`. Antes la IA solo podía tocar el mastering, y ni siquiera eso estaba conectado.
2. **El contrato entre el agente y los mappers quedó alineado.** El modelo de Python no coincidía con el JSON Schema compartido. Un test nuevo falla si vuelven a diferir.
3. **El prompt del agente** quedó en español neutro, sin voseo, y el asistente se presenta como WaveAI.
4. **RAG sobre los 4 libros.** Se extrajeron 2.414 páginas (OCR con Tesseract donde hizo falta) y se dividieron en 1.806 fragmentos con capítulo y página impresa. La búsqueda híbrida combina palabras exactas (BM25) y significado (vectores, con Ollama). **Todo es local y nada de los libros entra al repo.**

**Lo más importante que falta:** activar los embeddings (bloqueo de red, ver §6), conectar la búsqueda y los mappers al chat del studio, y que Paul valide los valores provisionales.

---

## 2. Cómo encaja todo

```
                       ┌──────────────── OFFLINE (máquina local) ───────────────┐
 Libros (PDF, fuera ──►│ extraer / OCR ─► limpiar ─► fragmentos ─► embeddings     │
 del repo)             │ (Tesseract)      (pág.      (cap. +      (Ollama bge-m3)│
                       │                  impresa)   página)                     │
                       └──────────────────────────────┬──────────────────────────┘
                                                      ▼
                                   .rag/index  (gitignored: texto + vectores)
                                                      │  búsqueda híbrida
 Usuario en el chat ─► agente (Gemini) ◄─────────────┘  BM25 + vectores (RRF)
                         │
                         │ respuesta con cita ("Owsinski, pág. 32")   ← PENDIENTE de conectar
                         ▼
                    IntentProfile (9 ejes, 0.5 = neutral)
                      │                           │
                      ▼                           ▼
            mix_mapper.py (NUEVO)          mapper.py (ya existía)
            → POST /mix                    → MasteringParameters
            (faders, vocal_treatment)
```

**Principio de diseño:** *los libros sirven para que el asistente EXPLIQUE, y el conocimiento revisado sirve para DECIDIR.* El modelo nunca convierte un párrafo en un valor de DSP mientras atiende al usuario. Los números pasan por los mappers, que son deterministas, tienen tests y respetan que un ajuste neutro no toque el audio. Si se quieren reglas nuevas sacadas de los libros (por género o por instrumento), se curan offline y las revisa Paul (§6, fase 4). Así se cumple la regla del repo: "No inventes valores DSP, extráelos de las fuentes".

---

## 3. Lo que ya está hecho

### 3.1 IA → mezcla: `mix_mapper.py`  (commit `cfaba17`)

`apps/audiomind/src/audiomind/processing/mix_mapper.py` — `map_intent_to_mix(IntentProfile) -> MixSettings`.

| Eje de la intención | Qué mueve en la mezcla | Curva |
|---|---|---|
| `vocal_focus` | `stem_trims.vocals_db` | −3 dB @ 0.0 · **0 dB @ 0.5** · +3 dB @ 1.0 |
| `vocal_focus` > 0.6 | `vocal_treatment = true` | mismo umbral que la EQ dinámica del mapper de mastering |
| `punch` | `stem_trims.drums_db` | −3 / 0 / +3 dB |
| `bass_weight` | `stem_trims.bass_db` | −3 / 0 / +3 dB |
| los otros 6 ejes | nada: son del mastering | — |

- **No toca código del motor ni de la API.** Solo produce el body que `POST /mix` ya acepta (`MixSettings` tiene los mismos campos y defaults que `MixRequest`).
- **Neutral = bypass:** una intención neutra da exactamente los defaults de `MixRequest` (`stem_trims=None`, mezcla idéntica a la de antes).
- ⚠️ **Los ±3 dB son PROVISIONALES**: los elegí como la mitad de la banda ±6 dB de `TRIM_STEM_RANGE`. **Paul debe validarlos.**

### 3.2 Contrato `IntentProfile` alineado  (commit `8488d41`)

`packages/contracts/intent_profile.schema.json` es la fuente de verdad. El agente (Zod) lo cumplía, pero el modelo de Python no:

| Campo | Schema / agente | Python antes | Python ahora |
|---|---|---|---|
| `target_platform` por defecto | `"none"` | `"spotify"` | `"none"` |
| valores de `target_platform` | `spotify, apple, youtube, club, none` | cualquier texto | solo esos |
| `reference_genre` / `notes` | máx. 60 / 500 caracteres | sin límite | con límite |
| campos desconocidos | rechazados | aceptados | rechazados |

`tests/test_intent_profile_contract.py` lee el JSON Schema y falla si Python se vuelve a desalinear. Ningún mapper usa `target_platform`, así que el audio no cambia.

### 3.3 Prompt del agente  (commit `479176b`)

`apps/agent/src/prompt.ts`: se quitó el voseo (`movas`, `podes`, `Recibis`, `devolves`…), porque el modelo imita el registro del prompt, y el asistente se presenta como **WaveAI** en vez de "midiMastering". Son 7 líneas de texto, sin cambios de lógica.

> La regla 7 del prompt ("No puedes cambiar la mezcla…") se mantiene **a propósito** hasta que el mapper de mezcla esté conectado al chat.

### 3.4 RAG sobre los libros  (commit `2dee7ee`)

Código en `apps/audiomind/src/audiomind/intelligence/rag/`:

| Módulo | Qué hace |
|---|---|
| `books.py` | Catálogo (solo metadatos): edición, idioma, cómo extraer y cuál es la edición de referencia del código. |
| `extract.py` | PDF → texto por página. Usa la capa de texto o **Tesseract OCR** a 300 DPI. Corre en paralelo y **se puede reanudar** si se corta. |
| `clean.py` | Une líneas y palabras partidas con guion, quita encabezados, pies y créditos, y detecta la **página impresa**. |
| `chapters.py` | Normaliza capítulos: "Chapter Five 31", "CAPÍTULO 5", "Capítulo cinco" o "Figura 5.3" → `Cap. 5`. |
| `chunk.py` | Fragmentos de unas 320 palabras con solapamiento, **sin cruzar capítulos**. |
| `embed.py` | Cliente de Ollama (`/api/embed`, modelo `bge-m3`, multilingüe). |
| `index.py` | Índice híbrido: BM25 + vectores fusionados con RRF. Funciona en modo solo BM25 si no hay Ollama. |
| `evaluate.py` + `eval_questions.json` | 15 preguntas reales en español con la página donde está la respuesta. Mide hit@k y MRR. |
| `__main__.py` | CLI: `status`, `extract`, `build`, `search`, `eval`. |

**Los libros:**

| Libro | Págs. | Extracción | Fragmentos | Nota |
|---|---|---|---|---|
| Owsinski — *Mixing Engineer's Handbook* **1.ª ed. (EN, 1999)** | 233 | OCR | 254 | **Edición de referencia**: el Mix Engine cita sus páginas ("Owsinski pág. 32") |
| Owsinski — *Manual del ingeniero de mezcla* 5.ª ed. (ES, 2022) | 804 | texto | 317 | Ebook sin páginas impresas: se cita la página del PDF y el capítulo se deduce de las figuras |
| Gibson — *El arte de la mezcla* (ES) | 124 | OCR | 186 | La capa de texto viene cifrada ("Rdi muåi" = "Una guía"), por eso OCR |
| Roads — *The Computer Music Tutorial* (EN, 1996) | 1.253 | OCR | 1.049 | Teoría de DSP; más útil para el motor que para hablar con músicos |

**Decisiones y hallazgos:**
- **Las citas del código son correctas.** Verifiqué que la tabla "Instrument Magic Frequencies" está en la pág. impresa **32** de la 1.ª edición, exactamente lo que cita `magic_frequencies.py`.
- **El desfase entre página del PDF y página impresa no es constante**: al escaneo le falta una hoja (desfase 14 al principio y 13 después). Se resuelve por zonas, con votación entre detecciones cercanas y descartando el ruido del OCR.
- **Búsqueda híbrida**, porque los vectores solos fallan con términos exactos ("1176", "400 Hz") y BM25 solo falla con paráfrasis y con preguntas en español sobre un libro en inglés.
- **Ollama + `bge-m3`**, elegido por Miguel: gratis, local y multilingüe. Límite: **solo funciona en la máquina donde corre Ollama**, no en producción (Vercel/Railway). Ver §6.
- **Tesseract** para el OCR, elegido por Miguel: gratis y local. Calidad buena en texto corrido; tablas y figuras salen con algo de ruido.
- Los 7 `.md` de Paul que venían en la carpeta (propuestas y viabilidades) **no se indexaron**: son decisiones internas, no conocimiento para el usuario.

**Resultado actual:** evaluación en modo solo BM25 = **5/15** (MRR 0,30). Es la línea base esperada: las preguntas están en español y el libro de referencia en inglés, y BM25 no cruza idiomas. Los embeddings multilingües existen justamente para eso. Hay que medir de nuevo con `bge-m3` (§6).

---

## 4. Reglas que no se pueden romper

1. **El repo es PÚBLICO.** Los libros tienen copyright. **Nunca** se versionan los PDFs, el texto extraído, los fragmentos ni los embeddings.
   - Los datos van en `apps/audiomind/.rag/` (añadido al `.gitignore`).
   - La carpeta `Libros de Mezcla y Masterizacion/` está excluida en `.git/info/exclude`, **solo en la máquina de Miguel**. Quien la copie a la raíz debe excluirla también, o mejor dejarla fuera del repo y usar `RAG_BOOKS_DIR`.
   - Además GitHub rechaza archivos de más de 100 MB, y Roads pesa 109 MB.
   - Sí se versionan: el código, el catálogo de metadatos y las preguntas de evaluación (páginas, no texto).
2. **El asistente explica y cita, pero no decide números.** Los valores de DSP salen de los mappers o de conocimiento revisado por Paul.
3. **Neutral = bypass** en todos los caminos (los mappers tienen tests de esto).
4. **Citas cortas y parafraseadas.** El asistente no debe reproducir pasajes largos de los libros.

---

## 5. Cómo correrlo (en local)

**Requisitos del sistema (una vez):**

```powershell
# 1) Tesseract 5 + idioma español (el instalador trae solo inglés)
#    Si tessdata está en Program Files, usa una carpeta de usuario:
mkdir $HOME\.tessdata
copy "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" $HOME\.tessdata\
curl -L -o $HOME\.tessdata\spa.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/spa.traineddata
$env:RAG_TESSDATA_DIR = "$HOME\.tessdata"

# 2) Ollama + modelo de embeddings
winget install Ollama.Ollama
ollama pull bge-m3
```

**Dependencias Python** (extra opcional, no afecta al despliegue):

```bash
.venv/Scripts/pip install -e "apps/audiomind[dev,rag]"
```

**Uso** (desde `apps/audiomind`):

```bash
python -m audiomind.intelligence.rag status            # qué hay extraído / indexado / si Ollama responde
python -m audiomind.intelligence.rag extract           # PDF → páginas (reanudable; ~15 min con OCR)
python -m audiomind.intelligence.rag build             # páginas → fragmentos (+ embeddings si hay Ollama)
python -m audiomind.intelligence.rag search "¿dónde corto si la caja suena a boing?"
python -m audiomind.intelligence.rag eval -v           # hit@5 por pregunta (bm25 / vector / híbrido)
```

Variables opcionales: `RAG_BOOKS_DIR` (carpeta de los PDF), `RAG_DATA_DIR` (por defecto `apps/audiomind/.rag`), `RAG_TESSDATA_DIR`, `TESSERACT_CMD`, `OLLAMA_URL`, `RAG_EMBED_MODEL`.

---

## 6. Qué falta (en orden)

| # | Tarea | Quién | Depende de |
|---|---|---|---|
| 1 | **Activar los embeddings.** `ollama pull bge-m3` falló en la máquina de Miguel: la red no deja resolver `registry.ollama.ai` ni el almacenamiento R2 de Cloudflare desde la sesión. Probar desde una terminal normal o en otra red. Plan B: descargar el GGUF de `bge-m3` desde Hugging Face y crearlo con `ollama create`. Luego `build` y `eval` para comparar con el 5/15. | Miguel | red |
| 2 | **Validar los ±3 dB** del mapper de mezcla y el umbral 0.6 de `vocal_treatment`. | **Paul** | — |
| 3 | **Ampliar `eval_questions.json`** a unas 50 preguntas, con preguntas reales de músicos y respuestas en los 4 libros. | Miguel (+ Paul revisa) | — |
| 4 | **Conectar la búsqueda al agente.** Antes de llamar a Gemini, buscar en el índice y pasar 4–6 fragmentos en el bloque de contexto del turno (no en el system prompt, para no romper la caché). Cada respuesta lleva su cita. | Miguel | 1 |
| 5 | **Conectar los mappers al flujo del chat.** Hoy los 9 ejes que calcula la IA no llegan al audio: el studio solo muestra las 3 tarjetas de presets. Hace falta un endpoint o integración que lleve `IntentProfile` → `mix_mapper` / `mapper` → `POST /mix` y `/process`. Después, actualizar la regla 7 del prompt. | Miguel + **Andrés** | arquitectura de backend |
| 6 | **Decidir dónde viven los embeddings en producción.** Ollama solo sirve en local. Opciones: (a) Supabase + pgvector, que ya está en el stack; (b) MongoDB Atlas Vector Search, si Andrés va con Mongo para las mezclas; (c) Ollama en un servidor propio. También habrá que elegir un modelo de embeddings para producción. | **Andrés** + Miguel | decisión |
| 7 | **Conocimiento curado por género e instrumento.** Con el RAG, generar borradores en `intelligence/knowledge/genres/` (las plantillas y schemas ya existen). Paul revisa y los mappers o `emphasis.py` los consumen. | Miguel → **Paul** revisa | 1, 3 |
| 8 | Probar `interpretIntent` con una `GEMINI_API_KEY` real (nunca se ha probado). | Miguel | credencial |

---

## 7. Qué necesito de cada uno

**Paul**
- Validar los valores provisionales del mapper de mezcla (§3.1).
- Repartir con Miguel la tarea "convertir prompts en chunks y entrenar el asistente", que el acta de la reunión asigna a los dos. Propuesta: Miguel lleva el pipeline y la conexión con el agente; Paul revisa el conocimiento curado y las reglas de DSP.

**Andrés**
- Definir dónde viven los vectores en producción (§6, punto 6) y cómo se centralizan las llamadas a Gemini y la búsqueda en el backend.
- Definir cómo llega el `IntentProfile` del chat a los endpoints de mezcla y mastering (§6, punto 5).

---

## 8. Hallazgos para el equipo (no son de esta rama)

- **`ruff check` del backend no da 0 errores**, aunque `ESTADO_PROYECTO.md` lo afirma: hay errores ya existentes en archivos como `analyzer.py`, `mastering.py`, `vocal.py` o `license.py`. Los archivos de esta rama pasan ruff y mypy estricto.
- **12 tests del backend fallan en un entorno recién instalado**, y también fallan en `develop` sin esta rama:
  - `test_songstarter*`: faltan los samples; correr `scripts/generate_samples.py`.
  - `test_loudness`: errores de memoria de numpy, intermitentes.
  - `test_inter_engine_handshake::test_build_mix_returns_mix_metadata`: el pipeline real con Demucs.
- **`ESTADO_PROYECTO.md` y el README están desactualizados**: hablan de Convex, que ya no existe (ahora es Supabase), y dicen que no hay login (existen `/login`, `/register` y middleware).
- **El CI de GitHub ejecuta `npm ci` sin `package-lock.json`** (el repo usa `bun.lock`), así que probablemente falla.

---

## 9. Validación

| Comando | Resultado |
|---|---|
| `pytest tests/test_rag_pipeline.py` | **39 passed** |
| `pytest tests/test_mix_mapper.py tests/test_intent_profile_contract.py tests/test_mapper.py` | **60 passed** |
| `pytest tests/` (suite completa, 2026-09-28) | 742 passed / 12 failed (fallos de entorno que también ocurren en `develop`, ver §8) |
| `ruff check` (archivos de la rama) | 0 errores |
| `mypy` estricto (`intelligence/rag`, `mix_mapper.py`, `intent_profile.py`) | Success: no issues found |
| `apps/agent`: `tsc --noEmit` / `bun run check` | 0 errores / 12/12 |
| RAG `eval -k 5` (solo BM25) | 5/15, MRR 0,30. Línea base; falta medir con `bge-m3` |

## Historial de commits de la rama

| Commit | Descripción |
|---|---|
| `479176b` | fix(agent): prompt sin voseo, se presenta como WaveAI |
| `cfaba17` | feat(audiomind): mapper IntentProfile → Mix Engine |
| `8488d41` | fix(audiomind): IntentProfile alineado con el JSON Schema |
| `2dee7ee` | feat(audiomind): RAG local sobre los libros (OCR, fragmentos, búsqueda híbrida) |
| (este documento) | docs: reporte del equipo para la línea de IA |
