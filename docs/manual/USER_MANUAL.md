# Manual de usuario — WaveAI Studio

> Versión 0.1 — Mastering profesional asistido por IA.

## Estructura: 2 pantallas

La app es una sola página con **2 vistas**:

| Vista | Qué es |
|---|---|
| **Subir** | Pantalla de entrada: hero "Masteriza Tu Música", zona de drop, píldoras "-14 LUFS Standard · 4 Módulos DSP · Calidad Profesional" |
| **Mastering** | Se desbloquea al subir un track: navbar, player, presets, dock de módulos, panel de entrega, reporte y descargas |

Dentro de mastering hay **2 modos de trabajo**: toggle **"Manual" / "Asistente IA"** (IA = chat agente con recomendaciones; Manual = tarjetas de presets + ajuste fino).

---

## Paso 1 — Licencia (primera vez)

- Modo licenciado: **"Sistema Protegido. Ingresa tu clave de licencia para continuar."** → pegas la clave → **"Activar"**.
- La clave se guarda en la sesión del navegador y se envía como header `X-License-Key` en cada proceso/descarga.
- Fallas: **"No se pudo conectar con el servidor de licencias."** (servidor caído) o **"Error al activar la licencia"** (clave inválida).
- Desarrollo local sin `AUDIOMIND_LICENSE_KEY` configurada → desbloqueado automáticamente.
- Sin login: la app entra directo (el flujo de autenticación fue removido del frontend).

---

## Paso 2 — Subir un track

- **Formatos**: WAV y MP3, hasta **50 MB**.
- Arrastras el archivo o tocas **"Seleccionar archivo"**.
- Errores previos a subir:
  - "Formato no soportado" — *"Solo aceptamos archivos WAV o MP3. ¡Mantengamos la compatibilidad!"*
  - "Archivo demasiado grande" — *"Por favor, sube un archivo que pese menos de 50MB. ¡Mantengamos el estudio ágil!"*
- Mientras sube: overlay **"Subiendo tu track a WaveAI..."** con % real → al 100%: **"Cargado"** con check.

---

## Paso 3 — Análisis automático

El backend analiza loudness, espectro, tempo, DR y true peak, y **detecta el género** — se muestra en el **chip de la navbar** ("reggaetón", "hip hop", "electrónica", "acústico", "clásica", "metal", "jazz", "pop", "rock", "otro", o "Tu track").

Para cambiar de tema: ícono de refrescar → **"Sí, cambiar"**.

⚠️ **Audio ya masterizado**: modal *"Este audio ya cuenta con mastering"* con % de confianza y advertencia de **sobremasterización** (compresión excesiva, pérdida de dinámica, distorsión). Opciones: **"Cancelar"** o **"Procesar de todas formas"** (aplica cadena reducida al **80%**).

---

## Paso 4 — Presets ("Macro-Carácter")

Al clickear un preset se **procesa automáticamente** y queda indicado como activo.

| Preset | Género | Qué hace |
|---|---|---|
| **Pulido** | Multigénero | Balance profesional: EQ transparente, compresión suave (1.5:1), -14 LUFS |
| **Brutal** | Trap / Drill | Compresión agresiva (5:1), pegada máxima, -12 LUFS (ideal radio/clubs; las plataformas normalizan el volumen por igual) |
| **Cristalino** | Pop / Latin Pop | +4 dB de brillo y apertura estéreo (Haas 6 ms) |
| **Vintage** | Lo-Fi / Hip Hop | Saturación tipo cinta analógica (+3 dB drive, +4 dB warmth) |
| **Crudo** | Acústico / Folk | Mínimo procesamiento, dinámica orgánica, techo -2 dB |
| **Envolvente** | Ambient / Electronic | Imagen estéreo anchísima (width 1.8×, Haas 15 ms) |
| **Épico** | Rock / Alternativo | Punch y calidez (width 1.6×, Haas 12 ms, +2.5 dB) |
| **Muro** | Reggaeton / Dembow | Loudness máximo, graves contundentes (8:1, limitador -1 dB) |

**"Ajuste Fino"** (desplegable bajo los presets): 9 perillas — Reverb, Brillo, Ratio, Ceiling, Punch, Drive, Warmth, Width, Haas — más **"Restablecer"**.

> 💡 En modo Manual las perillas **no se aplican en vivo**: cambias los parámetros y el cambio se aplica al tocar **"Procesar con estos parámetros"**. Los presets, en cambio, procesan solos al seleccionarlos.

> 💡 **Caché de presets**: si ya escuchaste un preset en este track, al volver a tocarlo se restaura al instante (sin reprocesar). Se limpia sola al cambiar de track.

