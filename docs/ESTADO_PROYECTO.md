# Estado del proyecto WaveAI / BrikMaster2027

> **Fecha de relevamiento**: 2026-09-21 · **Última actualización**: 2026-09-23 (verificación en vivo: tests, ruff, git).
> **Alcance**: repositorio completo — los tres motores (Mastering, Mix, Live Engine), frontend, agent de voz/IA, contratos, entorno, ramas y pendientes.
> **Fuentes**: código (`apps/`, `packages/`, `simulator/`, `e2e/`), documentos ODD (`odd/tasks/`), documentación (`docs/`), estado git real y suites de verificación.

---

## 1. Resumen ejecutivo

| Área | Estado |
|---|---|
| **Motor de Mastering (AudioMind)** | ✅ Operativo · cadena DSP proporcional completa · 628 tests verdes (backend completo) |
| **Motor de Mezcla (Mix Engine)** | ✅ Implementado (Pasos 01–08, TDD estricto) · paso 08 con cierre formal pendiente · **+ Stem Balance T1–T4** (faders ±6 dB + auto-balance por género, 23-Sep) · frontend "Mezcla de Audio" cerrado |
| **Motor en vivo (Live Engine)** | ✅ Operativo · **standalone** (knobs del navegador, sin WebSocket ni MIDI) |
| **Agent de interpretación (IA)** | 🟡 Compila · llamada real sin probar (faltan credenciales) |
| **Voz (chat/TTS)** | 🟡 Rutas implementadas · TTS pagado off por defecto (fallback navegador) |
| **Convex** | 🟡 Scaffold completo pero **durmiente** (la app no lo consulta) |
| **Bridge MIDI / Simulator Python** | ❌ **Removidos** del repositorio — README y docs quedaron desactualizados |
| **Deploy demo (Vercel+Railway)** | 📋 Plan LOCKED + runbook preparado · **no ejecutado** |
| **Suites de verificación** | Backend **628 passed** · Studio vitest **57 passed** · eslint **0 errores / 28 warnings** · e2e no ejecutado |

---

## 2. Estado del repositorio (git)

### 2.1 Rama actual y remotes

- **Rama actual**: `develop` — adelantada a `team/dev` por **4 commits sin pushear** (T1–T4 de Mix Stem Balance, 23-Sep).
- **Remotes**:
  - `origin` → `https://github.com/brikpaul569-cmd/BrikMaster2027.git`
  - `team` → `https://github.com/Masive-porjects/WaveIA.git`
  - `waveia` → `https://github.com/waveiamusic/WaveIA.git`
- **Working tree**: limpio en lo versionado. Hay rutas **excluidas localmente** (`.git/info/exclude`, no en git): `odd/`, `.atl/`, `docs/proposals/`, `docs/postmortems/`.

### 2.2 Ramas locales relevantes

| Rama | Estado |
|---|---|
| `develop` | Ahead 5 de `team/dev` — commits recientes de UI de mezcla (floating status stream, análisis flotante, `hip_hop` → perfil urban) |
| `main` | **Ahead 32 de `origin/main`** — muy atrasado el remote vs. local |
| `feat/mix-engine/01` … `08` | 8 ramas del Mix Engine, **locales sin push/PR** (decisión del usuario) |
| `demo/vercel-railway-client` | Ahead 3 de `origin/demo/vercel-railway-client` (deploy demo Vercel+Railway) |
| `docs/organize-centralize`, `feat/premium-ui-clarity`, `feat/preset-audio-signatures`, `refactor/page-mixpanel-onmasterize` | Varias con trabajo ya mergeado a `develop` |

### 2.3 Historial reciente (develop, 10 últimos)

