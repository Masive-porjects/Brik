"""TDD tests for magic frequencies (Paso 02 — per-stem EQ profiles).

RED → GREEN → REFACTOR contract for the Mix Engine step 02:

* ``MAGIC_PROFILES`` carries one EQ band list per stem (drums / bass /
  other / vocals), built from the verified magic-frequencies table
  (Owsinski, *The Mixing Engineer's Handbook*, p. 32, Fig. 5;
  ``docs/proposals/VIABILIDAD_MOTOR_DE_MEZCLA.md`` líneas 78-92).
* Every band is fully documented (``type``/``freq_hz``/``gain_db``/``q``/
  ``source``), cuts come before boosts, cuts use narrow Q, boosts use
  wide Q, and the initial gains stay inside the conservative envelope
  (cuts −1.5..−3 dB, boosts +0.5..+1.5 dB).
* ``apply_stem_eq`` is a bit-exact passthrough when the band list is
  empty or all gains are zero (backend neutrality contract).
* The EQ actually shapes the spectrum: applying the vocals profile must
  move energy DOWN at the 240 Hz boominess cut and UP at the 5 kHz
  presence / 12 kHz air bands (measured with numpy FFT, relative only).
* ``build_mix`` applies ``MAGIC_PROFILES`` by default and records the
  applied bands in ``eq_profiles_applied``; an explicit empty profile
  dict keeps the neutral routing of Paso 01.

``split_audio`` is monkeypatched with the same synthetic stand-in as the
Paso 01 test (``tests.test_mix_engine._fake_split``) — the contract under
test is the engine, not the Demucs separator.
"""
import sys
import uuid

sys.path.insert(0, "src")

import numpy as np
import pytest

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.magic_frequencies import MAGIC_PROFILES, apply_stem_eq
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from tests.test_mix_engine import _fake_split

_SR = 44100
#: Contract keys every band must carry (source: task spec — each band is
#: ``{"type", "freq_hz", "gain_db", "q", "source"}`` plus optional "filter").
_REQUIRED_BAND_KEYS = {"type", "freq_hz", "gain_db", "q", "source"}
_VALID_FILTERS = {"peak", "low_shelf", "high_shelf"}
#: Conservative gain envelope (Owsinski p. 33 golden rules + step spec).
_CUT_GAIN_RANGE = (-3.0, -1.5)
_BOOST_GAIN_RANGE = (0.5, 1.5)
#: Q envelope: narrow on cuts, wide on boosts (wide boosts avoid bad phase).
_CUT_Q_RANGE = (1.0, 1.4)
_BOOST_Q_RANGE = (0.5, 0.8)


