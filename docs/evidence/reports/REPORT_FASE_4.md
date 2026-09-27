# Reporte de Implementación - Fase 4: Persistencia de Audio Original y Metadata (Supabase Storage & DB)

## 1. Resumen Ejecutivo
En la **Fase 4** se implementó la arquitectura de almacenamiento directo y seguro de los archivos de audio originales en **Supabase Storage** junto con el registro estructurado de metadata en la base de datos PostgreSQL (`public.tracks`).

Esto resolvió la limitación de sesiones volátiles en memoria del navegador, garantizando que cada audio cargado por un usuario quede archivado en la nube con políticas de seguridad a nivel de fila (RLS), sin saturar la memoria del servidor de Next.js ni bloquear la interacción inmediata con el motor de masterización AudioMind.

---

## 2. Infraestructura y Seguridad (Supabase)

### 2.1 Bucket de Almacenamiento
- **Bucket creado**: `audio-originals` (privado).
- **Estructura de rutas**: `{user_id}/{track_id}/original_{timestamp}.{ext}`.
- **Políticas RLS en `storage.objects`**:
  - Inserción, lectura, actualización y eliminación restringidas exclusivamente al propietario autenticado:
    `auth.uid()::text = (storage.foldername(name))[1]`.

### 2.2 Tabla `public.tracks`
- Registro estructurado de la pista:
  - `id UUID PRIMARY KEY`: Identificador único del track.
  - `user_id UUID REFERENCES auth.users(id)`: Propietario.
  - `title TEXT`, `original_filename TEXT`: Nombre para visualización y archivo fuente.
  - `storage_path TEXT`: Ruta exacta en el bucket `audio-originals`.
  - `file_size_bytes BIGINT`, `duration_seconds NUMERIC`: Especificaciones físicas del archivo.
  - `sample_rate INT`, `channels INT`, `format TEXT`: Características de audio detectadas.
  - `status TEXT`: Ciclo de vida (`uploaded`, `analyzing`, `ready`, `mastering`, `completed`, `error`).
- **Políticas RLS en `public.tracks`**:
  - `Users can manage their own tracks`:
    `USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)`.

---

## 3. Módulos y Cambios en el Frontend

### 3.1 Módulo `apps/studio/src/features/tracks/`
- **`types.ts`**:
  - Definición de interfaces `Track`, `CreateTrackInput`, `AudioMetadata` y `TrackStatus`.
- **`services/trackStorageService.ts`**:
  - `uploadOriginalAudio`: Carga en streaming al bucket `audio-originals` usando el cliente Supabase del navegador.
  - `extractAudioMetadata`: Extracción de duración, canales y sample rate en el cliente mediante `AudioContext` nativo sin latencia de red.
  - `createTrackRecord`: Inserción en la tabla `public.tracks`.
  - `getOriginalSignedUrl`: Generación de URL firmada temporal con expiración configurable (por defecto 3600s).
  - `updateTrackStatus`: Actualización del estado de procesamiento.
  - `deleteTrack`: Eliminación segura del audio en Storage y de la fila en Postgres.
- **`index.ts`**:
  - Barrel export limpio de tipos y servicios.

### 3.2 Integración en `useMasteringWorkflow.ts`
- **Carga Concurrente Desacoplada**:
  - Al seleccionar un archivo en `handleFileSelected`, la subida a Supabase Storage se ejecuta de forma concurrente con la transferencia al motor AudioMind.
  - Si el usuario no está autenticado, el studio permite masterizar en modo sesión temporal sin bloquear al usuario.
- **Corrección de Transición en `ProcessingOverlay`**:
  - Se corrigió el bug donde la pantalla se quedaba congelada en el checkmark de "Cargado" (`loading = true`). Al completarse la subida al motor, se ejecuta `setLoading(false)` e inmediatamente `setProcessing(true)`, dando paso fluido a la animación de procesamiento DSP.
- **Ajuste de Timeout de Análisis**:
  - Se extendió `ANALYSIS_TIMEOUT_MS` a 180,000 ms (3 minutos) para permitir que el análisis armónico (`librosa.pyin`) se complete sin abortar en procesadores sin GPU o bajo carga pesada en Windows.

---

## 4. Validación y Calidad
- **Commits asociados**:
  - `7a162cc`: `feat(tracks): integrate Supabase Storage direct audio uploads and metadata tracking`
  - `340fd67`: `fix(studio): run storage upload concurrently and handle session transitions with error modal`
  - `f10fcab`: `fix(mastering): transition loading to processing phase immediately after upload completes`
- **Pull Request**: Integrado en `origin/dev` mediante PR #19 (`c64857b`).
- **Verificación**: Subida validada contra Supabase Storage y confirmación de fila en la tabla `public.tracks`.
