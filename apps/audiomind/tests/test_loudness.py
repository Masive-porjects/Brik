"""Objective tests for the BS.1770-4 loudness meter (Sprint 1 acceptance).

Covers: absolute calibration on a synthetic tone, absolute + relative
gating, per-channel weighting, ffmpeg ``ebur128`` oracle agreement, and
silence robustness.
"""
import sys

sys.path.insert(0, "src")

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import sosfreqz

from audiomind.processing.engine import target_lufs
from audiomind.processing.loudness import (
    ABS_ZERO_OFFSET,
    integrated_loudness,
    k_weighting_sos,
    match_lufs,
    measure_lufs,
    momentary_loudness,
    short_term_loudness,
)
from audiomind.processing.truepeak import measure_lufs as tp_measure_lufs

SR = 48000
TONE_FREQ = 997.0  # prime — avoids FFT bin alignment in band-energy helpers


def _tone(rms_db: float, seconds: float, sr: int = SR) -> np.ndarray:
    """Mono sine at exactly ``rms_db`` dBFS RMS (peak = rms * sqrt(2))."""
    n = int(sr * seconds)
    t = np.arange(n) / sr
    return np.sin(2.0 * np.pi * TONE_FREQ * t) * np.sqrt(2.0) * 10.0 ** (rms_db / 20.0)


def _k_weighting_gain_db(sr: int, freq: float) -> float:
    """Magnitude (dB) of the designed K-weighting curve at ``freq``."""
    _, h = sosfreqz(k_weighting_sos(sr), worN=[2.0 * np.pi * freq / sr])
    return float(20.0 * np.log10(abs(h[0])))


# ── 1. Absolute calibration ───────────────────────────────────────────


def test_sine_integrated():
    sr = SR
    rms_db = -20.0
    x = _tone(rms_db, seconds=10.0, sr=sr)
    measured = integrated_loudness(x, sr)
    # Expected: rms_db + K-weighting@997Hz + the -0.691 calibration offset.
    expected = rms_db + _k_weighting_gain_db(sr, TONE_FREQ) + ABS_ZERO_OFFSET
    assert measured == pytest.approx(expected, abs=0.3)
    # Roadmap band: a stationary tone sits within 1 LU of its RMS level.
    assert abs(measured - rms_db) <= 1.0
    print(
        f"  997 Hz @ -20 dBFS RMS -> {measured:.2f} LUFS "
        f"(K-weighting@{TONE_FREQ:.0f} Hz = {expected - rms_db - ABS_ZERO_OFFSET:+.2f} dB, "
        f"expected {expected:.2f})"
    )


# ── 2. Gating ─────────────────────────────────────────────────────────


def test_gating_silence_excluded():
    sr = SR
    tone = _tone(-20.0, seconds=4.0, sr=sr)  # 4 s tone + 6 s silence
    x = np.concatenate([tone, np.zeros(6 * sr)])
    measured = integrated_loudness(x, sr)
    reference = integrated_loudness(tone, sr)
    assert measured == pytest.approx(reference, abs=1.0)
    assert measured > -40.0  # silence must not drag the measurement down
    print(f"  4 s tone + 6 s silence -> {measured:.2f} LUFS (tone alone {reference:.2f})")


def test_gating_relative_tail():
    sr = SR
    tone = _tone(-20.0, seconds=4.0, sr=sr)
    tail = _tone(-45.0, seconds=4.0, sr=sr)  # passes -70 gate, 25 LU below tone
    x = np.concatenate([tone, tail])
    measured = integrated_loudness(x, sr)
    reference = integrated_loudness(tone, sr)
    # Without the RELATIVE gate the -45 LUFS tail would collapse the
    # integrated value to ~-24 LUFS; with it the tail is rejected.
    assert measured == pytest.approx(reference, abs=1.0)
    assert measured - reference > -2.0
    print(f"  tone + 25 dB-down tail -> {measured:.2f} LUFS (tone alone {reference:.2f})")


# ── 3. Channels / weights ─────────────────────────────────────────────


