"""TDD tests for the per-stem dynamics + bus compressor (Mix Engine Paso 05).

RED → GREEN → REFACTOR contract for the DYNAMICS stage of the DAW chain
(fader → pan → EQ → compresor → sends, ``VIABILIDAD_MOTOR_DE_MEZCLA.md``
línea 214 — Paso 05 inserts the compressor BETWEEN the EQ and the Paso 04
dimension/sends, and the stereo bus compresses AFTER the stem sum):

* ``STEM_COMPRESSOR_PROFILES`` per role (book págs. 56–57 + plan maestro):
  vocals 4:1 / 4–6 dB GR (transparent, the voice is not squashed); bass
  ∞:1 (implemented as ratio ≥ 20:1) / 3–4 dB GR (the bass stays solid);
  other (guitar) 8:1–10:1 with attack/release AT TEMPO; drums BY SPECTRAL
  SEGMENT (plan: kick 50–100, snare 120–240/5k, hats 8–10k) — Paso 05
  compresses ONLY the kick low band through the existing
  ``LinkwitzRiley4`` crossover (``multiband.py`` 150 Hz / 3 kHz edges)
  and leaves the other bands untouched.
* ``apply_stem_compression``: per-stem compressor built on
  ``AdaptiveCompressor`` (``adaptive_comp.py`` — the engine's
  program-dependent compressor: windowed-RMS threshold + crest-adaptive
  timing + per-frame diagnostics). The profiles load into
  ``AdaptiveCompParams``; GR reported from the DIAGNOSTICS (actual
  reduction, positive dB). Neutral (``{}``/``None``/ratio ≤ 1:1) → THE
  SAME array object (bit-exact bypass — ``adaptive_comp`` returns a copy
  in neutral mode, so the same-object guarantee lives HERE, documented).
* ``apply_bus_compression``: Jerry Finn mix-bus technique (págs. 53–56):
  2–3 dB total GR, attack slow / release fast. ``gr_ok`` = GR ≤ 3.1 dB
  (tolerance documented: 3 dB recipe + 0.1 dB measurement margin). A
  silent bus is a bit-exact no-op (same object).
* Breathing at tempo (pág. 55: "el compresor debe respirar a tempo"):
  ``tempo_release_ms(bpm, divisor)`` = ``60000 / bpm / divisor`` ms — the
  1/8 of the beat (stems) or 1/16 of the beat (bus). A release constant
  of 1/8 beat recovers ~95 % in ≈ 2.3× the constant (~0.29 beats at ANY
  tempo), so the compressor is back to 90–100 % before the next hit
  (pág. 55). Invalid/missing BPM → profile base release, never a crash
  (Alex guard, same policy as the Paso 04 dimension).
* ``build_mix`` grows ``compressor_profiles``: ``None`` ⇒
  ``STEM_COMPRESSOR_PROFILES`` active by default (applied AFTER the EQ,
  BEFORE the dimension/sends; bus compresses after the sum); ``{}`` →
  compressors disabled, exact Paso 04 routing (no ``compressor_report``
  key). Custom dict → only mapped stems appear in the report (panorama
  convention); the bus stage stays active while compressors are enabled.

``split_audio`` is monkeypatched with the same synthetic stand-in as
Paso 01–04 (``tests.test_mix_engine._fake_split``). The recipe GR tests
ride steady tones (crest ≈ 3 dB) so the mean gain reduction is
deterministic; the bus test rides a hot 2-tone sum (peaks ≈ 0 dBFS).
"""
import sys
import uuid

sys.path.insert(0, "src")

import numpy as np
import pytest

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.dynamics import (
    BUS_COMPRESSOR_PROFILE,
    STEM_COMPRESSOR_PROFILES,
    apply_bus_compression,
    apply_stem_compression,
    tempo_release_ms,
)
from audiomind.processing.magic_frequencies import MAGIC_PROFILES
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from tests.test_mix_engine import _fake_split

_SR = 44100
_SECONDS = 1.0
_BUS_TECHNIQUE = "jerry_finn_slow_attack_fast_release"


