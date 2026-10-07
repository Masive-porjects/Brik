# IA de WaveAI — Conciliación investigativa con Moises Studio

**Responsable:** Miguel Ángel Ariza (Línea IA)  
**Rama:** `develop` (sin mover de develop, tal como se indicó)  
**Fecha:** 2026-10-07  
**Estado:** INVESTIGATIVO — Conciliación completa de la referencia Moises Studio  
**Fuente de verdad:** Engram topic `architecture/ia-audio-pipeline-moises-reference` (7 bloques recopilados)  
**Ecosistema:** Moises Studio es un **ecosistema en producción mundial** — esta información es referencia autoritativa

> **Dirigido a:** Paul, Andrés y quien retome esta línea. Unifica todo lo recopilado: modelo operativo real, cadenas con valores cargados, fórmula del limitador vs trim, guardrails, separación `/separate`, RAG y plan de acción concreto.

---

## 1. Resumen Ejecutivo

El modelo operativo real de Moises Studio difiere de un enfoque puramente "chat-first". Los puntos clave que hay que llevar a Brik/WaveAI son:

- **Undo a nivel de proyecto.** Todo queda en el historial del documento del proyecto, no en el chat. Cada tanda de cambios es **UN paso único**. En el caso "Vintage", la cadena de pista + máster fueron **2 pasos**, no 10. Volver atrás es 1 clic. El transporte (playhead, loop, metrónomo) es estado de sesión aparte, no pasa por undo ni forma parte del documento.
- **Los resultados viven en el proyecto.** Si se detecta tempo, tonalidad, acordes o secciones, se escriben como **marcadores + mapa de tempo** sobre la línea de tiempo. Los renders, exportaciones o stems acaban como **pistas y clips con sus nombres, en su posición**, nunca como enlaces al chat.
- **Separar a stems es el ÚNICO camino para cambiar BALANCE.** Con un **bounce estéreo único**, NO se puede recuperar el balance entre instrumentos con EQ/comp/saturación. Eso solo cambia el **COLOR**. Para cambiar **BALANCE** hay que separar en **stems** y remezclar desde partes.
- **Los números mandan.** True peak define el techo real, LUFS define la sonoridad, crest + LRA demuestran que no se aplastó. Existe una fórmula directa y programable para el limitador vs trim.
- **Techo UNA sola vez.** Nunca poner limitador en la cadena de pista. El techo y la sonoridad se cierran **únicamente** en el **Stereo Out**.

---

## 2. Modelo Operativo Real de Moises Studio

### 2.1 Medir + Contenido (no sustituibles)

Antes de decidir **SIEMPRE** se hacen dos lecturas distintas:

- **(A) Métricas:** peak, true peak, RMS, crest factor, LUFS integrado, LRA (rango de sonoridad), fracción de silencio, muestras recortadas + tabla por compás.  
  - **True peak** → manda para el **techo** (picos entre muestras que llegan al conversor).  
  - **LUFS integrado** → manda para la **sonoridad**.  
  - **Crest + LRA** → validan que **NO** se aplastó la dinámica.
- **(B) Análisis de contenido:** detección de instrumentos + tempo, tonalidad y acordes del proyecto. Determina si es un **tema completo (bounce estéreo)** o un **instrumento suelto**.

### 2.2 Reparto Estructural

| Ubicación | Responsabilidad |
|---|---|
| **Pista (Track)** | Tono + Dinámica |
| **Stereo Out** | Techo + Sonoridad |

**Regla crítica:** Sin limitador en la pista. Dos limitadores en serie recortan dinámica dos veces, y el primero lo hace a ciegas sin saber lo que pedirá el techo final. El techo se cierra **UNA SOLA VEZ**, al final de toda la cadena.

### 2.3 Orden Correcto

**Corregir → Comprimir → Colorear**

