# DSP Industry Review — Mastering Chain vs Professional Practice

> Status: 2026-09-05. Phases A, B, C and D landed; P2 items remain open.
> Companion: `docs/reference/COMPLIANCE_PHASE1.md` (delivery contract), `docs/archive/INTEGRATION_REPORT.md` (integration state).

## Purpose

Map the WaveAI mastering chain (`apps/audiomind/src/audiomind/processing/engine.py`)
against 17 pieces of advice commonly given by professional mastering engineers,
identify concrete gaps with code evidence, and drive them into shipped phases.

**Honest framing:** an autonomous product does not replace fresh ears. The winning
strategy is *neutral by default + process with intention + exhaustive QC + reject (422)
when a source cannot be saved* — the LANDR/emastered model. This review checks how
close the engine gets.

---

## What the chain already does well (evidence)

| # | Professional advice | Position | Evidence |
|---|---|---|---|
| 1 | Loudness is a delivery target, not a process goal | ✅ complies | LUFS measured/validated after the chain; `target_lufs_db` only sets the final alignment stage |
| 2 | Leave headroom before the bus | ✅ complies | `gain_stage` to −6 dBFS at the chain head (engine L139-155) |
| 3 | Double protection against inter-sample peaks | ✅ complies | Soft-clipper (16×, erf knee) → true-peak limiter (body + 4 ms lookahead, 8× Kaiser) |
| 4 | Reverb only on the side (mono-safe) | ✅ complies* | Reverb lives in the M/S block on the side channel; *(see P0-2 for final QC gap, now fixed)* |
| 5 | Pro-grade dither / oversampling hygiene | ✅ complies | TPDF dither + Lipshitz 2nd-order noise shaping at 16-bit; libsoxr VHQ resample before DSP |
| 6 | EQ toward a genre reference | ✅ complies | Match EQ against `TARGET_BANDS_HZ` [60,150,400,1000,2500,6000,10000,15000], delta×1.8, ±2 dB, skip <0.5 dB |
| 7 | Mono-compatibility floor | ✅ complies | L/R collapse below 120 Hz to mono center |
| 8 | Don't over-process a track that is already there | ⚠️ partial → **FIXED (Phase A)** | Chain was always-on; now `smart_gate.py` skips corrective tone-shaping when input analysis already meets targets |
| 9 | Tame sibilance on the master bus | ❌ was missing → **FIXED (Phase B)** | Legacy static de-esser only in `/vocal`; now dynamic de-esser 3-8 kHz in `process_audio` |
| 10 | Clean the sub-bass in the stereo decorrelation | ❌ was missing → **FIXED (Phase B)** | no side HPF <100 Hz; now `apply_side_hpf` in M/S block |
| 11 | Check the FINAL master for phase/correlation | ⚠️ partial → **FIXED (Phase A)** | Correlation was mid-chain only; now measured on final master + validation issue |
| 12 | Check dynamic range collapse | ❌ was missing → **FIXED (Phase A)** | DR validation was a silent `pass`; now real check (absolute floor + collapse ratio) |
| 13 | Decide per-track, not per-preset-blindly | ❌ was missing → **FIXED (Phase A)** | smart gate is analysis-driven, conservative with engaged signatures |
| 14 | Compare against an external reference while mastering | ✅ FIXED Phase C | `POST /session/{id}/reference-file` uploads a real reference; `POST /session/{id}/compare-reference` returns spectral diff + loudness/brightness profile |
| 15 | Master an album/EP toward a relative target | ✅ FIXED Phase D | `POST /api/album/negotiate` (measure LRA per track) + `POST /api/album/process` (per-track negotiated `target_lufs_db` through the existing single-track pipeline) |
| 16 | Integrity/QC gate that can reject bad sources | ✅ complies | `strict_mode` → HTTP 422 with parsed detail for hard-clipped / hot sources |
| 17 | Keep the tonal character the artist chose | ⚠️ partial | preset characters are preserved; smart gate uses conservative tier when a signature is engaged (see design note) |

---

## P0 gaps (were blocking quality) — status

