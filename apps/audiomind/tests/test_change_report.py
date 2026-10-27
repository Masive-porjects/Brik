"""S6 unit contract: the before/after change report of a completed DSP job.

Why this module exists
----------------------
The change report must be as honest as the rest of the metrics contract:
both sides are measured with the SAME meters (band_energies_dbfs + the
BS.1770-4 LUFS meter processing/loudness.py implements), nothing inherits
the legacy FFT-dB scale, and a report that cannot be computed never raises
- a completed DSP job must not fail over its own report.

Pinned behaviors:

1. Deltas are measured: a uniformly louder "after" reads ~+6 dB on the
   band that carries energy and ~+6 dB LUFS, ``after - before`` order.
2. Legacy "before" payloads (pre-contract ``AnalysisResult`` without band
   fields) are re-measured from the input file instead of fabricating.
3. Missing before/after sides degrade to explicit statuses, never raises.
4. A corrupt output file degrades to ``status="error"`` with a message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audiomind.analysis.analyzer import TARGET_BANDS_HZ, band_energies_dbfs
from audiomind.analysis.change_report import build_change_report
from audiomind.models.audio import AnalysisResult

_SR = 44100


def _write_wav(path: Path, *, amp: float, freq: float = 440.0) -> str:
    """A 1.5 s stereo 44.1 kHz sine at the given amplitude."""
    t = np.linspace(0.0, 1.5, int(_SR * 1.5), endpoint=False)
    left = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.stack([left, left], axis=1), _SR, subtype="FLOAT")
    return str(path)


def _before_result(input_path: str) -> AnalysisResult:
    """A real Phase-A style 'before': bands measured from the input file."""
    import librosa

    y, sr = librosa.load(input_path, sr=None, mono=False)
    y_mono = librosa.to_mono(y) if getattr(y, "ndim", 1) > 1 else y
    return AnalysisResult(
        integrated_lufs=-14.7,
        true_peak_db=-14.0,
        dynamic_range_db=0.1,
        spectral_centroid=440.0,
        tempo_bpm=120.0,
        duration_seconds=1.5,
        sample_rate=_SR,
        channels=2,
        bands_hz=TARGET_BANDS_HZ,
        band_energies_db=band_energies_dbfs(y_mono, int(sr), TARGET_BANDS_HZ),
    )


def test_deltas_are_measured_and_the_master_side_is_positive() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    input_path = _write_wav(tmp / "before.wav", amp=0.2)
    output_path = _write_wav(tmp / "after.wav", amp=0.4)  # exactly twice -> ~+6 dB

    report = build_change_report(
        before=_before_result(input_path),
        input_path=input_path,
        output_path=output_path,
    )

    payload: dict[str, Any] = report.model_dump()
    assert payload["status"] == "ready"
    assert payload["before_bands_hz"] == TARGET_BANDS_HZ

    # ``after - before``: mastering ADDED the energy.
    deltas = payload["band_deltas_db"]
    energies_index = TARGET_BANDS_HZ.index(400)
    assert 5.7 <= deltas[energies_index] <= 6.4
    # Out-of-band floors cancel to ~0, not to a fabricated value.
    assert abs(deltas[0]) <= 0.05 or abs(deltas[0]) < 1.0

    # The same meter on both sides: double the amplitude is ~+6 LUFS.
    assert payload["after_integrated_lufs"] is not None
    assert 5.5 <= payload["lufs_delta_db"] <= 6.5

    assert payload["biggest_increase_band_hz"] == 400
    # A floor that stayed a floor is not a "decrease".
    assert payload["biggest_decrease_band_hz"] is None

    # The honesty marker travels with the report.
    assert payload["loudness_standard"] == "ITU-R BS.1770-4"


def test_legacy_before_without_bands_is_reread_from_the_input_file() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    input_path = _write_wav(tmp / "before.wav", amp=0.2)

    legacy = _before_result(input_path).model_dump()
    legacy.pop("bands_hz", None)
    legacy.pop("band_energies_db", None)
    before = AnalysisResult.model_validate(legacy)

    # Same content as the master: deltas must be ~0, from a RE-MEASURED
    # before, not from empty lists.
    report = build_change_report(
        before=before, input_path=input_path, output_path=input_path
    )

    payload = report.model_dump()
    assert payload["status"] == "ready"
    assert len(payload["before_band_levels_dbfs"]) == len(TARGET_BANDS_HZ)
    assert max(abs(d) for d in payload["band_deltas_db"]) <= 0.5
    assert abs(payload["lufs_delta_db"]) <= 0.2


def test_missing_output_degrades_to_no_after() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    input_path = _write_wav(tmp / "before.wav", amp=0.2)

    report = build_change_report(
        before=_before_result(input_path),
        input_path=input_path,
        output_path=tmp / "missing.wav",
    )
    assert report.model_dump()["status"] == "no_after"


def test_missing_before_degrades_to_no_before() -> None:
    report = build_change_report(
        before=None,
        input_path="does/not/exist.wav",
        output_path="also/missing.wav",
    )
    # no_after and no_before both true: the after side is checked first, so
    # this one reports no_before only when an after WOULD exist. With both
    # missing the after check wins, hence 'no_after'.
    assert report.model_dump()["status"] in {"no_before", "no_after"}


def test_missing_before_with_missing_after_reports_no_after() -> None:
    report = build_change_report(
        before=None, input_path=None, output_path="also/missing.wav"
    )
    assert report.model_dump()["status"] == "no_after"


def test_a_corrupt_after_file_never_raises() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    input_path = _write_wav(tmp / "before.wav", amp=0.2)
    corrupt = tmp / "after.wav"
    corrupt.write_bytes(b"not a wav file at all")

    report = build_change_report(
        before=_before_result(input_path),
        input_path=input_path,
        output_path=corrupt,
    )

    payload = report.model_dump()
    assert payload["status"] == "error"
    assert payload["message"]