def test_stereo_weights():
    sr = SR
    mono = _tone(-20.0, seconds=5.0, sr=sr)
    m_mono = integrated_loudness(mono, sr)

    # Identical L/R: BS.1770-4 SUMS channel power, so stereo is +10*log10(2)
    # = +3.01 LU over mono (verified against ffmpeg ebur128).
    stereo_ident = np.stack([mono, mono])
    m_stereo = integrated_loudness(stereo_ident, sr)
    assert m_stereo == pytest.approx(m_mono + 10.0 * np.log10(2.0), abs=0.3)

    # Signal only in the left channel: the right channel contributes
    # nothing, so this equals the mono measurement.
    stereo_left = np.stack([mono, np.zeros_like(mono)])
    assert integrated_loudness(stereo_left, sr) == pytest.approx(m_mono, abs=0.3)
    print(
        f"  mono {m_mono:.2f} | stereo L==R {m_stereo:.2f} (+{m_stereo - m_mono:.2f} LU) "
        f"| left-only {integrated_loudness(stereo_left, sr):.2f} LUFS"
    )


# ── 4. Oracle comparison (ffmpeg ebur128, best-effort) ────────────────


def _ffmpeg_has_ebur128() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        )
        haystack = (proc.stdout or "") + (proc.stderr or "")
        return "ebur128" in haystack
    except Exception:
        return False


FFMPEG_EBUR128 = _ffmpeg_has_ebur128()


def _ffmpeg_integrated_lufs(wav_path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-nostats", "-hide_banner", "-i", str(wav_path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    # Per-interval lines also print "I: ... LUFS" (they ramp up to the
    # real value), so the LAST occurrence is the summary block.
    last = None
    for line in text.splitlines():
        if "LUFS" not in line:
            continue
        parts = line.split()
        for i, p in enumerate(parts):
            if p == "I:" and i + 1 < len(parts):
                last = float(parts[i + 1])
    if last is not None:
        return last
    raise RuntimeError(f"could not parse ebur128 output:\n{text}")


@pytest.mark.skipif(not FFMPEG_EBUR128, reason="ffmpeg ebur128 filter not available")
def test_oracle_ffmpeg_ebur128():
    sr = SR
    x = _tone(-20.0, seconds=10.0, sr=sr)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "tone_997.wav"
        sf.write(str(wav), x, sr, subtype="FLOAT")
        oracle = _ffmpeg_integrated_lufs(wav)
    ours = integrated_loudness(x, sr)
    assert abs(ours - oracle) <= 0.5, f"ours={ours:.2f} vs ffmpeg={oracle:.2f}"
    print(f"  oracle ffmpeg ebur128: {oracle:.2f} LUFS | ours: {ours:.2f} LUFS | diff {abs(ours - oracle):.2f}")


# ── 5. Robustness ─────────────────────────────────────────────────────


def test_silence_robustness():
    sr = SR
    silence = np.zeros((2, int(3.0 * sr)))

    assert integrated_loudness(silence, sr) == -np.inf
    assert measure_lufs(silence, sr) == pytest.approx(-70.0)

    gain = match_lufs(silence, sr, -14.0)
    assert np.isfinite(gain)
    assert gain == pytest.approx(12.0)  # clamped to max, never NaN/inf

    out = target_lufs(silence, sr, -14.0)
    assert out.shape == silence.shape
    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out)) == 0.0  # silence stays silence

    # Tiny signal: gain is finite and clamped, output finite.
    tiny = np.full((2, int(0.5 * sr)), 1e-12)
    out2 = target_lufs(tiny, sr, -14.0)
    assert np.all(np.isfinite(out2))


def test_delegation_truepeak():
    x = _tone(-20.0, seconds=3.0)
    assert tp_measure_lufs(x, SR) == measure_lufs(x, SR)
    stereo = np.stack([x, x])
    assert tp_measure_lufs(stereo, SR) == measure_lufs(stereo, SR)


def test_sliding_windows():
    sr = SR
    x = _tone(-20.0, seconds=6.0, sr=sr)
    m = momentary_loudness(x, sr)
    s = short_term_loudness(x, sr)
    assert m.shape[0] > 10
    assert s.shape[0] > 3
    assert np.all(np.isfinite(m)) and np.all(np.isfinite(s))
    # Stationary tone: sliding windows hover around the integrated value.
    assert abs(np.median(m) - integrated_loudness(x, sr)) < 1.0