---

## Paso 5 — Opciones de entrega (botón flotante **"Entrega"**)

**1. Modo de procesamiento** | **"Creativo"** vs **"Transparente"**
- **Creativo** (master): *"Cadena completa: ecualización, compresión, saturación, loudness."*
- **Transparente**: *"Solo entrega: loudness (si hay target/plataforma), limiter, SRC y bit depth. No moldea el timbre."* — passthrough bit-exacto si no cambias nada; las perillas creativas se desactivan.

**2. Plataforma de entrega** → target de loudness + techo:

| Plataforma | LUFS | Ceiling |
|---|---|---|
| Automático | deja las perillas | — |
| Spotify | −14 | −1.0 |
| Apple Music | −16 | −1.0 |
| YouTube | −14 | −1.0 |
| Tidal | −14 | −1.0 |
| Personalizado | tú controlas | tú controlas |

Con Automático/Personalizado aparece el selector **"Loudness Target"** (Spotify -14, Deezer -14, SoundCloud -14, etc.).

**3. Formato de salida**
- **Sample rate**: Misma que la entrada / **44.1 kHz** / **48 kHz** / **96 kHz**
- **Bit depth**: **16-bit** o **24-bit** (default 24; a 16 se aplica dither con noise shaping)

**4. QC estricto** (toggle): *"Rechaza material dañado (clipping / true peak alto) con error claro en vez de procesarlo."*

> 🔄 Cambiar de preset **NO pisa** las opciones de entrega (modo, plataforma, SR, QC sobreviven).

---

## Paso 6 — Procesar

Botones: **"Procesar con estos parámetros"** (escritorio) / **"Procesar con este preset"** (móvil). Progreso real del backend:

- < 30% → *"Analizando espectro y aplicando Gain Staging..."*
- < 70% → *"Aplicando algoritmos DSP de Waveman Paul Morales..."*
- < 99% → *"Modelando True Peak y Noise Shaping..."*
- 100% → check + **"Cargado"**

Cadena real: análisis → gain staging a −6 dBFS → HPF 30 Hz → match EQ por género → brillo/calidez → compresor → módulos opcionales (multibanda, dyn EQ, excitador, estéreo) → saturación/tape → mono-compat < 120 Hz → loudness target → soft-clipper 16× → limitador true peak 8× → dither → validación.

---

## Paso 7 — Resultado

**Píldora flotante** (abajo a la izquierda): `-14 LUFS · -1.0 dBTP · 44.1k · 24-bit`. Expandida, el **"Reporte del motor"**:

| Métrica | Qué te dice |
|---|---|
| LUFS objetivo / LUFS medidos | ¿Llegó al target? |
| True peak (dBTP) | Riesgo de clipping en codecs |
| LRA (LU) | Rango de loudness / dinámica |
| Crest (dB) | Distancia pico/RMS — ¿está aplastado? |
| Sample rate + bit depth | Formato de salida real |

**Player A/B/C**: **Original** (tag "Raw"), **Master** y **Referencia** (render neutral a igual loudness — *"Mismo volumen que tu master — compara el carácter, no la fuerza."*). Cambio instantáneo de 10 ms.

**Descargas**: **WAV** y **MP3** → `waveai_{session_id}.wav/.mp3`. **"Compartir"** → tarjeta 1200×630 con stats y "masterizado con WaveAI" (Web Share o PNG).

---

## Errores comunes

| Error | Causa | Qué hacer |
|---|---|---|
| "El análisis del audio tardó demasiado…" | Backend lento (> 90 s) | Reintenta subiendo el track |
| "El procesamiento tardó demasiado y se canceló" | Proceso > 10 min | Prueba de nuevo |
| Detalle de error 422 (QC estricto) | Material dañado (clipping / TP ≥ −0.3 dB) | El backend da el detalle exacto |
| "Tu sesión anterior expiró" | Servidor reiniciado, storage sin persistir | Sube el audio de nuevo |
| "Algo salió mal en el estudio" | Error 5xx / saturación | Espera y reintenta |

---

## Live Engine (pestaña del dock)

Requisito: haber masterizado un track (si no: *"Primero necesitas masterizar un track para activar el motor en vivo."*). El Live Engine es **standalone** (Web Audio en el navegador): los knobs de la pestaña "Live" generan `LiveParams` directamente → FX en vivo (filtro, drive, delay, echo, reverb). Sin WebSocket ni MIDI — los knobs devueltos a sus defaults = master idéntico al original (neutral = bypass).