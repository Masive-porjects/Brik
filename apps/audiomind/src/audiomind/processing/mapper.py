"""Map a high-level mastering intent onto exact DSP parameters.

This module is the ONLY place that knows how the 9 semantic intent axes
become knob values. It is deliberately declarative: every axis is a table
of ``(axis_value, parameter_value)`` anchor points interpolated
piecewise-linearly around the 0.5 neutral point.

The neutrality contract is the hard rule the tests enforce: at 0.5 every
parameter takes its EXACT ``MasteringParameters`` default (not a generic
"zero" — ``clarity_wet`` defaults to 0.15, ``limiter_ceiling_db`` to
-1.0, ``target_lufs_db`` to None), so a fully neutral intent maps to a
bit-exact transparent master.
"""
from audiomind.models.audio import MasteringParameters
from audiomind.models.intent_profile import IntentProfile

# Engage thresholds — axes below these levels are simply not active.
_TAPE_ENGAGE = 0.55  # warmth / vintage
_MULTIBAND_ENGAGE = 0.55  # bass_weight
_EXCITER_ENGAGE = 0.6  # brightness
_DYN_EQ_ENGAGE = 0.6  # clarity

# Loudness ramp limits. At 0.5 the target is None (engine automatic, which
# at the neutral ceiling evaluates to -14 LUFS); above 0.5 it ramps toward
# the max streaming-safe target. The cap is now -12 LUFS (the loudest a
# delivery should ever be for universal normalization: Spotify/YouTube/Tidal
# sit at -14, Apple at -16; anything hotter than -12 gets attenuated by the
# platforms while carrying over-compression and distortion).
_LOUDNESS_TARGET_NEUTRAL_DB = -14.0
_LOUDNESS_TARGET_MAX_DB = -12.0