def _tone(freq: float, amp: float = 0.5, seconds: float = _SECONDS) -> np.ndarray:
    """Stereo (2, N) float32 sine with identical channels (mono-safe),
    exactly like the Paso 01–04 fixtures."""
    n = int(_SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    s = amp * np.sin(2.0 * np.pi * freq * t)
    return np.stack([s, s]).astype(np.float32)


def _hot_bus() -> np.ndarray:
    """Hot stereo bus: two loud tones summed — peaks ≈ 0 dBFS, crest ≈ 6 dB."""
    return (_tone(200.0, 0.5) + _tone(800.0, 0.5)).astype(np.float32)


def _kick_and_hats() -> np.ndarray:
    """Drums stem: kick body (60 Hz) + snare body (2.2 kHz) + hats
    (9 kHz) in SEPARATE spectral bands."""
    return (
        _tone(60.0, 0.5) + _tone(2200.0, 0.3) + _tone(9000.0, 0.3)
    ).astype(np.float32)


def _band_rms(audio: np.ndarray, lo_hz: float, hi_hz: float) -> float:
    """RMS of the FFT magnitude inside [lo, hi] on channel 0 (identical
    channels — one channel suffices)."""
    mono = audio[0]
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / _SR)
    mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    assert np.any(mask), f"no FFT bins in [{lo_hz}, {hi_hz}] Hz"
    return float(np.sqrt(np.mean(spec[mask] ** 2)))


class TestTempoReleaseMs:
    """Tempo breathing formula (book pág. 55): release = 60000/BPM ÷ divisor.

    1/8 of the beat for the stems, 1/16 for the bus — a release constant
    of 1/8 beat recovers ~95 % in ~0.29 beats at any tempo, back to
    90–100 % before the next hit ("el compresor debe respirar a tempo").
    """

    def test_one_eighth_of_beat_at_120(self):
        assert tempo_release_ms(120.0, 8) == 62.5

    def test_one_sixteenth_of_beat_at_120(self):
        assert tempo_release_ms(120.0, 16) == 31.25

    def test_scales_with_bpm(self):
        """Faster tempo → shorter release (60000/BPM/divisor)."""
        assert tempo_release_ms(90.0, 8) == pytest.approx(60000.0 / 90.0 / 8, abs=0.01)
        assert tempo_release_ms(160.0, 16) == (
            pytest.approx(60000.0 / 160.0 / 16, abs=0.01)
        )

    def test_non_positive_bpm_raises(self):
        with pytest.raises(ValueError):
            tempo_release_ms(0.0, 8)
        with pytest.raises(ValueError):
            tempo_release_ms(-120.0, 8)

    def test_non_positive_divisor_raises(self):
        with pytest.raises(ValueError):
            tempo_release_ms(120.0, 0)


class TestStemRecipeGR:
    """GR inside the book recipe ranges (págs. 56–57, plan maestro) on
    deterministic steady tones (crest ≈ 3 dB)."""

    def test_vocals_gr_in_4_to_6(self):
        """Lead voice 4:1, 4–6 dB GR — transparent, never squashed."""
        out, report = apply_stem_compression(
            _tone(440.0), _SR, STEM_COMPRESSOR_PROFILES["vocals"]
        )
        assert report["status"] == "applied"
        assert report["ratio"] == 4.0
        assert 4.0 <= report["gr_db"] <= 6.0
        assert out is not _tone(440.0)
        assert out.shape == (2, int(_SR * _SECONDS))
        assert out.dtype == np.float32
        assert np.all(np.isfinite(out))

    def test_bass_gr_in_3_to_4(self):
        """Bass ∞:1 (ratio 20), 3–4 dB GR — solid, stays put."""
        out, report = apply_stem_compression(
            _tone(60.0), _SR, STEM_COMPRESSOR_PROFILES["bass"]
        )
        assert report["status"] == "applied"
        assert report["ratio"] == 20.0
        assert 3.0 <= report["gr_db"] <= 4.0

    def test_other_gr_in_6_to_9(self):
        """Guitar/accompaniment 8:1–10:1 (9:1 midpoint), GR ≈ 6–9 dB."""
        out, report = apply_stem_compression(
            _tone(330.0), _SR, STEM_COMPRESSOR_PROFILES["other"]
        )
        assert report["status"] == "applied"
        assert report["ratio"] == 9.0
        assert 6.0 <= report["gr_db"] <= 9.0

    def test_drums_band_compressed_within_reasonable_gr(self):
        """Drums: the kick segment (low band) is compressed with a punchy
        recipe; the report names the processed band."""
        out, report = apply_stem_compression(
            _kick_and_hats(), _SR, STEM_COMPRESSOR_PROFILES["drums"]
        )
        assert report["status"] == "applied"
        assert report["band"] == "low"
        assert report["ratio"] == 4.0
        assert 3.0 <= report["gr_db"] <= 7.0
        assert out.shape == _kick_and_hats().shape