```
e1ccc55 feat(mix-engine): expose balance_report in the mix payload        # T4
03f8abe feat(mix-engine): stem auto-balance by genre target with OFF default  # T3
fdfde4f feat(mix-engine): apply stem balance faders to all four stems at the bus input  # T2
cef92d8 feat(creative): stem balance faders ±6 dB for drums/bass/other/vocals  # T1
5de9025 feat(audiomind): aplicar tratamiento vocal adaptativo por registro
98e9e41 test(audiomind): añadir tests TDD del tratamiento vocal adaptativo
d32714d feat(audiomind): exponer registro/f0 vocal en AnalysisResult
0b54a97 feat(audiomind): detect vocal register y f0 con librosa.pyin
d94d80a refactor(studio): replace floating chips with sequential status stream
08ed0f6 style(studio): render mix analysis metrics as floating readings
```

> La feature **Mix Stem Balance** (T1–T4, `odd/tasks/mix-stem-balance.md`) entró en develop con 4 work-unit commits el 23-Sep; sigue la rama `feat/mix-engine/01…08` ya mergeada.

---

## 3. Los tres motores

### 3.1 Motor 1 — Mastering (AudioMind, backend FastAPI)

**Ubicación**: `apps/audiomind/src/audiomind/` · Python 3.11+ · FastAPI, librosa, pedalboard, numpy, demucs-onnx (separación de stems).

**Pipeline del engine** (`processing/engine.py`, ~1300 líneas): cadena **proporcional y dinámica** (no presets fijos):

1. **QC de entrada** (`strict_mode`) → rechaza HTTP 422 si clipping duro o true peak ≥ −0.3 dBTP (InputQcError).
2. **Gain staging** a −6 dBFS.
3. **De-esser dinámico** 3–8 kHz (detección por ratio de envolventes; neutral = bit-exacto).
4. **Match EQ por género** contra `TARGET_BANDS_HZ` [60,150,400,1000,2500,6000,10000,15000].
5. **Cadena de carácter** del preset (low/high shelf, peaking, exciter, imagen estéreo).
6. **Smart gate** (`smart_gate.py`): si la entrada ya cumple objetivos, omite corrección tonal (tier `full`/`conservative` — nunca gatea módulos de firma).
7. **Bloque M/S**: side HPF <100 Hz (off por defecto), reverb solo en el canal side (mono-safe).
8. **Colapso mono** <120 Hz al centro.
9. **Soft clipper** 16× (knee erf, márgenes) → **limiter true-peak** 8× con lookahead (doble protección anti intersample).
10. **Dither** TPDF + noise shaping Lipshitz 2º (16-bit) · resample libsoxr VHQ.
11. **Validación final**: LUFS, DR (LRA), correlación/phase del master final, crest.

**Revisión contra práctica profesional** (`docs/reference/DSP_INDUSTRY_REVIEW.md`): 17 recomendaciones — 16 cumplen, 1 parcial (preservar carácter tonal; diseño aceptado). **Fases A–D entregadas; P2 (dead code) FIXED** (2026-09-05).

**Compliance Phase 1** (`docs/reference/COMPLIANCE_PHASE1.md`, canónico): `processing_mode: transparent` = passthrough bit-exacto (neutral = bypass); `platform_target` (spotify −14/−1.0, apple_music −16/−1.0, youtube, tidal, custom); `output_sr`/`output_bit_depth` (24 bits default); `strict_mode` 422.

**Features adicionales**:

- **Demo mode**: pool gated de DSP (`MAX_CONCURRENT_DSP`), TTL de sesiones + janitor, duración máx 240 s, métricas `/api/demo/stats`.
- **Prerender** por preset (on-demand en demo).
- **Referencia externa** (Phase C): upload `reference-file` + `compare-reference` (diff espectral 8 bandas, LUFS/crest/correlación/LRA).
- **Álbum** (Phase D): `negotiate` (LRA por track) + `process` (target LUFS negociado sobre el pipeline existente).
- **Splitter** (Demucs), **Vocal chain**, **SongStarter/Beats** (secuenciador con samples).
- **Licencias**: `LicenseGuard` — sin key se desbloquea solo (demo); con key bloquea el estudio.

