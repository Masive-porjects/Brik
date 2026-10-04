---
name: Spectral Mastering Void
colors:
  surface: '#121317'
  surface-dim: '#121317'
  surface-bright: '#38393e'
  surface-container-lowest: '#0d0e12'
  surface-container-low: '#1a1b20'
  surface-container: '#1f1f24'
  surface-container-high: '#292a2e'
  surface-container-highest: '#343439'
  on-surface: '#e3e2e8'
  on-surface-variant: '#bcc9c7'
  inverse-surface: '#e3e2e8'
  inverse-on-surface: '#2f3035'
  outline: '#869391'
  outline-variant: '#3d4948'
  surface-tint: '#5dd9d0'
  primary: '#6ee9e0'
  on-primary: '#003734'
  primary-container: '#4ecdc4'
  on-primary-container: '#00544f'
  inverse-primary: '#006a65'
  secondary: '#ecb2ff'
  on-secondary: '#520071'
  secondary-container: '#cf5cff'
  on-secondary-container: '#480063'
  tertiary: '#ffcca3'
  on-tertiary: '#4c2700'
  tertiary-container: '#ffa654'
  on-tertiary-container: '#723d00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#7cf6ec'
  primary-fixed-dim: '#5dd9d0'
  on-primary-fixed: '#00201e'
  on-primary-fixed-variant: '#00504c'
  secondary-fixed: '#f8d8ff'
  secondary-fixed-dim: '#ecb2ff'
  on-secondary-fixed: '#320047'
  on-secondary-fixed-variant: '#74009f'
  tertiary-fixed: '#ffdcc2'
  tertiary-fixed-dim: '#ffb77a'
  on-tertiary-fixed: '#2e1500'
  on-tertiary-fixed-variant: '#6d3a00'
  background: '#121317'
  on-background: '#e3e2e8'
  surface-variant: '#343439'
typography:
  display-xl:
    fontFamily: Syne
    fontSize: 56px
    fontWeight: '800'
    lineHeight: 64px
    letterSpacing: -0.03em
  display-xl-mobile:
    fontFamily: Syne
    fontSize: 36px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Syne
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Syne
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Syne
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Syne
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  metric-val-lg:
    fontFamily: JetBrains Mono
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.02em
  label-technical:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.06em
  label-badge:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.25rem
  gutter-desktop: 1.75rem
  margin: 1rem
  margin-tablet: 2rem
  margin-desktop: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system establishes an ethereal, spectral mastering aesthetic (*fantasmagórico*) engineered for next-generation audio professionals, sound designers, and electronic music producers. It melds precision DSP engineering with an otherworldly, spectral consciousness: sound is not merely processed; it is summoned, shaped, and illuminated from an astral plane.

The aesthetic fuses **Glassmorphism** and **Dark Tactile Neo-Brutalism**:
- **Atmospheric Void:** Deep charcoal obsidian and void blacks evoke quiet, high-end mastering suites in the dead of night.
- **Spectral Luminescence:** Semi-translucent glass surfaces catch ethereal cyan halos, ghostly violet shifts, and warm analog vacuum tube glows.
- **Tactile Precision:** Tactile skeuomorphic rotary dials, polished glass toggle pills, and high-frequency vector waveforms combine digital sorcery with studio console ergonomics.

## Colors

The palette is tuned around a dark void with high-contrast luminescent spectral emissions:

- **Primary (`#4ECDC4` - Spectral Cyan):** The ghostly life force of the interface. Used for dynamic waveforms, active signal routing, primary actions, positive metering thresholds, and radiant focus rings. Supported by `#64DFDF` for peak emissions.
- **Secondary (`#BD00FF` - Astral Violet):** Used for algorithmic mastering stems, AI inference indicators, dynamic EQ modulation badges, and ethereal transitions.
- **Tertiary (`#FF9F43` - Analog Tape Warmth):** Emulates vacuum tube warmth, saturation stages, clipping thresholds, and harmonic exciters.
- **Neutral (`#0B0C10` - Void Black):** Deep void black base canvas, elevated by obsidian layers (`#10121A`, `#161922`, and `#1E2230`). Glass backdrops feature translucent alpha layers (`rgba(22, 25, 34, 0.65)`) overlaid with hairline edge highlights (`rgba(255, 255, 255, 0.08)` to `rgba(78, 205, 196, 0.25)`).
- **Functional Semantics:**
  - True Peak Alert / Error: `#FF4976`
  - Stereo Phase Correlation / Pass: `#38EF7D`
  - Inactive / Floor Grid: `#2A2E3D`

## Typography

The typographical structure balances transcendental display headings with hyper-accurate hardware readouts:

1. **Editorial & Identity (`Syne`):** Carries futuristic curves, sculptural weights, and bold presence for heroic titles, engine statuses, and primary modal headings.
2. **Body & Utility (`Plus Jakarta Sans`):** Provides pristine legibility in deep dark environments, rendering contextual descriptions, settings labels, and master assistant prompts without eye fatigue.
3. **Audio Telemetry (`JetBrains Mono`):** Dedicated to technical metrics, audio parameters, decibel metering (`-14.0 LUFS`, `-1.0 dBTP`), DSP frequencies, and schema contracts. Always set with tabular figures (`tnum`) for non-shifting numeric readouts.

## Layout & Spacing

