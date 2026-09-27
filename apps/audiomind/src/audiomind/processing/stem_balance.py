"""Stem balance auto-gain (Mix Stem Balance, T3) — measurement + target.

The auto-balance answers the producer's reported symptom (voice ~7 dB
below the groove) with the engine's OWN meter and the genre emphasis the
engine already derives, WITHOUT inventing targets:

* measure: integrated LUFS per stem, reusing ``measure_lufs`` (the same
  BS.1770-4 meter the mix analysis uses) on the PROCESSED stems — the
  material that actually lands on the bus,
* target: the emphasis geometry (``emphasis.py``) resolves the genre to
  ``vocal_forward`` / ``groove_forward``; the direction driver
  ``d = vocal_forward − groove_forward ∈ [−1, 1]`` maps to the SAME
  ±6 dB fader band of the creative stem trims (T1). The voice target is
  ``groove_level + d * 6`` — a pop mix (d = +0.4) pulls the voice UP,
  a hip_hop mix (d = −0.4) keeps it lower, neutral 0.5/0.5 targets the
  exact groove level (d = 0),
* gain: ONE clamped correction on the voice (|gain| ≤ 6 dB) — the only
  relationship the emphasis defines (vocal v. groove). Drums/bass/other
  gains stay 0.0: the reported symptom is the voice, the manual faders
  (T1) stay on top for everything else,
* apply: pure calculation, never touches audio — ``mix_engine`` decides
  whether to apply (toggle, default OFF → the exact previous routing,
  bit-exact neutral, spec 08).

Module responsibilities (SRP): measure + geometry live here; the
application reuses ``mix_engine._apply_stem_trims`` (T2) — dependency
inversion toward the fader contract, so this module stays pure and
unit-testable without touching the engine or the audio graph.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .loudness import measure_lufs

#: The fader band of the creative stem trims (T1) bounds the auto-gain.
TRIM_STEM_RANGE = (-6.0, 6.0)

#: The dit is explicit.  Voice-target mapping factor: d ∈ [−1, 1] → ±6 dB.
_TARGET_DB_PER_UNIT_D = 6.0


def measure_stem_lufs(
    processed_stems: dict[str, np.ndarray], sr: float,
) -> dict[str, float]:
    """Integrated LUFS per stem (BS.1770-4, floored at −70 for silence).

    Measures the PROCESSED stems — the exact audio that lands on the bus
    after the chain — so the correction matches what the listener hears.
    """
    return {
        name: float(measure_lufs(audio, sr))
        for name, audio in processed_stems.items()
    }


def compute_stem_balance(
    processed_stems: dict[str, np.ndarray],
    sr: float,
    genre_weights: dict[str, float],
    fader_band: tuple[float, float] = TRIM_STEM_RANGE,
) -> dict[str, Any]:
    """Measure the stems and compute ONE clamped vocal gain, if any.

    Args:
        processed_stems: stem name → processed audio (post-chain, pre-bus).
        sr: sample rate of the processed stems.
        genre_weights: resolved emphasis weights
            (``{"vocal_forward": float, "groove_forward": float}`` —
            ``emphasis.resolve_emphasis`` output; the neutral 0.5/0.5
            fallback targets the exact groove level).
        fader_band: clamp window for the vocal gain, defaults to the
            creative fader band ±6 dB (T1).

    Returns:
        ``{
            "stem_lufs": {stem: float},
            "groove_level_lufs": float,     # mean LUFS of drums+bass
            "vocal_target_lufs": float,     # groove + d * 6
            "d": float,                     # vocal_forward − groove_forward
            "gains": {stem_db: float},      # "<stem>_db" keys — the SAME
                                            # contract as the mesh trims
                                            # (T1) and _apply_stem_trims
                                            # (T2); 0.0 except vocals_db
            "applied": bool,                # vocal gain ≠ 0
        }``
    """
    lo, hi = fader_band
    lufs = measure_stem_lufs(processed_stems, sr)
    vocal_forward = float(genre_weights.get("vocal_forward", 0.5))
    groove_forward = float(genre_weights.get("groove_forward", 0.5))
    d = vocal_forward - groove_forward

    groove_names = [name for name in ("drums", "bass") if name in lufs]
    groove_level = (
        float(np.mean([lufs[name] for name in groove_names]))
        if groove_names
        else float(lufs.get("vocals", 0.0))
    )
    vocal_target = groove_level + d * _TARGET_DB_PER_UNIT_D
    vocal_gain = float(np.clip(vocal_target - lufs.get("vocals", vocal_target), lo, hi))

    gains = {f"{name}_db": 0.0 for name in lufs}
    if "vocals" in lufs:
        gains["vocals_db"] = vocal_gain

    return {
        "stem_lufs": lufs,
        "groove_level_lufs": groove_level,
        "vocal_target_lufs": vocal_target,
        "d": d,
        "gains": gains,
        "applied": abs(vocal_gain) > 1e-9,
    }