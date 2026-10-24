"""Smoke test for the dynamic proportional mastering pipeline."""
import sys

sys.path.insert(0, "src")

import numpy as np
import soundfile as sf

from audiomind.models.audio import MasteringParameters
from audiomind.processing.engine import (
    gain_stage,
    process_audio,
    target_lufs,
)
from audiomind.processing.presets import get_preset, list_presets
from audiomind.processing.spatial import mid_side_encode


def test_gain_stage():
    audio = np.random.randn(2, 44100) * 0.1
    normed, gain_db = gain_stage(audio)
    peak = np.max(np.abs(normed))
    peak_db = 20 * np.log10(peak)
    assert abs(peak_db - (-6.0)) < 0.1, f"Expected -6 dBFS, got {peak_db:.1f}"
    print(f"  gain_stage OK: peak at {peak_db:.1f} dBFS")


def test_gain_stage_silent():
    audio = np.zeros((2, 44100))
    normed, gain_db = gain_stage(audio)
    assert gain_db == 0.0
    print("  gain_stage silent OK")


def test_target_lufs():
    sr = 44100
    audio = np.random.randn(2, sr) * 0.1
    result = target_lufs(audio, sr, -14.0)
    assert result.shape == audio.shape
    print("  target_lufs OK")


def test_presets_structure():
    presets = list_presets()
    assert len(presets) == 8
    for p in presets:
        assert "name" in p
        assert "display_name" in p
        assert "style" in p
        assert "description" in p
        assert "target_genres" in p
    # Verify internal structure
    full = get_preset("universal")
    assert "eq_bands" in full
    assert "compressor" in full
    assert "ratio" in full["compressor"]
    assert "target_lufs" in full
    assert "limiter_ceiling_db" in full
    print("  presets structure OK")


def _write_stereo_wav(path, sr=44100, duration=0.5, seed=0):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    noise = rng.standard_normal(int(sr * duration))
    left = 0.4 * np.sin(2 * np.pi * 440 * t) + 0.1 * noise
    right = 0.4 * np.sin(2 * np.pi * 660 * t) + 0.1 * noise
    x = np.stack([left, right])
    # 32-bit float WAV — the neutral fast-path writes the same format, so the
    # roundtrip is lossless and the bypass can be asserted bit-exactly.
    sf.write(str(path), x.T, sr, subtype="FLOAT")
    return x


def _write_mono_wav(path, sr=44100, duration=0.5):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    mono = 0.4 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(path), mono, sr, subtype="FLOAT")
    return mono


def _read_wav(path):
    arr, sr = sf.read(str(path), always_2d=True)
    return arr.T, sr


def test_neutral_defaults_are_bit_exact_bypass(tmp_path):
    """MasteringParameters() with all default values must be a bit-exact bypass:
    the delivered master is byte-identical (sample-identical) to the input."""
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_stereo_wav(in_path)

    result = process_audio(in_path, out_path, MasteringParameters())

    in_arr, in_sr = _read_wav(in_path)
    out_arr, out_sr = _read_wav(out_path)
    assert in_sr == out_sr
    assert in_arr.shape == out_arr.shape
    msg = "neutral defaults must be bit-exact"
    np.testing.assert_array_equal(in_arr, out_arr, err_msg=msg)

    # The delivered audio is byte-identical: hash of the sample data matches.
    # (We hash the PCM sample bytes, not the raw container — libsndfile may
    # emit different WAV header bytes depending on process state, but the audio
    # samples themselves are proven identical above and by these hashes.)
    import hashlib
    h_in = hashlib.sha256(np.ascontiguousarray(in_arr).tobytes()).hexdigest()
    h_out = hashlib.sha256(np.ascontiguousarray(out_arr).tobytes()).hexdigest()
    assert h_in == h_out

    # Response keeps the normal shape/keys.
    for key in ("output_path", "sample_rate", "channels", "duration_seconds",
                "true_peak_db", "integrated_lufs", "crest_factor_db",
                "limiter_ceiling_db", "output_bit_depth", "codec_pre_matching"):
        assert key in result


def test_neutral_mono_defaults_are_bit_exact_bypass(tmp_path):
    """Same bit-exact bypass for a MONO input with default params."""
    in_path = tmp_path / "in_mono.wav"
    out_path = tmp_path / "out_mono.wav"
    _write_mono_wav(in_path)

    result = process_audio(in_path, out_path, MasteringParameters())

    in_arr, in_sr = _read_wav(in_path)
    out_arr, out_sr = _read_wav(out_path)
    assert in_sr == out_sr
    assert in_arr.shape == out_arr.shape
    np.testing.assert_array_equal(in_arr, out_arr)
    assert result["channels"] == 1


def test_mono_does_not_crash_with_spatial_block_active(tmp_path):
    """A mono WAV with the Claridad spatial block active (clarity_wet > 0) must
    complete without IndexError and produce a valid master."""
    in_path = tmp_path / "in_mono.wav"
    out_path = tmp_path / "out_mono.wav"
    _write_mono_wav(in_path)

    result = process_audio(
        in_path, out_path, MasteringParameters(clarity_wet=0.5)
    )

    out_arr, out_sr = _read_wav(out_path)
    assert out_sr > 0
    assert out_arr.shape[0] > 0
    assert np.all(np.isfinite(out_arr))
    assert np.isfinite(result["true_peak_db"])
    assert np.isfinite(result["integrated_lufs"])


def test_mid_side_encode_handles_mono():
    """mid_side_encode must accept mono (1, samples) — upmix so side == 0."""
    t = np.linspace(0, 0.5, 22050, endpoint=False)
    mono = 0.4 * np.sin(2 * np.pi * 440 * t)
    mid, side = mid_side_encode(mono.reshape(1, -1))
    np.testing.assert_allclose(mid, mono * np.sqrt(2), atol=1e-10)
    np.testing.assert_allclose(side, 0.0, atol=1e-12)
    assert mid.shape == mono.shape


if __name__ == "__main__":
    print("=== Smoke Tests ===")
    test_gain_stage()
    test_gain_stage_silent()
    test_target_lufs()
    test_presets_structure()
    print("\nAll checks passed!")