- **EQ primero** (HPF + correctivo/tonal). Si filtras después de comprimir, el compresor reacciona a energía que no vas a escuchar.
- **Compresión antes de color**. El "pegamento" debe actuar sobre la señal ya balanceada tonalmene.
- **Saturación/efectos armónicos al final del bus de pista** (con compensación). Añaden **amplitud** → afectan true peak.
- **Reverb/Delay casi SIEMPRE por envío a bus**, nunca insert al 100% por pista. Así comparten espacio y se pueden filtrar/pre-delayar en un solo sitio.

### 2.4 Bucle de Corrección (Método)

**Medir → Calcular corrección → Mover 1 parámetro → Medir otra vez**

- **Máximo 4 medidas** por iteración global.
- **1 corrección por pasada**. No mover varios parámetros a la vez.
- **Parar cuando converge**, no cuando "suena bien".
- **Guardrail dinámico:** Si el **crest factor** baja **> 4 dB** respecto a la entrada → **volver atrás**. El objetivo NO se sostiene. Preservar dinámica es parte del objetivo de máster, no un daño colateral.
- **Sin espectro → sin EQ quirúrgico.** Fuera del HPF del máster, ninguna banda se justifica sin medición espectral. El carácter se basa en descripción/material.

---

## 3. Cadenas REALES Cargadas — Caso "Vintage"

**Material:** Bounce estéreo único neo-soul/R&B vintage, 87 BPM, G#m.  
**Pista y Stereo Out medían IGUAL antes de tocar nada.**

### 3.1 Punto de partida

| Métrica | Valor |
|---|---|
| **LUFS integrado** | -14.3 |
| **RMS** | -15.5 dB |
| **Crest factor** | 14.7 dB |
| **LRA** | 11.1 LU |
| **True Peak** | -0.8 dBTP |

**Diagnóstico:** Sonoridad ya correcta, sin margen de techo (-0.8 > -1.0), "le falta cuerpo".

### 3.2 Cadena de MEZCLA (pista — tratamiento de bus)

| Etapa | Parámetros cargados | Notas |
|---|---|---|
| **EQ** | HPF 28 Hz 12dB/oct · Low shelf 80 Hz +1.8 dB · Low bell 240 Hz +1.6 dB Q0.8 · High shelf 10.5 kHz +1.2 dB | HPF < fundamental G#1 (~51 Hz) → solo sub inaudible que consume headroom. Realces anchos (Q0.8) cambian peso, NO corrigen resonancias. |
| **Compresor (pegamento)** | Thresh -17.5 · Ratio 1.8 · Knee 8 · Attack 35 ms · Release 135 ms · Auto-makeup OFF · Makeup +1.4 dB | RMS -15.5 → 2 dB por debajo para trabajo suave continuo. Attack 35 ms deja pasar transiente kick/rimshot (mantiene pocket 87 BPM). Release 135 ms < pulso 690 ms → sin bombeo. |
| **Saturador (PARALELO)** | Drive +2.2 dB · Salida -1.2 dB · Mix **0.3** | **Mix 0.3 = 30% procesado + 70% seco.** Añade armónicos (cuerpo/presencia) sin comprimir toda la dinámica. Compensación -1.2 dB por +2.2 dB drive. **Efecto medido:** picos **-0.8 → 0.0 dBTP**. |

**Deliberadamente ausente:** Reverb, Delay, Ensanchadores (correlacionan lo ya correlacionado, emborronan/ensucian medios).

### 3.3 Cadena de MASTERIZACIÓN (Stereo Out)

| Etapa | Parámetros cargados | Notas |
|---|---|---|
| **EQ** | HPF 25 Hz ÚNICAMENTE | Sin más bandas (sin espectro no se justifica curva quirúrgica). En máster acumula sub → amplía margen del limitador. |
| **Compresor (pegamento)** | Thresh -6.5 · Ratio 1.7 · Knee 6 · Attack 30 ms · Release 250 ms · Auto-makeup OFF · Makeup 0 | ~9 dB por encima de RMS (-15.5) → **solo pasajes fuertes** tocan el compresor (estribillos/clímax). Release 250 ms más largo para no seguir cada golpe. |
| **Limitador** | Thresh **-1.6** · Lookahead ON | **Umbral = DRIVE, NO techo.** Todo lo que pasa por encima se limita; makeup automático sube a 0 dBFS. Cada 1 dB de umbral ≈ 1 dB de LUFS. |
| **Trim (Utility)** | **-1.3 dB** | **Fija el TECHO REAL.** Deja true peak entre -1.0 y -1.3 dBTP. El trim resta sonoridad → el limitador debe compensar esos 1.3 dB. |