class TestDrumsSpectralSegments:
    """Drums process ONLY their band (plan: kick 50–100, snare 120–240/5k,
    hats 8–10k → LR4 150/3k edges)."""

    def test_high_band_passthrough(self):
        """8–10 kHz (hats) content leaves the drums stem ≈ identical."""
        audio = _kick_and_hats()
        out, _ = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["drums"]
        )
        assert _band_rms(out, 8000.0, 10000.0) == pytest.approx(
            _band_rms(audio, 8000.0, 10000.0), rel=0.02
        )

    def test_low_band_compressed(self):
        """The 40–100 Hz region (kick body) is reduced by the band GR."""
        audio = _kick_and_hats()
        out, report = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["drums"]
        )
        assert _band_rms(out, 40.0, 100.0) < 0.82 * _band_rms(audio, 40.0, 100.0)
        assert report["gr_db"] > 0.0

    def test_mid_band_intact(self):
        """The 150–3000 Hz band is not processed in Paso 05 (snare body
        treatment is not part of this step) — band energy ≈ unchanged."""
        audio = _kick_and_hats()
        out, _ = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["drums"]
        )
        assert _band_rms(out, 1500.0, 3000.0) == pytest.approx(
            _band_rms(audio, 1500.0, 3000.0), rel=0.05
        )


class TestBusCompression:
    """Jerry Finn mix bus (págs. 53–56): 2–3 dB GR total, slow attack /
    fast release; ``gr_ok`` = GR ≤ 3.1 dB (3 dB recipe + 0.1 measurement
    tolerance)."""

    def test_hot_bus_gr_within_2_to_3_1(self):
        bus = _hot_bus()
        out, report = apply_bus_compression(bus, _SR)
        assert report["gr_db"] <= 3.1
        assert report["gr_db"] >= 2.0
        assert report["gr_ok"] is True
        assert report["technique"] == _BUS_TECHNIQUE
        assert out.shape == bus.shape
        assert out.dtype == bus.dtype
        assert np.all(np.isfinite(out))

    def test_silent_bus_is_bit_exact_noop(self):
        bus = np.zeros((2, int(_SR * 0.5)), dtype=np.float32)
        out, report = apply_bus_compression(bus, _SR)
        assert out is bus
        assert report["gr_db"] == 0.0
        assert report["gr_ok"] is True


class TestNeutrality:
    """Neutrality contract (spec 08): ratio ≤ 1:1 / empty profile → THE
    SAME array object (bit-exact bypass) — enforced here because
    ``adaptive_comp`` returns a *copy* in ratio-1 mode."""

    def test_empty_profile_same_object(self):
        audio = _tone(440.0)
        out, report = apply_stem_compression(audio, _SR, {})
        assert out is audio
        assert np.array_equal(out, audio)
        assert report["status"] == "neutral"
        assert report["gr_db"] == 0.0
        assert report["ratio"] == 1.0

    def test_ratio_one_profile_same_object_and_array_equal(self):
        audio = _tone(440.0)
        out, report = apply_stem_compression(
            audio, _SR, {"ratio": 1.0, "attack_ms": 5.0, "release_ms": 20.0}
        )
        assert out is audio
        assert np.array_equal(out, audio)
        assert report["status"] == "neutral"

    def test_none_profile_same_object(self):
        audio = _tone(440.0)
        out, report = apply_stem_compression(audio, _SR, None)
        assert out is audio
        assert report["status"] == "neutral"

    def test_drums_neutral_band_compressor_same_object(self):
        audio = _tone(60.0)
        profile = {
            "band": "low",
            "crossover_low_hz": 150.0,
            "crossover_high_hz": 3000.0,
            "band_compressor": {"ratio": 1.0},
        }
        out, report = apply_stem_compression(audio, _SR, profile)
        assert out is audio
        assert report["status"] == "neutral"
        assert report["gr_db"] == 0.0