| # | Gap | Root | Status |
|---|---|---|---|
| P0-1 | Smart gating "less is more" — chain always-on; neutral fast-path only with default params, not by analysis | No per-track decision | ✅ **FIXED** `feature/dsp-phase-a`: `smart_gate.py`, wired in `process_audio`; gated modules = match EQ / clarity shelf / warmth tilt / fixed compressor; NEVER delivery-critical stages |
| P0-2 | QC correlation/phase of the FINAL master | correlation/phase only inside spatial/imaging, mid-chain | ✅ **FIXED** Phase A: `measure_stereo_correlation` (windowed 4096/hop 1024) on final output; validation issue `< 0.35` (warning only) |
| P0-3 | Sibilance 3-8 kHz — static de-esser only in `/vocal`, outside `process_audio` | legacy voice-path design | ✅ **FIXED** Phase B: `deesser.py` dynamic detector (band/broadband ratio, audibility floor −55 dBFS, transient spike over 500 ms rolling reference); placed BEFORE tonal chain |
| P0-4 | Side HPF <100 Hz M/S does not exist | only L/R collapse <120 Hz to mono | ✅ **FIXED** Phase B: `apply_side_hpf` (4th-order butter, 24 dB/oct), `side_hpf_enabled` default off; complementary to mono collapse |
| P0-5 | DR validation is a `pass` no-op | stub left from chain build | ✅ **FIXED** Phase A: real DR check — output LRA < 3.0 LU (EBU 3342 floor) OR < 0.5× input DR → warning |

## P1 gaps — open

| # | Gap | Plan |
|---|---|---|
| P1-1 | External reference mode: `/reference/{preset_id}` re-renders the same track; there is no way to compare against a real master reference file | ✅ **FIXED** Phase C: `reference-file` upload/replace + `compare-reference` (spectral diff per 8-band profile, LUFS/crest/correlation/LRA deltas, biggest increase/decrease hints) — measurement-only, neutral contract preserved |
| P1-2 | Album/EP mode: no batch mastering toward a common relative target | ✅ **FIXED** Phase D: `POST /api/album/negotiate` (per-track input LUFS + EBU 3342-style LRA, negotiation table) + `POST /api/album/process` (masters IN ORDER overriding only `target_lufs_db` per track) — additive, no DSP change |

## P2 — dead code (low priority)

✅ **FIXED** (2026-09-05, `chore/dsp-p2-cleanup`): removed from `engine.py` —
`build_proportional_compressor` (replaced by the adaptive compressor),
`_build_dynamic_eq_fallback` + `calculate_proportional_gain` (fallback/legacy
helpers unreachable since `build_match_eq` replaced `build_dynamic_eq`),
`analyze_band_energy` (only used by the fallback), and the orphan
`_adjust_for_already_mastered` (zero call-sites). Dedicated dead-code tests
removed from `test_engine_smoke.py`; `adaptive_comp.py` docstring updated.

---

## Implementation notes (decisions worth preserving)

### Smart gate design (Phase A)
- Conjunction of the three Layer-2 validation constants: `|input LUFS − target| ≤ 1.5 dB`, `crest ≥ 6.0 dB`, `true peak ≤ ceiling + 0.1 dB`.
- `tier=full`: no signature engaged → gate match EQ, clarity shelf, warmth tilt, fixed compressor.
- `tier=conservative`: a character knob is engaged (`saturation`, `clarity`, `spatial`, `compression`, module on-flags) → gate ONLY match EQ (+ compressor when compression knobs are pristine). Signature modules are **never** gated.
- Report payload: `smart_gate: {applied, tier, gated_modules, evidence}`.

### De-esser design (Phase B)
- Band 3-8 kHz (anchors: analysis presence 6 kHz, vocal de-esser 5-8 kHz / 7.2 kHz).
- Detector: `band_env − total_env` ratio envelopes (15 ms attack / 150 ms release, from `multiband.detect_envelope`).
- Detection gate: band audible > −55 dBFS **and** spike > 3 dB over a 500 ms rolling reference — a permanently-bright program is NOT dulled (tested `test_permanent_bright_program_is_not_dulled`).
- Topology: parallel attenuation `y = x + (g_lin−1)·x_band` — exact 0 contribution below threshold (bit-exact); joint `(L+R)/2` detector preserves stereo image.
- Neutral: `deesser_amount_db == 0` or `deesser_enabled == False` → bit-exact no-op.

