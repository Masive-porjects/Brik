"""P4 texture recipe (mix side): the character stage, measured and published.

Spec: ``odd/tasks/mastering-cohesion.md`` S1 (and S2's emission side).

The character stage (P3, ``processing/character.py``) bakes a deliberate texture
into the PRINCIPAL render: a slapback on the vocals, wow/flutter and a chorus on
``other``, parallel saturation on the bass, and a hiss/crackle bed under the
whole bus. Mastering receives that render as its input WAV and has no way to
know the noise is intentional — it does what it was built to do with noise and
treats it as material to correct. This module measures the texture's effect on
the mix bus and returns a machine-readable ``texture_recipe`` the mastering chain
can read (P4, T3).

What is measured, and on which buses
------------------------------------

Everything under ``measured`` is a delta between the two buses that exist at the
same moment in ``build_mix``:

* **clean** — the sum of the pre-character stems: the mix the engine would have
  produced without the character stage;
* **shaped** — the bus the character produces, **bed included**, which is the
  bus at the input of the 2-bus compressor.

The approximation is deliberate and stated rather than hidden: the deltas are
measured on the bus input, *before* the 2-bus compressor. That compressor then
acts on both buses equally, so it cancels out of the delta — but a compressor
that reacts to the bed (this one does) can move the final numbers slightly. The
recipe reports the input-side delta, which is the quantity the mastering chain
needs: S5 subtracts ``loudness_delta_lu`` from its own loudness measurement of
the render.

Signs are measured, never assumed. A bed can raise or lower the crest factor
depending on how dynamic the program is (``character.character_budget`` says the
same about the QC tolerance), so ``crest_delta_db`` is reported as
``crest(clean) - crest(shaped)`` with whatever sign the material produces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

import numpy as np
from scipy.signal import butter, sosfilt

from audiomind.processing.character import HF_BAND_HZ, crest_db
from audiomind.processing.loudness import FLOOR_LUFS, integrated_loudness
from audiomind.processing.splitter import STEM_NAMES

#: Recipe schema version this module emits and the reader accepts (S2). A
#: reader that meets another value ignores the recipe whole rather than
#: half-applying it.
RECIPE_SCHEMA: Final[int] = 1

#: The "telephone band" a band-limited vocal lives in (requirement 4).
VOCAL_BAND_HZ: Final[tuple[float, float]] = (300.0, 3400.0)

#: Share of the vocal's energy that must sit inside ``VOCAL_BAND_HZ`` for the
#: vocal to be declared band-limited. This is a declared threshold, not a
#: measurement: the measured share travels alongside it as ``vocal_band_ratio``.
#: The ``commercial_alt_pop`` profile does NOT band-limit the vocal, so real
#: material reads below this and the boolean stays honest about it.
BAND_LIMITED_VOCAL_RATIO: Final[float] = 0.9

#: Energy floor (dB) so a silent band stays a finite, comparable number
#: (mirrors ``character._band_energy_db``).
_BAND_ENERGY_FLOOR_DB: Final[float] = -300.0


def _loudness_lu(audio: np.ndarray, sr: int) -> float:
    """Integrated loudness (BS.1770-4), floored so silence stays finite.

    The meter returns ``-inf`` for silence; the recipe is data other code
    consumes, so it reports the meter's floor (``loudness.FLOOR_LUFS``) instead
    of a value that would poison the delta with a NaN.
    """
    value = integrated_loudness(audio, sr)
    if not np.isfinite(value):
        return float(FLOOR_LUFS)
    return float(value)


def _band_energy_db(audio: np.ndarray, sr: int, band_hz: tuple[float, float]) -> float:
    """Absolute band energy in dB, floored so silence stays comparable.

    Mirrors ``character._band_energy_db`` (same 2nd-order Butterworth bandpass,
    same floor) so the HF excess this module reports and the HF droop that
    module reports describe the same neighbourhood with the same tool.
    """
    x = np.asarray(audio, dtype=np.float64)
    if x.size == 0:
        return _BAND_ENERGY_FLOOR_DB
    low, high = band_hz
    sos = butter(2, [low, high], btype="bandpass", fs=sr, output="sos")
    filtered = sosfilt(sos, x, axis=-1)
    energy = float(np.sum(np.square(filtered)))
    return float(10.0 * np.log10(max(energy, 1e-300)))


def _band_ratio(audio: np.ndarray, sr: int, band_hz: tuple[float, float]) -> float:
    """Share of the signal's power inside ``band_hz`` (``0.0`` for silence).

    Measured on the magnitude spectrum rather than by filtering: a bandpass
    filter attenuates content near the band edges, so re-filtering a signal that
    already lives inside the band returns a share well under 1 and the
    "telephone band" question would answer itself incorrectly. Summing the
    spectral bins inside the band answers it directly.
    """
    x = np.asarray(audio, dtype=np.float64)
    if x.size == 0:
        return 0.0
    mono = x.mean(axis=0) if x.ndim > 1 else x
    if mono.size == 0:
        return 0.0
    windowed = mono * np.hanning(mono.size)
    power = np.square(np.abs(np.fft.rfft(windowed)))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    total = float(np.sum(power))
    if total <= 0.0:
        return 0.0
    low, high = band_hz
    in_band = float(np.sum(power[(freqs >= low) & (freqs <= high)]))
    return float(min(1.0, max(0.0, in_band / total)))


def _spectral_centroid_hz(audio: np.ndarray, sr: int) -> float:
    """Magnitude-weighted spectral centroid of the whole signal (Hz).

    A whole-signal magnitude centroid, not librosa's per-frame mean: the recipe
    only ever reports the DELTA between two buses measured the same way, so a
    consistent, dependency-free definition beats an exact match with the
    analyzer's framing. Digital silence has no centroid and returns ``0.0``.
    """
    x = np.asarray(audio, dtype=np.float64)
    if x.size == 0:
        return 0.0
    mono = x.mean(axis=0) if x.ndim > 1 else x
    if mono.size == 0:
        return 0.0
    windowed = mono * np.hanning(mono.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    total = float(np.sum(spectrum))
    if total <= 0.0:
        return 0.0
    return float(np.sum(freqs * spectrum) / total)


def build_texture_recipe(
    *,
    profile: str,
    seed: int,
    stages: Mapping[str, Sequence[str]],
    clean_bus: np.ndarray,
    shaped_bus: np.ndarray,
    sr: int,
    bed: Mapping[str, Any],
    vocal_audio: np.ndarray | None = None,
    vocal_sr: int | None = None,
) -> dict[str, Any]:
    """Measure the character texture and return the ``texture_recipe`` (S1).

    Pure and dependency-light by design: it takes arrays and returns the recipe
    dict, with no I/O and no dependence on ``build_mix``'s internals, so tests
    can feed it synthetic buses and assert exact numbers.

    Args:
        profile: The character profile name that ran (``commercial_alt_pop``).
        seed: The resolved seed of the stochastic part (the bed).
        stages: The profile's stem → stage map. Every ``STEM_NAMES`` stem is
            listed in the output, with an empty list for one the profile does
            not treat.
        clean_bus: The stem sum WITHOUT the character stages.
        shaped_bus: The bus the character produced, bed included — the bus at
            the input of the 2-bus compressor (see the module docstring for the
            stated approximation).
        sr: Sample rate of both buses.
        bed: The report returned by ``character.apply_bed``; it says whether the
            bed ran and at which levels.
        vocal_audio: The vocals stem the render carries (the shaped one). When
            ``None`` the vocal band is unmeasured and reads ``0.0``/``False`` —
            an unmeasured vocal never claims to be band-limited.
        vocal_sr: Sample rate of ``vocal_audio``. Defaults to ``sr``; the mix
            engine resamples every stem to the bus rate, so they agree.

    Returns:
        The recipe dict (S1): ``recipe_schema``, ``profile``, ``seed``,
        ``stems``, ``bed`` and ``measured``. Every numeric value is a Python
        float (never a numpy scalar) so it serialises cleanly through pydantic.
    """
    loudness_delta_lu = _loudness_lu(shaped_bus, sr) - _loudness_lu(clean_bus, sr)
    hf_excess_db = _band_energy_db(shaped_bus, sr, HF_BAND_HZ) - _band_energy_db(
        clean_bus, sr, HF_BAND_HZ
    )
    crest_delta_db = crest_db(clean_bus) - crest_db(shaped_bus)
    centroid_delta_hz = _spectral_centroid_hz(shaped_bus, sr) - _spectral_centroid_hz(
        clean_bus, sr
    )

    # A bed that never ran contributes nothing: its levels are reported as zero
    # and ``applied``/``transient`` are the reader's gate. Reporting the
    # profile's nominal levels for a bed that did not apply would let a reader
    # subtract a bed that is not there.
    bed_applied = bed.get("status") == "active"
    if bed_applied:
        hiss_dbfs = float(bed.get("hiss_level_dbfs", 0.0))
        crackle_dbfs = float(bed.get("crackle_level_dbfs", 0.0))
        crackle_rate_per_s = float(bed.get("crackle_rate_per_s", 0.0))
    else:
        hiss_dbfs = 0.0
        crackle_dbfs = 0.0
        crackle_rate_per_s = 0.0
    # The bed's transient content is its crackle: ticks are program to a
    # spike-gated stage (S4.2), so the reader needs to know they are there.
    transient = bool(bed_applied and crackle_rate_per_s > 0.0)

    if vocal_audio is None or np.asarray(vocal_audio).size == 0:
        vocal_band_ratio = 0.0
    else:
        vocal_band_ratio = _band_ratio(
            vocal_audio, sr if vocal_sr is None else vocal_sr, VOCAL_BAND_HZ
        )
    band_limited_vocal = bool(vocal_band_ratio >= BAND_LIMITED_VOCAL_RATIO)

    return {
        "recipe_schema": RECIPE_SCHEMA,
        "profile": profile,
        "seed": int(seed),
        "stems": {name: list(stages.get(name, ())) for name in STEM_NAMES},
        "bed": {
            "applied": bed_applied,
            "transient": transient,
            "hiss_dbfs": hiss_dbfs,
            "crackle_dbfs": crackle_dbfs,
            "crackle_rate_per_s": crackle_rate_per_s,
        },
        "measured": {
            "loudness_delta_lu": float(loudness_delta_lu),
            "hf_excess_db": float(hf_excess_db),
            "crest_delta_db": float(crest_delta_db),
            "centroid_delta_hz": float(centroid_delta_hz),
            "band_limited_vocal": band_limited_vocal,
            "vocal_band_ratio": float(vocal_band_ratio),
        },
    }