**Endpoints (38 en `api/`)**: upload (3) · mastering (17: process, prerender, reset, audio refs, raw, raw-mastered, download, session, master) · mix (2) · license (2) · splitter (3) · vocal (2) · songstarter (7) · batch/álbum (2) + `/health` y `/api/demo/stats` del app. Verificación detallada en el código de cada router.

**Tests**: `apps/audiomind/tests/` — suite **628 passed** (114 s) ✔ (incluye 19 tests del Mix Stem Balance T1–T4).

> ⚠️ Advertencias operativas: sesiones en memoria (`session_store`) — se pierden al reiniciar salvo espejo best-effort a `uploads/sessions.json`; `outputs/` (masters) **no** están en el volume de Railway → se pierden en redeploy. Pendiente de decisión: historial/retención.

---

### 3.2 Motor 2 — Mix Engine (mezcla IA+DSP)

**Ubicación**: `apps/audiomind/src/audiomind/processing/` (mix_engine.py + 11 módulos) · API en `api/mix.py`.

**Plan maestro**: `odd/tasks/plan-motor-de-mezcla.md` + viabilidad en `docs/proposals/VIABILIDAD_MOTOR_DE_MEZCLA.md` (local-only).

**Progreso — Pasos 01–08 IMPLEMENTADOS en TDD estricto** (suite creció 352 → **628 tests**):

| Paso | Rama | Commit | Estado |
|---|---|---|---|
| 01 Ruteo por stem + análisis | `feat/mix-engine/01-ruteo-stems` | `81a125a` | ✅ |
| 02 Frecuencias mágicas (Owsinski p.32) | `feat/mix-engine/02-frecuencias-magicas` | `1356d70` | ✅ |
| 03 Panorama por rol + validación posicional | `feat/mix-engine/03-panorama-validacion` | `8750b0e` | ✅ |
| 04 Dimensión a tempo (delay + Schroeder) | `feat/mix-engine/04-dimension-tempo` | `faf07d7` | ✅ |
| 05 Dinámica por stem + buss (Jerry Finn) | `feat/mix-engine/05-dinamica-buss` | `ff2b890` | ✅ |
| 06 Énfasis adaptativo por género | `feat/mix-engine/06-enfasis-genero` | `62467d4` | ✅ |
| 07 QC + versiones alternativas | `feat/mix-engine/07-qc-versiones` | `0b7b71a` | ✅ |
| 08 Exploración creativa acotada | `feat/mix-engine/08-exploracion-creativa` | `b37d82e` | ✅ (ver pendientes) |
| **SB** Faders + auto-balance por stem | `mix-stem-balance` (work-units en develop) | `cef92d8`+`fdfde4f`+`03f8abe`+`e1ccc55` | ✅ (T1–T4) |

**Stem Balance** (`odd/tasks/mix-stem-balance.md`, 23-Sep): producto pedido por el productor de la sesión (instrumental/snare dominan, voz ~7 dB abajo).

- **[T1]** Faders manuales ±6 dB por los 4 stems (`creative.py`, `_TRIM_STEM_RANGE = (-6.0, 6.0)`).
- **[T2]** `_apply_stem_trims` a la entrada del bus: escala por `10**(db/20)`; trims 0.0 = no-op bit-exacto (spec 08, neutral = bypass).
- **[T3]** Auto-balance opcional (`stem_balance.py` + toggle `auto_balance` en `build_mix`, default OFF): mide LUFS integrado por stem (BS.1770-4), target vocal = groove + d×6 según énfasis de género, corrige SOLO la voz con clamp ±6 dB.
- **[T4]** `balance_report` en el payload cuando `auto_balance=True`: género resuelto + status (active/neutral_fallback), LUFS por stem, target, `d`, gains (`*_db`) y flag `applied` honesto. OFF → clave ausente (payload previo exacto).
- **Pendiente**: T5 API (exponer faders+toggle en POST /mix), T6 Studio (UI), T7 A/B auditivo con la sesión hip_hop.

**Pipeline final por stem**: `split Demucs (4 stems) → pan por rol → EQ mágico → compresor por stem → dimensión (sends) → suma al bus → compresor de bus → QC → render de 5 versiones → modo creativo`.

