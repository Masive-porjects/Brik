"""External-reference comparison — pure measurement (Phase C, P1-1).

Compares a mastered file against an uploaded external reference file:
per-band spectral energy, integrated loudness, crest factor, stereo
correlation and dynamic range, plus ``reference − master`` deltas and
the biggest-increase/decrease band hints.

Strictly measurement-only: no DSP processing and no audio mutation, so
the neutral contract ("comparison never changes the master") holds by
construction.

Loudness comes from ``measure_lufs`` — the SAME BS.1770 meter the engine
uses for target matching — and crest uses the same mono peak/RMS math as
``analyze_audio``, so there are two sources of truth for these numbers,
not three. ``analyze_audio`` itself is deliberately NOT reused here: its
genre/tempo/already-mastered detection work is irrelevant to a reference
comparison.

This module imports librosa at the top; the API layer pulls it in lazily
(see the ``_lazy_dsp_call`` pattern in ``api/mastering.py``) so FastAPI
startup stays light on low-memory deployments.
"""
from pathlib import Path

import librosa
import numpy as np

from audiomind.analysis.analyzer import TARGET_BANDS_HZ, analyze_band_energies
from audiomind.models.audio import ReferenceComparison
from audiomind.processing.loudness import measure_lra, measure_lufs
from audiomind.processing.spatial import measure_stereo_correlation


def _round1(value: float | None) -> float | None:
    """Round to one decimal, the engine's output convention.

    Coerces through ``float()`` first: ``analyze_band_energies`` returns
    numpy float32 scalars whose ``round()`` would stay float32 (keeping
    binary artifacts like 13.3999996185 instead of 13.4).
    """
    return None if value is None else round(float(value), 1)


def _round3(value: float | None) -> float | None:
    """Round stereo correlation to three decimals (engine convention)."""
    return None if value is None else round(float(value), 3)


