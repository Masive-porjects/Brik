# Sistema de Diseño — midiMastering Studio

Este documento resume el design system aplicado a la capa de frontend de `apps/studio/`. Los valores y reglas fueron extraídos de la especificación y del código; no deben inventarse.

## Visión de diseño

El studio se lee como un **panel de instrumento hardware oscuro**: superficies casi negras en capas, un único acento teal desaturado (`#627e84`), paneles de vidrio, knobs físicos y una capa de mascotas contenida (fantasmas + notas musicales) que mantiene la herramienta viva sin sobrecarga decorativa. Referencias principales: Ableton/BandLab en tono oscuro, con acentos de estilo Mindloop.

## Tipografía

- **Inter** (300–700) para todo lo funcional.
- **Instrument Serif italic** para acentos de una sola palabra (`.serif-accent`).
- Headings con `letter-spacing` negativo (−0.02 a −0.04 em).
- Fuentes cargadas desde Google Fonts en `globals.css`.

## Tema

- Modo oscuro por defecto.
- Modo claro soportado vía `html[data-theme="light"]`.
- Anti-FOUC: el tema persistido (`localStorage` `waveai-theme`) se restaura antes de la hidratación en `layout.tsx`.

## Tokens de color (dark default)

Los valores canonically viven en `apps/studio/src/app/globals.css`.

| Rol | Token | Valor dark |
|---|---|---|
| Fondo app | `--bg-app` | `#0b0b0c` |
| Fondo sidebar | `--bg-sidebar` | `#09090a` |
| Fondos legacy | `--bg-primary` / `--bg-secondary` / `--bg-tertiary` / `--bg-elevated` | `#0a0a0c` / `#121216` / `#1a1a20` / `#22222a` |
| Texto | `--text-primary` / `--text-secondary` / `--text-muted` | `#e8e8e8` / `#8a8a8a` / `#555555` |
| Acento | `--accent-primary` / `--accent-secondary` | `#627e84` / `#829ca1` |
| Éxito / advertencia / error | `--accent-success` / `--accent-warning` / `--accent-error` | `#34c759` / `#ff9500` / `#dc2626` |
| Meters | `--meter-safe` / `--meter-warn` / `--meter-clip` | `#34c759` / `#ff9500` / `#ff3b30` |
| Waveform original / master | `--waveform-original` / `--waveform-mastered` | `#484855` / `#00d4aa` |
| Vidrio | `--bg-glass` / `--bg-glass-elevated` | `rgba(18,18,22,0.6)` / `rgba(26,26,32,0.55)` |
| Superficies | `--surface-hover` / `--surface-active` | blanco @ 4% / 8% |
| Bordes | `--border-subtle` / `--border-strong` | blanco @ 5% / 12% |

Los colores de identidad de presets están en `apps/studio/src/core/presets.ts`.

## Vidrio y superficies

- **Receta de vidrio**: fondo translúcido (`--bg-glass`, `--bg-glass-elevated`) + `backdrop-blur` (20–24px) + borde sutil + rim-light superior de 1px blanco/30 + sheen superior de 64px blanco/[0.07] en paneles elevados.
- Utilidades: `.glass`, `.glass-elevated`, `.liquid-glass`.

## Knobs

- `Knob3D`: cara mecanizada radial-gradient desde tokens `--knob-gradient-*`, inset shadow, elipse de highlight, dimple central y LED brillante.
- Rango: ±135° (sweep 270°), transición transform 0.08s ease-out.
- Interacción: arrastre vertical, 200px de recorrido = rango completo.
- Range inputs legacy estilizados con `--knob-track`, `--knob-fill` y thumb radial-gradient.

## Animación y movimiento

Librerías:

- **GSAP** (`@gsap/react` / `useGSAP`) para entradas coreografiadas.
- **Framer Motion** para transiciones de presencia y layout.
- Helpers en `apps/studio/src/shared/motion.ts`: `fadeUp(delay)` y `VIEW_TRANSITION`.

Patrones clave:

- `PaintedModule`: wipe `clipPath` 0.7s `power2.inOut`.
- `ModuleSheet`: curtain `inset(0 0 100% 0) → 0`, 0.55s `power3.inOut`.
- `ModulePanel`: cards con stagger 0.04s, 0.45s `power2.out`.
- `WaveformBars`: 32 barras ondulan con `timeScale` 0.7 idle → 1.6 playback.
- `AnalysisPanel`: count-up de métricas vía GSAP `textContent` 1.1s.
- Upload card float: y ±6px, 2.6s `sine.inOut` yoyo.

Accesibilidad: todos los efectos coreografiados respetan `prefers-reduced-motion` y las capas ambientales están `aria-hidden` / `pointer-events-none`.

## Mascota y capa ambiental

Componentes deterministas/seeded, hydration-safe:

- `FloatingGhosts`: 8 fantasmas, 26–56px, opacity 0.18–0.46, loops 9–17s.
- `FloatingNotes`: 16 notas de 5 colores, 14–34px, loops 8–16s.
- `BigGhostWithNotes`: fantasma hero 80px + notas orbitando.

Colocación: campos detrás de toda la app (z 1–2), el hero detrás de la card de upload, watermark `/brand/WaveAI.png` con `var(--brand-bg-opacity)` en el canvas.

## Layout y navegación

- Shell `h-screen overflow-hidden`.
- Tres columnas flex con scroll independiente.
- Left rail (w-16 / lg:72px), canvas, right panel (w-80 / lg:96px).
- Navegación por dropdown "Módulos" que pinta el módulo en el canvas (`PaintedModule` con `key={currentTab}`).
- Historia: tab bar → columna de iconos → dropdown único. No reintroducir tabs horizontales.

## Componentes core

La lista detallada vive en `docs/reference/specs/04_waveai_sistema_diseno.md`. Los principales son `DropZone`, `ModulePanel`, `PlatformSelector`, `ProcessingOverlay`, `LicenseGuard`, `AnalysisPanel`, `SignalChain` y `StereoField`.

## Responsive

- Breakpoints: sidebar 64→72px, icon rail 48→56px, right panel 320→384px en `lg`, macro grid 2→4 columnas en `md`.
- Mobile: hamburguesa toggle, acciones progresivas `hidden sm:flex`.
- Hydration safety: `useIsClient` vía `useSyncExternalStore` y capas ambientales seeded.

## Microcopy

- **Español latino neutro/colombiano (sin voseo)**: "Sube tu audio", "Ajusta", "Prueba de nuevo".
- Identificadores y comentarios de código en inglés.

## Fuentes de verdad

- `docs/reference/specs/04_waveai_sistema_diseno.md` — spec completa del sistema de diseño.
- `apps/studio/src/app/globals.css` — tokens y utilidades CSS.
- `apps/studio/src/shared/motion.ts` — helpers de animación.
- `apps/studio/src/core/presets.ts` — colores e información de presets.