- **Neutralidad**: perfiles `{}` = routing exacto del paso previo; `creativity=0` → principal byte-idéntico con/sin bloque creativo. La suma 1:1 NO es bit-exacta al original (Demucs es lossy — pitfall aceptado).
- **QC** (`quality_checks.py`): mono/fase, sibilancia 4–7 kHz, muddy 200–300 Hz, honky 450–600 Hz — flags informativos, **nunca bloquean**.
- **Versiones** (`render_versions.py`): principal 0 dB, vocal ±0.75 dB, instrumental, TV mix (sin vocal).
- **Creativo** (`creative.py`): espacio continuo 0..1, semilla reproducible, rejection sampling contra QC/posicional (nunca bloquea), `creative_manual=True` marca `non_standard`.

**API**:

- `POST /api/session/{id}/mix` → WAV + análisis en header `X-Mix-Result` (stems, `tempo_bpm`, `genre`, `genre_confidence`, sr, duración). Body opcional `{"dimension_enabled": false}`.
- `GET /api/session/{id}/audio/mix` → WAV persistido (URL estable para player/download).

**Frontend "Mezcla de Audio"**: `odd/tasks/mezcla-frontend.md` — **CERRADO (2026-09-21)**. Commits `7a95caf` (MixPanel.tsx, client.ts `mixTracks`/`getMixAudioUrl`, dock tab, GET /audio/mix) + `a406acf` (fix duplicación router). Verificado: `tsc --noEmit` limpio, vitest 22, pytest mix 9 passed. Queda **probar manualmente en la UI**.

**Pendientes del Mix Engine**: ver §7 (paso 08 EOL churn + cierre de assess; push/PR a `team`; análisis mypy soundfile).

---

### 3.3 Motor 3 — Live Engine (Web Audio, standalone)

**Ubicación**: `apps/studio/src/adapters/live/` + `apps/studio/src/lib/live/` + componentes `presentation/components/live/`.

**Arquitectura actual**: **INDEPENDIENTE — sin WebSocket**. Los parámetros vienen exclusivamente de los **knobs de la UI**:

```
Knobs UI → LiveParams → AudioGraph (Web Audio) → Recorder → descarga
```

**Grafo de audio** (`audioGraph.ts`):

```
Source → Filter (lowpass Biquad) → Drive (WaveShaper tanh 4× oversample)
       → Delay + Feedback → Reverb (Convolver) → Master Gain
       → Analysers (mono + L/R por canal) → Destination
```

- **Todos los cambios de parámetro con `setTargetAtTime`** (anti-zipper, obligatorio).
- **Neutral = defaults del schema** → master idéntico al original.
- Mediciones en tiempo real (`lib/live/meterMath.ts`): RMS, peak dB, correlación, stereo width, loudness momentary/short-term (24+5 tests ✔).
- **Recorder**: graba la salida del engine y la descarga como blob.
- Hint `useLiveEngine` (docstring): *"No WebSocket: params come exclusively from the knob UI"*.

**Protocolo** (`packages/contracts/live_params.schema.json` — fuente de verdad): 9 campos (`ts` requerido): `filter_cutoff` 200–12000 (default 12000), `filter_res` 0.5–12 (0.7), `drive` 0–1 (0), `delay_time` 50–800 (250), `echo_feedback` 0–0.8 (0), `reverb_mix` 0–1 (0), `output_level` 0–1 (0.9), `fx_preset` (clean | dub | big_room | radio | null). Tipos TS generados en `src/lib/live/liveParams.gen.ts`.

**UI**: `LiveView` + `FxSlotPanel` (slots FX), `Knob3D`, `LiveMeterDeck`, `LiveRecorderBar`, `PresetHeader`.