class TestTempoBreathing:
    """Pág. 55: the compressor breathes at tempo — release derived from the
    measured BPM (1/8 of the beat per stem, 1/16 on the bus); invalid BPM
    falls back to the profile base release, never a crash (Alex guard)."""

    def test_stem_release_locked_to_eighth_beat(self):
        audio = _tone(330.0)
        _, tempo = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["other"], bpm=120.0
        )
        assert tempo["release_ms"] == pytest.approx(
            tempo_release_ms(120.0, 8), abs=0.01
        )
        assert tempo["release_ms"] == pytest.approx(62.5, abs=0.01)

    def test_bus_release_locked_to_sixteenth_beat(self):
        bus = _hot_bus()
        _, tempo = apply_bus_compression(bus, _SR, bpm=120.0)
        assert tempo["release_ms"] == pytest.approx(
            tempo_release_ms(120.0, 16), abs=0.01
        )
        assert tempo["release_ms"] == pytest.approx(31.25, abs=0.01)

    def test_missing_bpm_falls_back_to_profile_release(self):
        """bpm=None/≤ 0 → the profile's static release, no crash."""
        audio = _tone(330.0)
        _, static = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["other"], bpm=None
        )
        assert static["release_ms"] == pytest.approx(
            STEM_COMPRESSOR_PROFILES["other"]["release_ms"], abs=0.01
        )
        _, zero_bpm = apply_stem_compression(
            audio, _SR, STEM_COMPRESSOR_PROFILES["other"], bpm=0.0
        )
        assert zero_bpm["release_ms"] == pytest.approx(
            STEM_COMPRESSOR_PROFILES["other"]["release_ms"], abs=0.01
        )

    def test_bus_missing_bpm_falls_back(self):
        bus = _hot_bus()
        _, static = apply_bus_compression(bus, _SR, bpm=None)
        assert static["release_ms"] == pytest.approx(
            BUS_COMPRESSOR_PROFILE["release_ms"], abs=0.01
        )


class TestMixEngineCompressor:
    """``build_mix`` integration: default on, ``{}`` off, keys intact;
    compressor BETWEEN the EQ and the dimension/sends; bus after the sum."""

    def test_compressor_disabled_no_report_key(self, tmp_path, monkeypatch):
        """``compressor_profiles={}`` → exact Paso 04 routing: no
        ``compressor_report`` key, EQ/pan keys intact."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, dimension_profiles={}, compressor_profiles={},
        )
        assert "compressor_report" not in result
        assert "dimension_report" not in result
        assert "pan_report" not in result
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_compressor_default_active_full_report(self, tmp_path, monkeypatch):
        """``compressor_profiles=None`` → STEM_COMPRESSOR_PROFILES active,
        bus compresses after the sum; Paso 01–04 keys keep their contracts."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), pan_profiles={}
        )
        report = result["compressor_report"]
        assert report["status"] == "active"
        assert set(report["stems"]) == set(STEM_NAMES)
        for entry in report["stems"].values():
            assert set(entry) == {"gr_db", "ratio", "status"}
            assert entry["status"] in {"applied", "neutral"}
            assert isinstance(entry["gr_db"], float)
        bus = report["bus"]
        assert set(bus) == {"gr_db", "gr_ok", "technique"}
        assert bus["technique"] == _BUS_TECHNIQUE
        assert isinstance(bus["gr_ok"], bool)
        assert bus["gr_ok"] is True  # recipe: 2–3 dB total on this material
        # Paso 04 keys keep their contracts next to the new key.
        assert result["dimension_report"]["status"] == "active"
        assert result["dimension_report"]["bpm_used"] == 120.0
        assert "pan_report" not in result
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_compressor_disabled_dimension_stays_paso04(self, tmp_path, monkeypatch):
        """Compressors off does NOT touch the dimension stage: with
        ``dimension_profiles=None`` the Paso 04 dimension still runs."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, compressor_profiles={},
        )
        assert "compressor_report" not in result
        assert result["dimension_report"]["status"] == "active"
        assert result["dimension_report"]["bpm_used"] == 120.0

    def test_compressor_custom_profiles_only_report_mapped_stems(
        self, tmp_path, monkeypatch,
    ):
        """A custom dict maps only some stems: the rest are untouched and
        do not appear in the report (panorama convention); the bus stage
        stays active while compressors are enabled."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 90.0)
        custom = {"vocals": {"ratio": 1.0}}  # neutral profile
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, dimension_profiles={}, compressor_profiles=custom,
        )
        report = result["compressor_report"]
        assert set(report["stems"]) == {"vocals"}
        assert report["stems"]["vocals"] == {
            "gr_db": 0.0, "ratio": 1.0, "status": "neutral",
        }
        assert report["bus"]["gr_ok"] is True

    def test_compressor_works_without_tempo(self, tmp_path, monkeypatch):
        """No measurable BPM (missing input file) → compressor still active
        with profile fallback releases; dimension degrades to no_tempo
        (Alex guards independent per stage)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "missing.wav"),
            pan_profiles={}, compressor_profiles=None,
        )
        assert result["compressor_report"]["status"] == "active"
        assert result["compressor_report"]["bus"]["gr_ok"] is True
        assert result["dimension_report"]["status"] == "no_tempo"