def _load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Load audio keeping its channel layout: (channels, samples) for
    stereo, (samples,) for mono — same call as ``analyzer.analyze_audio``.
    """
    y, sr = librosa.load(str(path), sr=None, mono=False)
    return y, int(sr)


def _measure_crest_db(mono: np.ndarray) -> float | None:
    """Crest factor (dB) of a mono signal; None for digital silence.

    Same peak/RMS math as ``analyzer.analyze_audio``; silence cannot
    produce a meaningful ratio, so it stays unmeasurable instead of 0.
    """
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono**2)))
    if peak <= 0.0 or rms <= 0.0:
        return None
    return float(20.0 * np.log10(peak / rms))


def _sub_delta(
    reference: float | None, master: float | None, ndigits: int = 1
) -> float | None:
    """``reference − master`` with None propagation: either side None → None."""
    if reference is None or master is None:
        return None
    return round(float(reference) - float(master), ndigits)


def _biggest_band_hz(deltas: list[float | None], positive: bool) -> float | None:
    """Center frequency of the band with the largest delta in the sign.

    ``positive=True`` → largest positive delta (reference has MORE energy
    there → the master is "too quiet here"); ``positive=False`` → largest
    negative delta (the master is "too loud here"). None when no delta
    carries the requested sign.
    """
    candidates = [
        (hz, delta)
        for hz, delta in zip(TARGET_BANDS_HZ, deltas, strict=False)
        if delta is not None and (delta > 0 if positive else delta < 0)
    ]
    if not candidates:
        return None
    pick = max if positive else min
    return float(pick(candidates, key=lambda pair: pair[1])[0])


def compare_tracks(
    master_path: str | Path | None,
    reference_path: str | Path | None,
) -> ReferenceComparison:
    """Compare a mastered file against an external reference file.

    Args:
        master_path: Path to the mastered output
            (``SessionData.mastered_path``).
        reference_path: Path to the uploaded reference
            (``SessionData.reference_path``).

    Returns:
        A ``ReferenceComparison``. ``status="ready"`` after a full
        comparison; ``"no_master"`` / ``"no_reference"`` when the path is
        absent or does not exist; ``"error"`` when a file cannot be
        decoded or measured (``message`` carries the reason). Never
        raises.

    The deltas are always ``reference − master``. Per-band levels use the
    shared 8-band list (``TARGET_BANDS_HZ``) on MONO (the band-energy
    function expects 1D), while correlation/LUFS/LRA run on the
    channel-preserving load — mono files simply yield ``None``
    correlation.
    """
    if not master_path:
        return ReferenceComparison(
            status="no_master", message="No mastered file path provided."
        )
    if not reference_path:
        return ReferenceComparison(
            status="no_reference", message="No reference file path provided."
        )
    master_path = Path(master_path)
    reference_path = Path(reference_path)
    if not master_path.exists():
        return ReferenceComparison(
            status="no_master", message=f"Mastered file not found: {master_path}"
        )
    if not reference_path.exists():
        return ReferenceComparison(
            status="no_reference", message=f"Reference file not found: {reference_path}"
        )

    try:
        master_audio, master_sr = _load_audio(master_path)
        reference_audio, reference_sr = _load_audio(reference_path)
        if master_audio.size == 0 or reference_audio.size == 0:
            return ReferenceComparison(
                status="error",
                message=(
                    "Comparison failed: one of the files contains no "
                    "audio samples."
                ),
            )

        master_mono = librosa.to_mono(master_audio)
        reference_mono = librosa.to_mono(reference_audio)

        # Per-band levels on MONO (analyze_band_energies expects 1D),
        # rounded to one decimal like the rest of the engine outputs.
        master_bands = [
            _round1(v)
            for v in analyze_band_energies(master_mono, master_sr, TARGET_BANDS_HZ)
        ]
        reference_bands = [
            _round1(v)
            for v in analyze_band_energies(
                reference_mono, reference_sr, TARGET_BANDS_HZ
            )
        ]
        band_deltas = [
            _sub_delta(ref_i, mas_i)
            for mas_i, ref_i in zip(master_bands, reference_bands, strict=False)
        ]

        # Loudness/crest/correlation/LRA. Crest needs mono; the rest
        # accept the channel-preserving load (correlation returns None
        # for non-stereo, which is exactly the mono-reference case).
        master_lufs = _round1(measure_lufs(master_audio, master_sr))
        reference_lufs = _round1(measure_lufs(reference_audio, reference_sr))
        master_crest = _round1(_measure_crest_db(master_mono))
        reference_crest = _round1(_measure_crest_db(reference_mono))
        master_correlation = _round3(measure_stereo_correlation(master_audio))
        reference_correlation = _round3(measure_stereo_correlation(reference_audio))
        master_lra = _round1(measure_lra(master_audio, master_sr))
        reference_lra = _round1(measure_lra(reference_audio, reference_sr))

        return ReferenceComparison(
            status="ready",
            target_bands_hz=list(TARGET_BANDS_HZ),
            master_band_levels_db=master_bands,
            reference_band_levels_db=reference_bands,
            band_deltas_db=band_deltas,
            biggest_increase_band_hz=_biggest_band_hz(band_deltas, positive=True),
            biggest_decrease_band_hz=_biggest_band_hz(band_deltas, positive=False),
            master_lufs_db=master_lufs,
            reference_lufs_db=reference_lufs,
            lufs_delta_db=_sub_delta(reference_lufs, master_lufs),
            master_crest_db=master_crest,
            reference_crest_db=reference_crest,
            crest_delta_db=_sub_delta(reference_crest, master_crest),
            master_correlation=master_correlation,
            reference_correlation=reference_correlation,
            master_lra_lu=master_lra,
            reference_lra_lu=reference_lra,
            lra_delta_lu=_sub_delta(reference_lra, master_lra),
        )
    except Exception as e:
        # Never break the payload: decode/measure failures become a
        # graceful error status instead of a raise.
        return ReferenceComparison(status="error", message=f"Comparison failed: {e}")