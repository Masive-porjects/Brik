# Lineamientos de Arquitectura y Estándares de Código — WaveAI

Este documento establece las reglas de arquitectura y estándares de ingeniería para **WaveAI** (Next.js 16 + React 19 + TypeScript + Supabase).

---

## 1. Arquitectura Limpia por Features
Organiza el código del cliente en `apps/studio/src/features/` agrupando por dominio funcional, no por tipo de archivo técnico:

```text
src/
├── features/
│   ├── auth/                     # Autenticación y perfil con Supabase
│   ├── audio-upload/             # Carga y validación de archivos de audio
│   ├── mastering/                # Flujo y parámetros del DSP de mastering
│   ├── player/                   # Motor Web Audio y reproductor A/B
│   ├── remastering-history/      # Historial de versiones, proyectos y drafts
│   ├── live-engine/              # Motor Live en tiempo real + Bridge MIDI
│   ├── stem-splitter/            # Separador de stems
│   ├── vocal-chain/              # Procesamiento de pista vocal
│   └── songstarter/              # Generador y secuenciador
│
├── shared/                       # Código común y primitivas sin lógica de dominio
│   ├── components/               # Knobs, Faders, Modales, Botones, Sheets, Tabs
│   ├── hooks/                    # useDebounce, useMediaQuery, useLocalStorage
│   ├── utils/                    # Formateadores de tiempo, decibeles, frecuencias
│   └── config/                   # features.config.ts (Feature Flags)
│
├── i18n/                         # Internacionalización modular
│   ├── locales/
│   │   ├── es.json               # Español latino neutro
│   │   └── en.json               # Inglés técnico
│   ├── I18nProvider.tsx          # Provider de contexto de traducción
│   └── useTranslation.ts         # Hook tipado
│
└── app/                          # Composition Root (Rutas de Next.js App Router)
```

### Reglas de Organización
1. **Composición Limpia de `page.tsx`**:
   - `page.tsx` actúa exclusivamente como **Composition Root**: monta providers y ensambla contenedores principales.
   - Prohibido incluir llamadas masivas `fetch`, múltiples `useState` dispersos o lógica de renderizado pesada directamente en `page.tsx`.
2. **Capa Compartida (`src/shared/`)**:
   - Todo componente genérico (knobs, sliders, botones base, spinners, utilidades de audio) vive en la capa común y no depende de features específicas.
3. **Cero Código Muerto / Sin Código Huérfano**:
   - Eliminación total de Convex y dependencias en desuso.
   - TypeScript estricto con **0 errores de compilación** y sin uso indiscriminado de `any`.

---

## 2. Feature Flags y Desacoplamiento de Módulos
Para permitir activar o desactivar herramientas experimentales o secundarias sin alterar la lógica central:

1. **Configuración Centralizada (`src/shared/config/features.config.ts`)**:
   - Las features declaran su estado (`enabled`, `labelKey`, `icon`, `requiresAuth`).
2. **Consumo Dinámico**:
   - La barra de navegación / `ModuleDock` lee `FEATURE_FLAGS` y renderiza exclusivamente las pestañas activas.
   - Si una feature se apaga en configuración, se excluye de la vista sin generar errores de referencia.

---

## 3. Autenticación, Datos y Persistencia con Supabase
1. **Fuente Única de Verdad**:
   - Supabase es la fuente oficial para perfiles (`profiles`), pistas (`tracks`), borradores (`track_drafts`), mezclas consolidadas (`masters`) y auditoría (`track_events`).
   - Prohibido depender de `localStorage` para el estado maestro de canciones o autorizaciones.
2. **Subida Eficiente a Storage**:
   - Archivos originales a `audio-originals` y masters finales a `audio-masters`.
   - Políticas RLS estrictas vinculadas a `auth.uid() = user_id`.