### 3.4 Fórmula Limitador vs Trim (PROGRAMABLE)

```text
threshold_limitador ≈ (LUFS_partida - LUFS_objetivo) + |trim_dB|
```

**Aplicado a "Vintage":**
```text
(-14.3 - (-14)) + 1.3 = (-0.3) + 1.3 = -1.6 dB
```

### 3.5 Resultado Final Medido

| Métrica | Valor | Estado |
|---|---|---|
| **LUFS integrado** | -14.2 | Dentro de 0.5 LU del objetivo (-14) |
| **True Peak** | -1.2 dBTP | < -1.0 dBTP ✓ |
| **Crest factor** | 14.2 dB | Bajó **1.3 dB** vs bus mezcla (pegamento correcto) |
| **LRA** | 8.3 LU | OK |
| **Muestras recortadas** | 0 | OK |

**Veredicto:** Converge. No hizo falta segunda pasada. Si crest hubiera bajado **> 4 dB** se habría revertido.

---

## 4. Endpoint `/separate` — Contrato Técnico

### 4.1 Puertas (orden crítico)

1. **Validación de esquema**  
2. **Pre-flight** (GPU / VRAM disponible)  
3. **Idempotencia** (mismo `media_hash` + parámetros → devuelve job existente)  
4. **Cuota**  
5. **Caché de resultado**  
6. **Admission/Queue**

**CRÍTICO:** `jobs.insert` **ANTES** de `queue.enqueue`. Si se invierte, se pierde la referencia al job ante fallo de enqueue.

### 4.2 Worker

- **Chunking:** `chunk_plan` divide audio con **solape** + **crossfade trapezoidal** (evita artefactos entre ventanas).
- **Lease + Heartbeat:** el worker toma posesión del job; heartbeat mantiene lease. `reap_stale` re-asigna jobs con lease vencido.
- **Reanudación bit-exacta:** checkpoint se invalida si cambian parámetros. Flush de parciales antes de guardar.
- **Absorb / Finalize / Residual:** residual calculado en **float32 SIEMPRE**. Escritura **atómica** (`tmp` → `rename`) para nunca dejar WAV a medias.

### 4.3 Robustez + Tests

- **Política:** reintentos acotados + `reap_stale` + **DLQ con `media_hash`** (evita reintentar ciegamente mismo medio).
- **11 tests clave:**
  1. Determinismo: 10 ejecuciones → mismo hash
  2. Idempotencia: 50 requests → 1 job
  3. Reanudación bit-exacta tras kill
  4. Null test: stems + residual ≈ original
  5. 429 con cola acotada
  6. VRAM ≤ 80%
  7. Pre-flight sin GPU falla explícito
  (resto cubren contrato, leases, checkpoints)

---

## 5. RAG sobre Libros (Estado Actual)

### 5.1 Extracción e Indexado

| Libro | Páginas | Extracción | Fragmentos | Nota |
|---|---|---|---|---|
| Owsinski — *Mixing Engineer's Handbook* 1ª ed. (EN, 1999) | 233 | OCR | 254 | **Referencia canónica**. Citas verificadas (p.32 "Instrument Magic Frequencies"). |
| Owsinski — *Manual del ingeniero de mezcla* 5ª ed. (ES, 2022) | 804 | Texto | 317 | Ebook sin páginas impresas → cita página PDF + capítulo por contexto. |
| Gibson — *El arte de la mezcla* (ES) | 124 | OCR | 186 | Capa de texto parcialmente cifrada → OCR necesario. |
| Roads — *The Computer Music Tutorial* (EN, 1996) | 1.253 | OCR | 1.049 | Más útil para motor DSP que para charla con músicos. |