def _synthetic_kit_tone(sr: int, seconds: float = 1.0) -> np.ndarray:
    """Stereo float32 tone with three sines in the vocals' magic bands.

    Exactly one second at ``sr`` puts 240 / 5000 / 12000 Hz on exact
    ``np.fft.rfft`` bins, so the spectral comparison is bin-sharp and
    windowing-free (integer number of cycles per bin).
    """
    n = int(sr * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    tone = 0.25 * (
        np.sin(2.0 * np.pi * 240.0 * t)
        + np.sin(2.0 * np.pi * 5000.0 * t)
        + np.sin(2.0 * np.pi * 12000.0 * t)
    )
    return np.stack([tone, tone]).astype(np.float32)


def _bin_magnitude(audio: np.ndarray, sr: int, freq: float) -> float:
    """FFT magnitude of channel 0 at the bin nearest ``freq`` Hz."""
    spectrum = np.abs(np.fft.rfft(audio[0]))
    bin_index = round(freq * audio.shape[1] / sr)
    return float(spectrum[bin_index])


class TestMagicProfiles:
    """Structure and documentation contract of ``MAGIC_PROFILES``."""

    def test_profiles_cover_all_stems(self):
        """Exactly the 4 stems, each with a non-empty band list."""
        assert set(MAGIC_PROFILES) == set(STEM_NAMES)
        for name in STEM_NAMES:
            assert MAGIC_PROFILES[name], f"{name} profile is empty"

    def test_each_band_is_fully_documented(self):
        """Every band carries the contract keys, valid type and filter."""
        for name in STEM_NAMES:
            for band in MAGIC_PROFILES[name]:
                assert _REQUIRED_BAND_KEYS <= set(band), f"{name}: {band}"
                assert band["type"] in {"cut", "boost"}, f"{name}: {band}"
                assert band["freq_hz"] > 0.0, f"{name}: {band}"
                assert band["q"] > 0.0, f"{name}: {band}"
                assert isinstance(band["source"], str) and band["source"], (
                    f"{name}: empty source"
                )
                assert band.get("filter", "peak") in _VALID_FILTERS, (
                    f"{name}: {band}"
                )

    def test_cuts_come_before_boosts(self):
        """Golden rule (p. 33): all cuts first, boosts after."""
        for name in STEM_NAMES:
            seen_boost = False
            for band in MAGIC_PROFILES[name]:
                if band["type"] == "boost":
                    seen_boost = True
                else:
                    assert not seen_boost, (
                        f"{name}: cut {band['freq_hz']} after a boost"
                    )

    def test_gain_envelope_is_conservative(self):
        """Cuts −1.5..−3 dB, boosts +0.5..+1.5 dB (envelope start)."""
        for name in STEM_NAMES:
            for band in MAGIC_PROFILES[name]:
                gain = band["gain_db"]
                if band["type"] == "cut":
                    assert _CUT_GAIN_RANGE[0] <= gain <= _CUT_GAIN_RANGE[1], (
                        f"{name}: cut gain {gain} out of envelope"
                    )
                else:
                    assert _BOOST_GAIN_RANGE[0] <= gain <= _BOOST_GAIN_RANGE[1], (
                        f"{name}: boost gain {gain} out of envelope"
                    )

    def test_q_envelope_narrow_cuts_wide_boosts(self):
        """Q 1.0–1.4 on cuts, 0.5–0.8 on boosts."""
        for name in STEM_NAMES:
            for band in MAGIC_PROFILES[name]:
                q = band["q"]
                if band["type"] == "cut":
                    assert _CUT_Q_RANGE[0] <= q <= _CUT_Q_RANGE[1], (
                        f"{name}: cut Q {q} not narrow"
                    )
                else:
                    assert _BOOST_Q_RANGE[0] <= q <= _BOOST_Q_RANGE[1], (
                        f"{name}: boost Q {q} not wide"
                    )


class TestApplyStemEq:
    """Neutrality and spectral behaviour of ``apply_stem_eq``."""

    def test_empty_bands_is_bit_exact_passthrough(self):
        """``[]`` returns the input untouched (identity, no pedalboard)."""
        audio = _synthetic_kit_tone(_SR)
        out = apply_stem_eq(audio, _SR, [])
        assert out is audio
        assert np.array_equal(out, audio)

    def test_zero_gain_bands_is_bit_exact_passthrough(self):
        """All-zero gains also bypass without touching the array."""
        audio = _synthetic_kit_tone(_SR)
        zero_bands = [
            {"type": "boost", "freq_hz": 5000.0, "gain_db": 0.0, "q": 0.6,
             "source": "test"},
            {"type": "cut", "freq_hz": 240.0, "gain_db": 0.0, "q": 1.3,
             "source": "test"},
        ]
        out = apply_stem_eq(audio, _SR, zero_bands)
        assert out is audio
        assert np.array_equal(out, audio)

    def test_vocal_profile_shapes_spectrum(self):
        """Energy drops at the 240 Hz boominess cut, rises at 5 kHz / 12 kHz."""
        audio = _synthetic_kit_tone(_SR)
        shaped = apply_stem_eq(audio, _SR, MAGIC_PROFILES["vocals"])
        assert not np.array_equal(shaped, audio), "EQ must change the signal"
        assert _bin_magnitude(shaped, _SR, 240.0) < (
            _bin_magnitude(audio, _SR, 240.0) * 0.95
        ), "240 Hz boominess cut did not reduce energy"
        assert _bin_magnitude(shaped, _SR, 5000.0) > (
            _bin_magnitude(audio, _SR, 5000.0) * 1.05
        ), "5 kHz presence boost did not increase energy"
        assert _bin_magnitude(shaped, _SR, 12000.0) > (
            _bin_magnitude(audio, _SR, 12000.0) * 1.05
        ), "12 kHz air shelf did not increase energy"


class TestMixEngineProfiles:
    """Integration: profiles plug into the Paso 01 routing pipeline."""

    def test_build_mix_applies_magic_profiles_by_default(self, tmp_path,
                                                         monkeypatch):
        """No ``profiles`` arg ⇒ ``MAGIC_PROFILES`` recorded per stem."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(str(uuid.uuid4()), str(tmp_path / "input.wav"))
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        for stem in result["analysis"].values():
            assert "integrated_lufs" in stem
            assert "dynamic_range_db" in stem
            assert "spectral_centroid" in stem
        assert result["duration_seconds"] == pytest.approx(1.25, abs=0.01)

    def test_build_mix_empty_profiles_is_neutral(self, tmp_path, monkeypatch):
        """``profiles={}`` keeps the Paso 01 neutral routing (no EQ)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), profiles={}
        )
        assert result["eq_profiles_applied"] == {}
        assert set(result["analysis"]) == set(STEM_NAMES)