Layouts follow a structured 12-column fluid grid on desktop (collapsing to 8 columns on tablet and 4 columns on mobile), tailored for complex DAW workflow ergonomics and modular DSP rack structures:

- **Desktop (1200px+):** Max canvas constraint at 1440px with `margin-desktop` (48px) and `gutter-desktop` (28px). Arranges the spectral master visualizer centrally while pinning DSP chain stages and audio metering sidecars into high-density dockable modules.
- **Tablet (768px - 1199px):** `margin-tablet` (32px), `gutter` (20px). Meters collapse into expandable bottom drawers, keeping waveforms and core parameter knobs touch-accessible.
- **Mobile (< 768px):** Single-column stack with `margin` (16px). Key controls utilize thumb-friendly glass dock strips anchored at the bottom edge.
- **Spacing Rhythm:** Internal card and container paddings use strict 8px incremental multiples (`space-xs` to `space-xl`), ensuring compact technical density for audio plugin racks.

## Elevation & Depth

Visual hierarchy uses frosted glassmorphism backed by tinted volumetric glow fields:

- **Level 0 (The Astral Void - Canvas):** Raw background `#0B0C10` with subtle radial gradient flares of spectral cyan (`#4ECDC408`) and magenta (`#BD00FF06`) floating in atmospheric positions.
- **Level 1 (Sub-racks & Track Channels):** Background `#10121A` at 85% opacity, backdrop blur `12px`, with an inner border of `1px solid rgba(255, 255, 255, 0.05)`.
- **Level 2 (Active Studio Cards & Processors):** Frosted glass panels using `rgba(22, 26, 36, 0.65)`, backdrop blur `24px`, high-specular top rim light (`1px solid rgba(255, 255, 255, 0.15)`), and diffuse drop shadows (`0 12px 32px -4px rgba(0, 0, 0, 0.6)`).
- **Level 3 (Tactile Knobs, Sliders & Glass Pods):** 3D tactile pill treatments with radial specular highlights (`radial-gradient(circle at 35% 30%, rgba(255,255,255,0.4), rgba(255,255,255,0.02) 60%)`), cast against sunken track wells.
- **Level 4 (Floating Modals & Floating Spectral Ghosts):** Ambient halos with spectral glow spreads (`0 0 40px rgba(78, 205, 196, 0.25)` or `0 0 50px rgba(189, 0, 255, 0.2)`).

## Shapes

The design system adopts **Roundedness Level 2** (`rounded` = 8px, `rounded-lg` = 16px, `rounded-xl` = 24px) for structural studio interfaces, accented by full-pill radiuses for tactile controllers:

- **Processing Cards & Audio Modules:** Apply `rounded-xl` (24px) for master console decks, mirroring high-end hardware casings with chamfered inner glass bezels.
- **Stem Badges & Toggle Caps:** Apply continuous smooth pills (`9999px`) for sliders, toggle thumbs, and bypass switches.
- **Data Cells & EQ Bands:** Apply `rounded` (8px) for crisp, professional data framing without harsh corners.

## Components

### Buttons & Interactive Pods
- **Primary Spectral Button:** Pill-shaped or `rounded-lg`. Background: Gradient from `#4ECDC4` to `#2AC8B8`. Text: `#0B0C10` Bold. Box-shadow: `0 0 20px rgba(78, 205, 196, 0.35)`. On hover, the internal glow intensifies and scales by `1.02`.
- **Ghost Glass Button:** Frosted obsidian glass (`rgba(255, 255, 255, 0.04)`), `1px` border `rgba(255, 255, 255, 0.12)`, text `#FFFFFF`. Hover triggers an ethereal inner glow tint of Astral Violet (`#BD00FF20`) and border glow.
- **Master Trigger (Spectral Summon):** Features an oscillating, breathing pulse animation using an outer SVG blur mask.

### Tactile Knobs & Master Sliders
- **Rotary Glass Dials:** Dark concave alloy bases with a glossy glass lens overlay. Position notches glow in `#4ECDC4` or `#FF9F43` based on drive saturation.
- **Fader Tracks:** Sunken pill slots with an inset shadow (`inset 0 2px 4px rgba(0,0,0,0.8)`). Fader caps are brushed aluminum with an illuminated center laser stripe.

### Audio Waveform Visualizers
- **Spectral Ocean Display:** Real-time dual-rendered canvas. Bottom layer: low-opacity ethereal bloom. Top layer: sharp vector spline stroke (`1.5px`) transitioning across Cyan (`#4ECDC4`), Violet (`#BD00FF`), and Warm Orange (`#FF9F43`) depending on harmonic intensity.

### Telemetry Badges & LUFS Chips
- **Chips:** Monospace tags (`label-technical`) encased in glass capsules (`padding: 4px 10px`), styled with subtle colored indicator pips (e.g., green dot for `Integrated -14.0 LUFS`, orange for `Tape Saturation +3dB`).

### Toggle Switches & Stems
- **Glass Switch:** Frosted pill frame (`width: 52px, height: 28px`). In the active state, the slide well lights up in ghostly mint cyan while the thumb glows like a luminescent orb with specular glass refraction.

### DSP Chain Stages (Process Cards)
- **Chain Slots:** Modular horizontal or vertical blocks featuring stage indices (`01` through `13`), dynamic mini-graph previews (EQ curve, compression knee, stereo width vector), and an active bypass toggle button.