**Totales:** 2.414 páginas extraídas → **1.806 fragmentos** con capítulo + página impresa cuando disponible.

### 5.2 Arquitectura RAG

- **Híbrido:** BM25 + vectores fusionados con **RRF**. Funciona en modo solo-BM25 si Ollama no disponible.
- **Embeddings:** `ollama` + `bge-m3` (multilingüe, local). Gratis.
- **Chunking:** ~320 palabras, solapamiento, **sin cruzar capítulos**.
- **Citas obligatorias:** el agente debe citar (`Owsinski, p.xx`) con fragmentos breves/parafraseados.
- **Exclusión estricta:** PDFs, texto extraído, fragmentos y embeddings **NUNCA** van al repo. Solo código, catálogo de metadatos y `eval_questions.json`.

### 5.3 Evaluación

- **Solo BM25:** **5/15 hit@5, MRR 0.30** (esperado: preguntas ES vs libro EN).  
- **Pendiente:** medir con `bge-m3` activo tras resolver bloqueo de red. Objetivo: **> 10/15 hit@5**.

---

## 6. Plan de Acción por Equipo

### 6.1 IA / Ángel + Miguel

| # | Tarea | Prioridad | Notas |
|---|---|---|---|
| **IA-01** | **Activar embeddings `bge-m3`** | P0 | Bloqueo red: probar terminal normal o descargar GGUF desde HF + `ollama create`. Rebuild index + `eval`. |
| **IA-02** | **Conectar RAG al agente** | P0 | Inyectar top 4–6 fragmentos por turno (NO en system prompt), con citas obligatorias. |
| **IA-03** | **Conectar `IntentProfile` → mappers** | P0 | Llevar `IntentProfile` a `mix_mapper.py` + `mapper.py` → `POST /mix` y `/process`. Quitar regla 7 del prompt tras validación. |
| **IA-04** | **Portar lógica Moises a `mix_mapper`** | P0 | Implementar **fórmula** `threshold_limitador ≈ (LUFS_partida - LUFS_objetivo) + |trim_dB|`. Añadir **guardrail crest > 4 dB → revertir**. Forzar **techo ÚNICAMENTE en master**. Respetar **saturador paralelo mix 0.3 + compensación salida**. |
| **IA-05** | **Constantes versionadas** | P0 | Crear `apps/audiomind/intelligence/constants/mix.v1.json` con valores de referencia Moises + tests de integridad. Validar ±3 dB pendientes con Paul. |
| **IA-06** | **Decisión vectores producción** | P0 | Definir con Andrés: Supabase pgvector / MongoDB Atlas Vector Search / Ollama propio. Elegir modelo embeddings producción. |
| **IA-07** | **Ampliar `eval_questions.json`** | P1 | Llevar a ~50 preguntas reales con página correcta. Revisar con Paul. |
| **IA-08** | **Probar `interpretIntent` con GEMINI_API_KEY real** | P1 | Nunca probado aún. |

### 6.2 Frontend / Andrés

| # | Tarea | Prioridad | Notas |
|---|---|---|---|
| **FE-01** | **Panel de métricas en tiempo real** | P0 | Mostrar: LUFS integrado, true peak, RMS, crest, LRA, peak, muestras recortadas + **convergencia** (nº medida / nº pasada). |
| **FE-02** | **Detección "bounce estéreo único"** | P0 | Si análisis detecta full mix bounce → mostrar aviso: **"Tratamiento como bus. Cambiar BALANCE requiere separar a stems (EQ/comp/sat solo cambian COLOR)."** |
| **FE-03** | **Timeline + Marcadores** | P0 | Exponer tempo/key/acordes/secciones como **marcadores + mapa de tempo** (nivel proyecto). No mostrar en chat. |
| **FE-04** | **Respetar "efecto con script"** | P1 | NO exponer editor DSP genérico. Mostrar: nombre del script + mandos validados (motor devuelve código + UI). |
| **FE-05** | **Wiring IntentProfile → backend** | P0 | Conectar con IA-03 para enviar `IntentProfile` a endpoints `/mix` y `/process`. |