def _lerp(axis: float, anchors: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation through (axis, value) anchor points.

    Below the first / above the last anchor the value is HELD at the
    endpoint: an axis side without anchors means "no effect beyond
    neutral", never an extrapolation. Anchor hits (axis exactly on an
    anchor x) return the anchor value EXACTLY — this is what guarantees
    the bit-exact neutral mapping at 0.5.
    """
    points = sorted(anchors)
    if axis <= points[0][0]:
        return points[0][1]
    if axis >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=True):
        if x0 <= axis <= x1:
            if axis == x0:
                return y0
            if axis == x1:
                return y1
            t = (axis - x0) / (x1 - x0)
            return round(y0 + t * (y1 - y0), 6)  # 6 decimals kills float noise
    return points[-1][1]  # pragma: no cover — unreachable


def map_intent_to_mastering(intent: IntentProfile) -> MasteringParameters:
    """Translate a semantic intent into exact DSP parameters.

    Neutrality contract: every curve below is anchored at 0.5 on the
    parameter's EXACT default, and engage flags use strict ``>``
    thresholds above 0.5 — so ``IntentProfile.neutral()`` maps to
    ``MasteringParameters()`` bit-exactly.

    Combination rules:
    - ``vintage`` x ``warmth``: both engage the same tape stage. Vintage
      already adds its own saturation (bias/hysteresis/roll-off), so
      stacking the full warmth drive on top would overdrive the tape. When
      both axes are active the warmth drive is scaled down linearly (up to
      half at max vintage). Neutral is untouched: below the 0.55 engage
      threshold there is no drive to scale.
    - ``clarity``: engages the dynamic EQ when active and configures band
      2 (2.5 kHz).
    - ``punch``: ``adaptive_comp_ratio``/``attack_ms`` are mapped per the
      approved table but ``adaptive_comp_enabled`` stays False on purpose
      — engaging the adaptive module would REPLACE the fixed compressor
      for every non-neutral punch value, changing the whole pipeline
      character versus the session flow. The knob wiring takes effect the
      moment the adaptive stage is engaged elsewhere.
    """
    params = MasteringParameters()  # every default IS the 0.5 anchor

    # ── warmth ──────────────────────────────────────────────────────
    # saturation_warmth_db: -3 dB @ 0.0, 0 dB @ 0.5 (default), +3 dB @ 1.0.
    params.saturation_warmth_db = _lerp(
        intent.warmth, [(0.0, -3.0), (0.5, 0.0), (1.0, 3.0)]
    )
    # tape_drive_db: 0 dB @ 0.5 (default), +2 dB @ 1.0; held at 0 below.
    params.tape_drive_db = _lerp(intent.warmth, [(0.5, 0.0), (1.0, 2.0)])

    # ── vintage ─────────────────────────────────────────────────────
    # tape_hysteresis: 0 @ 0.5 (default), 0.4 @ 1.0.
    params.tape_hysteresis = _lerp(intent.vintage, [(0.5, 0.0), (1.0, 0.4)])
    # tape_bias: 0 @ 0.5 (default), 0.05 @ 1.0.
    params.tape_bias = _lerp(intent.vintage, [(0.5, 0.0), (1.0, 0.05)])
    # tape_rolloff_amount: 0 @ 0.5 (default), 0.4 @ 1.0.
    params.tape_rolloff_amount = _lerp(intent.vintage, [(0.5, 0.0), (1.0, 0.4)])

    # ── Tape stage — shared by warmth and vintage (combination rule) ─
    params.tape_enabled = intent.warmth > _TAPE_ENGAGE or intent.vintage > _TAPE_ENGAGE
    if intent.warmth > _TAPE_ENGAGE and intent.vintage > _TAPE_ENGAGE:
        # Both axes active: scale the warmth drive down, up to half at max
        # vintage, so the combined tape character stays musical instead of
        # stacking full drive on top of bias/hysteresis/roll-off.
        vintage_intensity = min(
            1.0, (intent.vintage - _TAPE_ENGAGE) / (1.0 - _TAPE_ENGAGE)
        )
        params.tape_drive_db = round(
            params.tape_drive_db * (1.0 - 0.5 * vintage_intensity), 6
        )

    # ── punch ───────────────────────────────────────────────────────
    # transient_boost_db: 0 dB @ 0.0/0.5 (default), +3 dB @ 1.0.
    params.transient_boost_db = _lerp(intent.punch, [(0.5, 0.0), (1.0, 3.0)])
    # adaptive_comp_ratio: 1.0 @ 0.5 (default), 3.0 @ 1.0 (see note above
    # about adaptive_comp_enabled staying False).
    params.adaptive_comp_ratio = _lerp(intent.punch, [(0.5, 1.0), (1.0, 3.0)])
    # adaptive_comp_attack_ms: 30 ms @ 0.0, 10 ms @ 0.5 (default), 5 ms @ 1.0.
    params.adaptive_comp_attack_ms = _lerp(
        intent.punch, [(0.0, 30.0), (0.5, 10.0), (1.0, 5.0)]
    )

    # ── clarity ─────────────────────────────────────────────────────
    # clarity_wet: 0 @ 0.0, 0.15 @ 0.5 (default), 0.30 @ 1.0.
    params.clarity_wet = _lerp(intent.clarity, [(0.0, 0.0), (0.5, 0.15), (1.0, 0.30)])

    # ── brightness ──────────────────────────────────────────────────
    # clarity_brightness_db: -2 dB @ 0.0, +1 dB @ 0.5 (default), +3 dB @ 1.0.
    params.clarity_brightness_db = _lerp(
        intent.brightness, [(0.0, -2.0), (0.5, 1.0), (1.0, 3.0)]
    )
    # exciter air band (band 4): engaged only above 0.6, amount ramping
    # from 0 @ 0.6 to ~0.3 @ 1.0.
    if intent.brightness > _EXCITER_ENGAGE:
        params.exciter_enabled = True
        params.exciter_band4_amount = round(
            0.3 * (intent.brightness - _EXCITER_ENGAGE) / (1.0 - _EXCITER_ENGAGE), 6
        )

    # ── width ───────────────────────────────────────────────────────
    # stereo_width: 0.7 @ 0.0, 1.0 @ 0.5 (default), 1.6 @ 1.0.
    params.stereo_width = _lerp(intent.width, [(0.0, 0.7), (0.5, 1.0), (1.0, 1.6)])

    # ── bass_weight ─────────────────────────────────────────────────
    if intent.bass_weight > _MULTIBAND_ENGAGE:
        params.multiband_enabled = True
        # multiband_low_threshold_db: -20 dB @ 0.5 (default), -30 dB @ 1.0.
        params.multiband_low_threshold_db = _lerp(
            intent.bass_weight, [(0.5, -20.0), (1.0, -30.0)]
        )
        # multiband_low_ratio: 1.0 @ 0.5 (default), 2.5 @ 1.0.
        params.multiband_low_ratio = _lerp(intent.bass_weight, [(0.5, 1.0), (1.0, 2.5)])
        # stereo_imaging_mono_below_hz: 0 @ 0.5 (default), 150 Hz @ 1.0.
        params.stereo_imaging_mono_below_hz = _lerp(
            intent.bass_weight, [(0.5, 0.0), (1.0, 150.0)]
        )

    # ── clarity → dynamic EQ ─────────────────────────────────────────
    params.dyn_eq_enabled = intent.clarity > _DYN_EQ_ENGAGE
    if intent.clarity > _DYN_EQ_ENGAGE:
        # 2.5 kHz band — freq/threshold are the stage defaults, set
        # explicitly so the clarity contract is self-documenting.
        params.dyn_eq_band2_freq_hz = 2500.0
        params.dyn_eq_band2_threshold_db = -20.0
        # dyn_eq_band2_ratio: 1.0 @ 0.5 (default), 2.0 @ 1.0.
        params.dyn_eq_band2_ratio = _lerp(intent.clarity, [(0.5, 1.0), (1.0, 2.0)])

    # ── loudness ────────────────────────────────────────────────────
    # limiter_ceiling_db: -2.5 dB @ 0.0, -1.0 dB @ 0.5 (default), -0.3 @ 1.0.
    params.limiter_ceiling_db = _lerp(
        intent.loudness, [(0.0, -2.5), (0.5, -1.0), (1.0, -0.3)]
    )
    # target_lufs_db: None (automatic) at 0.5 and below; above 0.5 it
    # ramps continuously from the automatic value at neutral (-14) toward
    # -9 at 1.0, instead of stepping, so loudness intent never jumps.
    if intent.loudness > 0.5:
        params.target_lufs_db = round(
            _LOUDNESS_TARGET_NEUTRAL_DB
            + (intent.loudness - 0.5) / (1.0 - 0.5)
            * (_LOUDNESS_TARGET_MAX_DB - _LOUDNESS_TARGET_NEUTRAL_DB),
            1,
        )

    return params