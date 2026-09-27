"""Tests for vocal register / f0 detection (Eje A: adaptive voice treatment).

RED origin (2026-09-22): the backend analyzed voice without knowing its
pitch/register — analyzer.py:178 ``analyze_audio()`` computed rms, spectral
centroid, flatness, zero-crossing rate and beat_track, but ZERO pitch.
These tests pin the new librosa.pyin-based detection:

- T1: pyin over the (vocal) signal produces a credible f0 median.
- T2: phrase-aware median f0, robust to silence / octave errors / pyin blips.
- T3: register classification with explicit HIPOTHESIS thresholds.
- T4: AnalysisResult exposes the register transparently (fields + wiring).

The thresholds are marked HIPOTHESIS a calibrar (no source value): the f0
depends on the real signal, and the backend must never invent a register.
"""
import sys

sys.path.insert(0, "src")

import wave

import numpy as np

from audiomind.analysis.analyzer import analyze_audio
from audiomind.analysis.register_detection import (
    classify_register,
    detect_vocal_register,
    median_f0_per_phrase,
)
from audiomind.models.audio import AnalysisResult

SR = 22050


def _vocal(f0_hz: float, duration: float = 4.0, noise: float = 0.005,
           gap_from: float | None = None, gap_to: float | None = None) -> np.ndarray:
    """Harmonic-rich synthetic voice at ``f0_hz`` (pyin-friendly).

    A sine + 2nd/3rd/4th harmonics plus a tiny noise floor: the fundamental
    is unambiguous, so any detection error is a real pyin/aggregation issue.
    An optional silent gap splits the signal into two voiced phrases.
    """
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    phase = 2 * np.pi * f0_hz * t
    y = (
        np.sin(phase)
        + 0.5 * np.sin(2 * phase)
        + 0.35 * np.sin(3 * phase)
        + 0.2 * np.sin(4 * phase)
    )
    rng = np.random.default_rng(7)
    y = y + noise * rng.standard_normal(len(t))
    if gap_from is not None:
        y = y * ((t < gap_from) | (t > gap_to))
    return y * (0.7 / max(abs(y)))


def _write_wav(path, y: np.ndarray, sr: int) -> None:
    """Write a 16-bit mono WAV (stdlib only, same as tests/create_test_wav.py)."""
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ── T1: librosa.pyin over the (vocal) signal ────────────────────────────

def test_t1_median_tracks_female_like_f0():
    det = detect_vocal_register(_vocal(261.63), SR)  # C4
    assert det.median_f0_hz is not None
    assert 230 <= det.median_f0_hz <= 295           # within ~12% of 261.63
    assert det.voiced_ratio > 0.5
    assert det.register in {"grave", "medio", "agudo"}


def test_t1_median_tracks_male_like_f0():
    det = detect_vocal_register(_vocal(110.0), SR)  # A2
    assert det.median_f0_hz is not None
    assert 95 <= det.median_f0_hz <= 125            # within ~12% of 110
    assert det.register == "grave"


# ── T2: phrase-aware median, robust to silence / octaves / errors ───────

def test_t2_silence_yields_no_register():
    det = detect_vocal_register(np.zeros(int(SR * 3)), SR)
    assert det.median_f0_hz is None
    assert det.register is None
    assert det.voiced_ratio < 0.05


def test_t2_pure_noise_yields_no_register():
    """White noise must NOT invent a register: pyin marks some frames voiced,
    so the voice-presence guard (HIPOTHESIS ratio) must reject the signal."""
    rng = np.random.default_rng(3)
    det = detect_vocal_register(rng.standard_normal(int(SR * 3)), SR)
    assert det.median_f0_hz is None
    assert det.register is None


def test_t2_phrases_segment_by_silence():
    """A silent gap splits the signal into >=2 voiced phrases; each phrase
    median stays credible (no frame-solo noise)."""
    y = _vocal(110.0, duration=4.0, gap_from=1.5, gap_to=2.5)
    det = detect_vocal_register(y, SR)
    assert len(det.phrase_medians_hz) >= 2
    for pm in det.phrase_medians_hz:
        assert 95 <= pm <= 125


def test_t2_median_robust_to_octave_jump_errors():
    """Median per phrase survives octave-jump frames that would poison a mean:
    a few frames at 2x/0.5x f0 must not move the reported phrase."""
    f0 = np.array([110.0] * 90 + [440.0] * 10 + [55.0] * 5)
    voiced = np.ones(len(f0), dtype=bool)
    medians = median_f0_per_phrase(f0, voiced)
    assert len(medians) == 1
    assert 100 <= medians[0] <= 120
    assert medians[0] < np.mean(f0[voiced]) - 5  # mean (138.8) is the outlier


def test_t2_short_blips_are_not_phrases():
    """A 3-frame voiced blip inside silence is pyin noise, not a phrase."""
    f0 = np.array([np.nan] * 50 + [110.0] * 3 + [np.nan] * 50)
    voiced = ~np.isnan(f0)
    assert median_f0_per_phrase(f0, voiced, min_frames=5) == []


# ── T3: register classification (HIPOTHESIS thresholds) ─────────────────

def test_t3_register_labels_from_median():
    assert classify_register(100.0) == "grave"
    assert classify_register(200.0) == "medio"
    assert classify_register(300.0) == "agudo"
    assert classify_register(None) is None


# ── T4: transparent exposure in AnalysisResult ──────────────────────────

def test_t4_analysis_result_defaults_are_neutral():
    """Backward compatible: a plain AnalysisResult carries no register."""
    res = AnalysisResult(
        integrated_lufs=-14.0,
        true_peak_db=-1.0,
        dynamic_range_db=8.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=10.0,
        sample_rate=44100,
        channels=2,
    )
    assert res.vocal_median_f0_hz is None
    assert res.vocal_register is None
    assert res.vocal_f0_voiced_ratio == 0.0
    assert res.vocal_phrase_count == 0


def test_t4_analyze_audio_populates_register(tmp_path):
    y = _vocal(110.0, duration=3.0)
    path = tmp_path / "vocal.wav"
    _write_wav(path, y, SR)
    res = analyze_audio(path)
    assert res.vocal_register == "grave"
    assert res.vocal_median_f0_hz is not None
    assert 95 <= res.vocal_median_f0_hz <= 125
    assert res.vocal_f0_voiced_ratio > 0.5


def test_t4_analyze_audio_never_invents_register_on_noise(tmp_path):
    rng = np.random.default_rng(3)
    path = tmp_path / "noise.wav"
    _write_wav(path, rng.standard_normal(int(SR * 3)), SR)
    res = analyze_audio(path)
    assert res.vocal_median_f0_hz is None
    assert res.vocal_register is None