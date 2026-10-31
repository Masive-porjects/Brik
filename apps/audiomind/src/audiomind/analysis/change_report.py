"""Before/after change report for completed DSP jobs (metrics contract, S6).

What this module is
-------------------
A completed master/mix run changes the audio; the Studio renders what
changed. This module measures BOTH sides with the same meters the
agent-facing contract already uses (``band_energies_dbfs`` +
BS.1770-4 LUFS), so the deltas are honest in a scale that does not depend
on the analysis length.

Why not ``reference_compare`` itself
------------------------------------
``reference_compare.compare_tracks`` answers a different question:
user-master vs an uploaded REFERENCE track, on the internal FFT-dB scale
its consumers share. This module deliberately reuses its CONVENTIONS
(per-band deltas, biggest band hints, LUFS delta, never-raise statuses)
but measures on the dBFS contract scale, so it composes with the Phase-A
metrics JSON instead of mixing scales.
"""

from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from audiomind.analysis.analyzer import TARGET_BANDS_HZ, band_energies_dbfs
from audiomind.models.audio import AnalysisResult, ChangeReport
from audiomind.processing.loudness import LOUDNESS_STANDARD, measure_lufs

logger = logging.getLogger(__name__)


def _measure_file(path: Path) -> tuple[list[float], float, float]:
    """Bands (dBFS, aligned to TARGET_BANDS_HZ), LUFS and true peak — one decode.

    Mirrors ``analyzer.analyze_audio``: full multi-channel signal for the
    LUFS meter, mono mix for the band masks.
    """
    y, sr = librosa.load(str(path), sr=None, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y], axis=0)
    y_mono = librosa.to_mono(y)
    bands = band_energies_dbfs(y_mono, int(sr), TARGET_BANDS_HZ)
    lufs = measure_lufs(y, sr)
    peak = float(np.max(np.abs(y)))
    true_peak_db = 20.0 * np.log10(max(peak, 1e-10))
    return bands, float(lufs), float(true_peak_db)


def _rounded(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def build_change_report(
    *,
    before: AnalysisResult | None = None,
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> ChangeReport:
    """Measure one completed job in the agent-facing scale.

    ``before`` prefers the session's own Phase-A analysis (the bands it
    stores are already dBFS); sessions analyzed before the contract get
    their before-side re-measured from ``input_path`` so legacy rows get a
    real report instead of fabricated zeros. Everything degrades:
    ``no_after`` when the output is gone, ``no_before`` when no input is
    recoverable, ``error`` when measurement itself fails — never raises.
    """
    try:
        if output_path is None or not Path(output_path).exists():
            return ChangeReport(
                status="no_after",
                message="The job's output file is not present for measurement",
            )

        before_bands: list[float] = []
        before_lufs = _rounded(before.integrated_lufs) if before else None
        before_tp = _rounded(before.true_peak_db) if before else None
        from_storage = bool(
            before
            and before.bands_hz == TARGET_BANDS_HZ
            and before.band_energies_db
        )
        if from_storage and before is not None:
            before_bands = list(before.band_energies_db)
        elif input_path is not None and Path(input_path).exists():
            before_bands, before_lufs, before_tp = _measure_file(Path(input_path))
        else:
            return ChangeReport(
                status="no_before",
                message=(
                    "No usable before-side: the session holds no contract "
                    "bands and the input file is not available"
                ),
            )

        after_bands, after_lufs, after_tp = _measure_file(Path(output_path))

        deltas = [
            round(a - b, 2) for a, b in zip(after_bands, before_bands, strict=False)
        ]
        up_index = int(np.argmax(deltas)) if deltas else None
        down_index = int(np.argmin(deltas)) if deltas else None

        def _band_at(index: int | None, *, sign: float) -> int | None:
            if index is None or not deltas or deltas[index] * sign <= 0.05:
                # Only a band that actually moved counts as the headline;
                # floors that equalled out render as None, not noise.
                return None
            return TARGET_BANDS_HZ[index]

        lufs_delta = (
            round(float(after_lufs) - float(before_lufs), 2)
            if before_lufs is not None
            else None
        )
        tp_delta = (
            round(float(after_tp) - float(before_tp), 2)
            if before_tp is not None
            else None
        )

        return ChangeReport(
            status="ready",
            before_bands_hz=list(TARGET_BANDS_HZ),
            before_band_levels_dbfs=[round(b, 2) for b in before_bands],
            after_band_levels_dbfs=[round(b, 2) for b in after_bands],
            band_deltas_db=deltas,
            biggest_increase_band_hz=_band_at(up_index, sign=1.0),
            biggest_decrease_band_hz=_band_at(down_index, sign=-1.0),
            before_integrated_lufs=before_lufs,
            after_integrated_lufs=_rounded(after_lufs),
            lufs_delta_db=lufs_delta,
            before_true_peak_db=before_tp,
            after_true_peak_db=_rounded(after_tp),
            true_peak_delta_db=tp_delta,
            loudness_standard=LOUDNESS_STANDARD,
        )
    except Exception as exc:  # noqa: BLE001 -- the report is the report
        logger.warning("Change report could not be computed: %s", exc)
        return ChangeReport(
            status="error",
            message=str(exc)[:200] or exc.__class__.__name__,
        )