**Nota importante**: los README/AGENTS aún describen "socket :8765, heartbeat, bridge MIDI, fallback a neutral si el socket cae". **Ese flujo ya no existe**: el bridge y el simulator fueron removidos (§5). El documento `docs/reference/specs/05_live_engine_gestos_a_master.md` sigue siendo referencia de audio válida, pero la parte de gestos/MIDI quedó histórica.

---

## 4. Studio — frontend y aplicaciones acompañantes

### 4.1 Studio (Next.js 16 + React 19 + TS + Tailwind 4)

- **Tabs actuales** (`page.tsx`): Mezcla de Audio · Masterizar Audio (módulos) · Splitter · Vocal · Beats (SongStarter) · Guía de Géneros · Cadena de Master · Análisis · Estéreo · **Live Engine** · Álbum.
- Componentes: 60+ en `src/presentation/components/` (dock/ModuleDock con tiles de motor, MixPanel, MixWaveformAB, MixStatusStream, Player con A/B, FloatingDeliveryPanel, chat/ChatPanel, live/*, audio/* secuenciadores, auth/*, etc.).
- **Mix UI**: MixPanel + MixWaveformAB + MixStatusStream (stream secuencial de estado), action "masterize" post-mezcla.
- **Chat/agente**: ChatPanel → `/voz/chat` → `interpretIntent` (agent Gemini) → perfil; preset cards.
- **Voz**: `/voz/speak` (TTS ElevenLabs opcional con cache `.tts-cache`, tope 400 chars, `204` = fallback a `speechSynthesis` del navegador) · `/voz/escuchar` + `useVoiceInput` (entrada por voz) · `lib/voice/decodeAgentText` (parseo de texto del agente).
- **Librerías clave**: GSAP 3.15 + @gsap/react (11 componentes), framer-motion 12, tone 15, wavesurfer.js 7, lucide-react. Sin framework i18n: **microcopy en español latino neutro** hardcodeada (normalizada en `main`).
- **Tests**: vitest **57 passed** (8 archivos: meterMath 24, client 13, audioUtils 7, audioContextUtils 5, decodeAgentText 4, etc.) · eslint **0 errores / 28 warnings** (no funcionales, documentado) ✔.

### 4.2 apps/agent (`@midimastering/agent`)

- Traduce lenguaje natural → `IntentProfile` (9 ejes 0..1) con Gemini (`@google/genai`) + Zod; **no toca audio** — el mapper DSP convierte el perfil en `MasteringSettings`.
- Contrato `intent_profile.schema.json` ✅; `interpretIntent` compila pero **la llamada real no fue probada** (sin credenciales en el entorno). `needsClarification` no mueve el perfil; fuera de rango se rechaza (no clamp); ajuste incremental; `effort: low` por defecto; system prompt estable con `cache_control`.
- Pendientes: tipos Python para el mapper, integración Convex action, persistencia de conversación. El README referencia roles del equipo (Brickman/Tomás/Andrés).

### 4.3 Convex — dummie

Scaffold completo (`convex/` schema, auth, mastering, projects, messages; deps `convex` + `@convex-dev/auth`) pero **la app NO lo consulta**: `ConvexClientProvider` es un passthrough, hay **0 imports de `convex/_generated`**, el flujo de login fue removido. `convex/auth.ts` queda disponible para un futuro login real. El CI tiene env placeholder y un job `deploy-convex` gated por variable/secret.

---

## 5. Componentes removidos / documentación desactualizada

| Componente | Estado real | Evidencia |
|---|---|---|
| **`apps/bridge`** (MIDI → LiveParams → WS :8765) | ❌ **No existe** (ni en árbol ni en git) | Commits `92c79bf` (*remove vision/gesture/MIDI stack — Live Engine standalone*) y `38c1246` (*remove legacy HumanMidi gesture stack*) |
| **`simulator` (Python)** `python -m simulator.main` | ❌ **Solo queda `simulator/Dockerfile`** — el módulo ya no existe | `git ls-files simulator` → solo `simulator/Dockerfile` |
| **HumanMidi / gestos** | ❌ Removido | `docs/archive/HUMANMIDI_REMOVAL_REPORT.md` (histórico) |

> **Consecuencia**: `README.md`, `AGENTS.md` y `docs/README.md` del repo aún listan `apps/bridge/` y `simulator/` como componentes vivos y describen el flujo MIDI→WS→Live Engine. Es documentación **stale** — el Live Engine es standalone y no hay MIDI.

---

## 6. Entorno, CI/CD y verificación

### 6.1 Scripts y entorno local

- `scripts/` (`.bat` + `.ps1`): `setup` (venv + deps Python + bun install + build agent + .env.local), `start` (start-all con health checks), `stop`, `verify`. Docker Compose disponible (`docs/runbooks/DOCKER.md`).

### 6.2 CI (`.github/workflows/studio-ci.yml`)

- Pull requests (ruta `apps/studio/**`): `npm ci` + `npm run lint` + `npm run build` (env `NEXT_PUBLIC_CONVEX_URL` placeholder).
- Push a `develop`/`main`: igual.
- Job `deploy-convex` opcional solo en `main` si `CONVEX_DEPLOY_ENABLED=true` y existe `CONVEX_DEPLOY_KEY`.

### 6.3 Deploy demo

- `docs/runbooks/DEMO_DEPLOYMENT_PLAN.md` — **LOCKED** (Vercel → studio UI; Railway → audiomind; sin proxy de audio; envs exactas: `AUDIOMIND_CORS_ORIGINS`, `AUDIOMIND_PRERENDER_MODE=on_demand`, `MAX_CONCURRENT_DSP=1`, `DEMO_MAX_DURATION_SECONDS=240`, `MAX_FILE_SIZE_MB=100`, `SESSION_TTL_MINUTES=60`, `NEXT_PUBLIC_API_URL`).
- `docs/runbooks/DEPLOY_RUNBOOK.md` — **preparado, NO ejecutado** (sin credenciales usadas). Rama `demo/vercel-railway-client` local ahead 3.

### 6.4 e2e (Playwright)

- `e2e/playwright.config.ts`: chromium, `baseURL localhost:3000`, webServer `npm run dev --workspace=apps/studio`, fixtures `demo-audio.wav`.
- Specs: `demo_flow.spec.ts` y `master_to_live.spec.ts`. **No ejecutado en este relevamiento** (requiere stack levantado).

### 6.5 Verificación ejecutada (23-Sep, relevamiento actualizado)

| Comando | Resultado |
|---|---|
| `pytest tests/ -q` (audiomind) | **628 passed** (~114 s, warnings de deprecación de terceros) |
| `python -m ruff check` (audiomind) | **0 errores** (import order autofijado en T3) |
| `npm run test` (studio, vitest) | **8 files / 57 tests passed** |
| `npm run lint` (studio, eslint) | **0 errors / 28 warnings** |
| `npm run build` (studio) | — ejecutar si se desea (no corrido para no interferir) |

---

## 7. Pendientes y decisiones del usuario

| # | Pendiente | Dónde | Tipo |
|---|---|---|---|
| 1 | Push/PR de las ramas `feat/mix-engine/01…08` al remote `team` | Mix Engine | Decisión del usuario (requiere `gh auth login`) |
| 2 | Push de `develop` (ahead 4 de `team/dev`) y `main` (ahead 32 de `origin/main`) | git | Decisión del usuario |
| 3 | Limpiar **churn de EOL (LF→CRLF)** en `mix_engine.py` del paso 08 y cerrar el assess bloqueado | Paso 08 Mix Engine | Trabajo pendiente |
| 4 | **Mypy**: RESUELTO 23-Sep (commit `66c4fdb`) — `python_version` bump a 3.12 en pyproject, overrides estrechos para libs sin stubs, tipado corrigido hasta `Success: no issues found in 72 source files` | audiomind | Hecho |
| 5 | Prueba **manual** de "Mezcla de Audio" en la UI (backend + studio levantados) | Frontend | Decisión del usuario |
| 6 | **Deploy demo Vercel + Railway** (runbook listo, plan LOCKED) — requiere credenciales y vars | Deploy | Acción pendiente |
| 7 | Decidir si se **activa Convex** (auth/queries reales) o se limpia el scaffold | Studio | Decisión |
| 8 | Probar `interpretIntent` real (credenciales Gemini/Anthropic) + tipos Python del mapper + integración Convex action | apps/agent | Decisión usuario / credenciales |
| 9 | **Actualizar documentación stale**: README/AGENTS/docs mencionan bridge y simulator que ya no existen — **HECHO 23-Sep** (ESTADO_PROYECTO, README, AGENTS, docs/README, SETUP, DOCKER, USER_MANUAL, UX_MAP, ARQUITECTURA_WAVEIA_DETALLE actualizados; specs 05/07 y archive quedan históricos por convención). El servicio `simulator` roto del compose fue **quitado** (23-Sep, commit `093946c`, `docker-compose.yml` ahora solo `audiomind` + `studio`; queda el `simulator/Dockerfile` huérfano). Falta (scripts, no docs): corregir `scripts/setup/setup.ps1` (líneas 38–40 instalan `apps\bridge\requirements.txt` y `simulator\requirements.txt` que **ya no existen** — falla el setup de Windows) | Docs + compose + setup | Limpieza sugerida |
| 10 | Historial/retención de sesiones: `outputs/` fuera del volume de Railway → masters se pierden en redeploy | Backend/Deploy | Decisión de producto |
| 11 | Segundo libro del Mix Engine (anexo al plan) + autotune creativo **fuera de alcance v1** | Mix Engine | Documentado como fuera de alcance |
| 12 | **Mix Stem Balance**: T5 API (trims + toggle en POST /mix), T6 Studio (faders + toggle), T7 E2E neutralidad bit-exacta **HECHOS 23-Sep**; queda el A/B auditivo con la sesión hip_hop del productor (requiere su WAV, no está en el repo) | Mix Engine | Trabajo en curso (T1–T7 automatizable hechos, 23-Sep) |

---

## 8. Documentación: dónde está todo

**Canónica/vigente** (`docs/reference/`, `docs/runbooks/`, `docs/manual/`, `docs/evidence/`): índice central en `docs/README.md` — specs de implementación (valores DSP exactos), COMPLIANCE_PHASE1, DSP_INDUSTRY_REVIEW, DESIGN, SETUP/DOCKER/DEPLOY, USER_MANUAL, UX_MAP, evidencias de benchmark.

**Histórica** (`docs/archive/`): integración, HumanMidi removal, workplan, plan original.

**Local-only (excluida de git, `.git/info/exclude`)**:

- `docs/proposals/` — 4 PDF de libros (Mixing Engineer's Handbook, The Art of Mixing, Computer Music Tutorial) + `VIABILIDAD_MOTOR_DE_MEZCLA.md`, `VIABILIDAD_MOTOR_ESPACIAL.md`, `PERFIL_VINTAGE_SINTETICO.md`, `PROPUESTA_DIMENSION_POR_NECESIDAD.md`, `PROPUESTA_VOZ_ETEREA_VINTAGE_MOJADA.md`.
- `docs/postmortems/` — `inc-2026-04-22-checkout-5xx.md`.
- `odd/` — documentos de tareas ODD (plan-motor-de-mezcla, mezcla-frontend, preestudio-mezcla/espacial, mix-panel-glass-ux, mezcla-ux-progress, **mix-stem-balance** — T1–T4 hechos) y `mezcla-frontend` CERRADO.
- `.atl/` — skill registry local.

**Memoria Engram** (`brikmaster2027`): conocimiento consolidado del Mix Engine, postmortems, decisiones de arquitectura, auditoría de estado (observación 676) y las features recientes (vocal treatment, stem balance T1–T4; observaciones 714–717).

---

*Documento generado por auditoría read-only del repositorio y actualizado el 23-Sep con la feature Mix Stem Balance (T1–T4). Los commits y conteos de tests son del estado git verificado en esa fecha.*