### Side HPF design (Phase B)
- Corner default 100 Hz, 4th-order Butterworth, side channel only (mid never touched).
- Anchor: below the 120 Hz mono collapse, above the 30 Hz master HPF — complementary by construction.
- `side_hpf_enabled` default `False` → bit-exact bypass.

### QC thresholds (Phase A)
- `STEREO_CORRELATION_MINIMUM = 0.35` (correlation meter "red zone" ~0.3-0.4, Ozone/ITU-style mono-compat guidance).
- `DR_COLLAPSE_RATIO = 0.5`, `DR_MINIMUM_LU = 3.0` (EBU 3342 percentile floor). Both warning-only.

### External reference comparison design (Phase C)
- Distinct surface from the Crudo `/reference/{preset_id}` re-render (same-track neutral). New prefix `reference-file`: `POST /session/{id}/reference-file` (upload/replace, validation mirrors `/api/upload`), `POST /session/{id}/compare-reference` (measurement, cached per session, cleared on re-upload), `GET /session/{id}/audio/reference-file` (playback; must be registered before `/audio/{audio_type}` — literal beats parameter).
- `compare_tracks` is pure measurement (no DSP): 8-band spectral levels from `analyze_band_energies` on MONO; LUFS from `measure_lufs` (the same BS.1770 meter the engine uses for target matching); crest mono peak/RMS; correlation from `measure_stereo_correlation`; LRA from `measure_lra`. Deltas are always `reference − master` (1 decimal; correlation 3 decimals).
- Hints: `biggest_increase_band_hz` (reference has MORE energy → "too quiet here") / `biggest_decrease_band_hz` ("too loud here").
- Neutral: comparison never touches audio; same master with/without a reference is bit-identical (feature-level identity test: file vs itself → all deltas ≈ 0).

### Album/EP relative target negotiation design (Phase D)
- Pure negotiation module (`processing/album.py`): `target = round(base + clamp((lra − album_median) × 0.25, ±2.0), 1)`; `base` is the album-wide target (default −14.0 LUFS); LRA is the EBU 3342-style `measure_lra` of the INPUT track. Tracks without a measurable LRA keep the base unchanged.
- Model (TC Electronic / Nugen-style "relative loudness"): perceptual uniformity in sequence — a track with MORE dynamic range has lower energy density, so it needs a slightly HIGHER integrated-LUFS target to feel equally loud next to denser tracks; a dense track gets a LOWER target.
- Endpoints (`api/batch.py`): `POST /api/album/negotiate` (measurement-only) and `POST /api/album/process` (masters in order, overriding ONLY `target_lufs_db` per track through the existing `process_audio`; replaces session state like the single-track endpoint; `save_sessions` once after all tracks).
- Failure semantics: guards fail fast (empty → 400, unknown session → 404, missing file → 400); per-track failures never abort the album — the track is marked (null metrics, `within_tolerance=False`, original exception type in `warnings`) and the rest continues.
- Report: per-track `lufs_deviation_db = output − target`, `within_tolerance` when |deviation| ≤ 1.5 dB (same tolerance as `validation.py`); warnings in Spanish (neutral Latin American) for out-of-tolerance tracks, consistent with the engine surfaces.

---

## Shipped phases

| Phase | Scope | Branch | Tests |
|---|---|---|---|
| A | smart gating + final correlation QC + real DR validation | `feature/dsp-phase-a` | `tests/test_phase_a.py` (11) |
| B | side HPF <100 Hz + dynamic de-esser 3-8 kHz | `feature/dsp-phase-b` | `tests/test_deesser.py` (25) + `tests/test_spatial.py` (+7) |
| C | external reference comparison (spectral diff + loudness/brightness profile), measurement-only | `feature/dsp-phase-c` | `tests/test_reference_external.py` (21) |
| D | album/EP batch mastering with relative LUFS/DR target negotiation, additive-only | `feature/dsp-phase-d` | `tests/test_album.py` (19) |

Suite after all four: **321 passed** (`cd apps/audiomind && python -m pytest tests/ -q`).

## Remaining

- Phases A+B merged into `main` via integration branch (`2f95925`); C/D/P2 ready to merge.
- End-to-end smoke with a real track once servers are running.