### 6.3 DSP / Brikman + Paul

| # | Tarea | Prioridad | Notas |
|---|---|---|---|
| **DSP-01** | **Implementar procesadores con valores exactos** | P0 | HPF 28/25, shelves/bell **Q0.8**, comp pegamento con **automakeup OFF**, **saturador paralelo mix 0.3** con compensación de salida, limitador con lookahead + **Trim/Utility** separado. |
| **DSP-02** | **Preservar 8× oversampling en limitador** | P0 | Si aplica a implementación actual, mantener 8× (tal como indica spec histórica). |
| **DSP-03** | **Validar ±3 dB `mix_mapper`** | P0 | Cruzar con casos reales. Ajustar solo con evidencia numérica. |
| **DSP-04** | **Contrato "efecto con script"** | P1 | Definir: descripción intención → motor devuelve **código validado + mandos** → montaje en cadena de pista. Moises NO escribe DSP custom manualmente. |
| **DSP-05** | **Aplicar regla "techo SOLO en master"** | P0 | Builder de cadena debe **bloquear** inserción de limitador en pista. |

---

## 7. Checklist de Validación

| Ítem | Criterio | OK |
|---|---|---|
| **Undo** | Histórico proyecto (no chat). Pista+máster = 2 pasos. Transport fuera de undo. | ☐ |
| **Timeline** | Marcadores + mapa tempo escritos al detectar tempo/key/chords/secciones. | ☐ |
| **Stems vs Balance** | UI avisa: bounce único → balance requiere stems. | ☐ |
| **Fórmula** | `mix_mapper` usa `(LUFS_partida - LUFS_objetivo) + |trim_dB|` para threshold limitador. | ☐ |
| **Crest guardrail** | > 4 dB drop → revertir / advertir. | ☐ |
| **Techo único** | Sin limitador en pista. Trim fija true peak en Stereo Out. | ☐ |
| **Paralelo sat** | mix 0.3 + compensación salida aplicada. | ☐ |
| **Automakeup OFF** | Glue comps con automakeup OFF (ganancia predecible). | ☐ |
| **RAG híbrido** | BM25+vectores activos + citas. Medir >10/15 con bge-m3. | ☐ |
| **`/separate`** | `jobs.insert` ANTES de `queue.enqueue`. float32 + atomic write. 11 tests verdes. | ☐ |

---

## 8. Referencias en Engram

Toda la recopilación quedó persistida bajo `architecture/ia-audio-pipeline-moises-reference`:

- **#880** — Observación consolidada con los 7 bloques (cadenas reales, fórmula, modelo operativo, `/separate`, walkthrough "Vintage")
- **#881** — Session summary completo con Goal/Instructions/Discoveries/Accomplished/Next Steps
- **Conflictos resueltos** vía `mem_judge`: `compatible` / `not_conflict` (referencia externa Moises complementa memorias internas Brik)

---

## 9. Conclusión

El mayor valor de esta conciliación no son solo los **valores numéricos**, sino el **modelo mental**:

> **Moises no "suena bonito". Moises mide, calcula, mueve UN parámetro, vuelve a medir y se detiene cuando converge.**

Llevar ese mismo rigor a `mix_mapper` (fórmula programable + guardrails numéricos) es lo que acercará WaveAI al comportamiento real de Moises Studio. El punto estructural decisivo queda claro: **para cambiar BALANCE hay que ir a STEMS**. Tratar un bounce como si tuviera balance separable es el error conceptual a evitar.

**Siguiente paso inmediato:** ejecutar **IA-01 a IA-05** + **DSP-01/DSP-02/DSP-03** en paralelo, con **FE-01/FE-02** habilitando la visibilidad de métricas y el aviso de "bounce → necesita stems".