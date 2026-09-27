"""TDD tests for the tempo-locked dimension stage (Mix Engine Paso 04).

RED → GREEN → REFACTOR contract for the tempo dimension of the DAW chain
(fader → pan → EQ → compresor → sends, ``VIABILIDAD_MOTOR_DE_MEZCLA.md``
línea 214 — Paso 04 inserts the DELAY + REVERB sends right after the EQ;
the compressor arrives in Paso 05, before the sends):

* ``tempo_delay_ms`` maps a BPM + subdivision to a delay time in ms:
  ``60000 / BPM`` = quarter note (book págs. 39–40), dotted ×1.5,
  triplet ×0.667, half ×2, eighth ÷2, sixteenth ÷4, rounded to 2
  decimals. ``tempo_delay_table`` sweeps BPM 60–160 (book apéndice
  págs. 216–217) for reference validation ±1 ms.
* ``DIMENSION_PROFILES`` per role: vocals = LONGEST reverb (ethereal) +
  BRIGHT return (bright stands out, pág. 37–38: longest → brightest) with
  pre-delay and a quarter-note delay; drums = MEDIUM reverb with HP on the
  return (dense content → cut the lows of the effect, pág. 37–38); bass =
  conservative (shortest + DARK return — dark blends in, the center bass
  is not dirtied); other = medium reverb, neutral-mid return, optional
  eighth delay.
* ``apply_return_eq``: bright = ~+3 dB shelf above 8–12 kHz, dark = LP
  ~< 6 kHz, HP/LP cut when ``hp_hz``/``lp_hz`` are set; neutral →
  passthrough (same array object).
* ``apply_stem_dimension``: delay (the ``delay.py`` circular buffer) +
  reverb (the ``reverb.py`` Schroeder — 4 comb + 2 allpass) with
  pre-delay (< 40 ms, Swedien pág. 39) and return EQ on the WET only.
  ``bpm`` invalid (None / ≤ 0) → neutral no-op, reported ``no_tempo``,
  never a crash (Alex guard: dimension applies ONLY with a valid tempo).
* Neutrality contract (spec 08): mix-0 profile or empty profile →
  THE SAME array object (bit-exact bypass), like ``delay.py``/``reverb.py``.
* ``build_mix`` grows ``dimension_profiles``:
  ``None`` ⇒ ``DIMENSION_PROFILES`` active by default; ``{}`` → dimension
  disabled, exact Paso 03 routing (no ``dimension_report`` key). When
  active, BPM is measured once from the INPUT (librosa beat tracking,
  same measurement as ``analysis/analyzer.py``) and the dimension applies
  AFTER the EQ, BEFORE the pad/sum.

``split_audio`` is monkeypatched with the same synthetic stand-in as
Paso 01–03 (``tests.test_mix_engine._fake_split``); its 1-second tones
yield ``tempo = 0.0`` from ``librosa.beat.beat_track``, so the honest
integration behaviour on synthetic material is ``status = "no_tempo"`` —
verified empirically in the venv (librosa 1.0.0). The deterministic
"active" path monkeypatches ``mix_engine._measure_input_bpm``.
"""
import sys
import uuid

sys.path.insert(0, "src")

import numpy as np
import pytest

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.dimension import (
    DIMENSION_PROFILES,
    apply_return_eq,
    apply_stem_dimension,
    tempo_delay_ms,
    tempo_delay_table,
)
from audiomind.processing.magic_frequencies import MAGIC_PROFILES
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from tests.test_mix_engine import _fake_split

_SR = 44100
_SECONDS = 0.125
_LAYERING_NOTE = "longest reverb brightest, shortest darkest"


def _sine(freq: float, amp: float = 0.5) -> np.ndarray:
    """Short float32 sine tone (integral cycles at ``_SR``)."""
    n = int(_SR * _SECONDS)
    t = np.linspace(0.0, _SECONDS, n, endpoint=False)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _stereo(freq: float, amp: float = 0.5) -> np.ndarray:
    """Stereo (2, N) pair with identical channels (float32, mono-safe)."""
    s = _sine(freq, amp)
    return np.stack([s, s]).astype(np.float32)


def _band_rms(audio: np.ndarray, lo_hz: float, hi_hz: float) -> float:
    """RMS of the FFT magnitude inside [lo, hi] on channel 0 (identical
    channels — one channel suffices)."""
    mono = audio[0]
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / _SR)
    mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    assert np.any(mask), f"no FFT bins in [{lo_hz}, {hi_hz}] Hz"
    return float(np.sqrt(np.mean(spec[mask] ** 2)))


class TestTempoDelayMs:
    """Tempo math contract (book págs. 39–40, apéndice págs. 216–217)."""

    def test_quarter_at_120_is_500ms(self):
        assert tempo_delay_ms(120.0, "quarter") == 500.0

    def test_all_subdivisions_at_120(self):
        """dotted ×1.5 (750), triplet ×0.667 (≈333.5), half ×2 (1000),
        eighth ÷2 (250), sixteenth ÷4 (125) — all rounded to 2 decimals."""
        assert tempo_delay_ms(120.0, "dotted_quarter") == 750.0
        assert tempo_delay_ms(120.0, "triplet_quarter") == pytest.approx(333.5, abs=0.5)
        assert tempo_delay_ms(120.0, "half") == 1000.0
        assert tempo_delay_ms(120.0, "eighth") == 250.0
        assert tempo_delay_ms(120.0, "sixteenth") == 125.0

    def test_table_sweep_60_160_coherent_within_1ms(self):
        """Reference table: every subdivision stays within ±1 ms of the
        quarter-note formula it derives from (apéndice págs. 216–217)."""
        table = tempo_delay_table()
        assert min(table) == 60 and max(table) == 160
        for bpm, row in table.items():
            quarter = 60000.0 / bpm
            assert row["quarter"] == pytest.approx(quarter, abs=1.0)
            assert row["dotted_quarter"] == pytest.approx(quarter * 1.5, abs=1.0)
            assert row["triplet_quarter"] == pytest.approx(quarter * 0.667, abs=1.0)
            assert row["half"] == pytest.approx(quarter * 2.0, abs=1.0)
            assert row["eighth"] == pytest.approx(quarter / 2.0, abs=1.0)
            assert row["sixteenth"] == pytest.approx(quarter / 4.0, abs=1.0)

    def test_table_120_anchor_values(self):
        table = tempo_delay_table()
        assert table[120]["quarter"] == 500.0
        assert table[120]["dotted_quarter"] == 750.0
        assert table[120]["eighth"] == 250.0

    def test_table_monotonic_decreasing_with_bpm(self):
        """Faster tempo → shorter notes: the table must never jump up."""
        table = tempo_delay_table()
        bpms = sorted(table)
        for subdivision in table[bpms[0]]:
            values = [table[bpm][subdivision] for bpm in bpms]
            assert all(
                a > b for a, b in zip(values, values[1:], strict=False)
            )  # strict

    def test_invalid_subdivision_raises(self):
        with pytest.raises(ValueError):
            tempo_delay_ms(120.0, "quarter_triplets")

    def test_non_positive_bpm_raises(self):
        with pytest.raises(ValueError):
            tempo_delay_ms(0.0, "quarter")
        with pytest.raises(ValueError):
            tempo_delay_ms(-90.0, "quarter")


class TestApplyStemDimensionNeutrality:
    """Neutrality contract (spec 08): mix-0 / empty / no-tempo → the SAME
    array object (bit-exact), reported honestly."""

    def test_mix_zero_profile_same_object_and_array_equal(self):
        audio = _stereo(440.0)
        profile = {
            "reverb": {"size": 0.85, "mix": 0.0, "pre_delay_ms": 30.0,
                       "return_eq": "bright"},
            "delay": {"subdivision": "quarter", "feedback": 0.35, "mix": 0.0},
        }
        out, report = apply_stem_dimension(audio, _SR, 120.0, profile)
        assert out is audio  # same object — bit-exact passthrough
        assert np.array_equal(out, audio)
        assert report["applied"] is False
        assert report["delay_ms"] is None
        assert report["reverb_size"] is None
        assert report["pre_delay_ms"] is None

    def test_empty_profile_same_object(self):
        audio = _stereo(440.0)
        out, report = apply_stem_dimension(audio, _SR, 120.0, {})
        assert out is audio
        assert report["applied"] is False
        assert report["return_eq"] == "neutral"

    def test_none_bpm_no_tempo_report(self):
        audio = _stereo(440.0)
        out, report = apply_stem_dimension(
            audio, _SR, None, DIMENSION_PROFILES["vocals"]
        )
        assert out is audio
        assert report == {"bpm_used": None, "applied": False, "reason": "no_tempo"}

    def test_zero_bpm_no_tempo_report(self):
        audio = _stereo(440.0)
        out, report = apply_stem_dimension(
            audio, _SR, 0.0, DIMENSION_PROFILES["vocals"]
        )
        assert out is audio
        assert report["reason"] == "no_tempo"

    def test_negative_bpm_never_crashes(self):
        audio = _stereo(440.0)
        out, report = apply_stem_dimension(
            audio, _SR, -10.0, DIMENSION_PROFILES["vocals"]
        )
        assert out is audio
        assert report["reason"] == "no_tempo"


class TestApplyStemDimensionEngaged:
    """Engaged path: delay + reverb reports carry the applied values."""

    def test_vocals_profile_applies_delay_and_reverb(self):
        audio = _stereo(440.0)
        out, report = apply_stem_dimension(
            audio, _SR, 120.0, DIMENSION_PROFILES["vocals"]
        )
        assert report["applied"] is True
        assert report["delay_ms"] == pytest.approx(500.0, abs=1.0)  # 60000/120
        assert report["reverb_size"] == 0.85
        assert report["return_eq"] == "bright"
        assert out is not audio
        assert out.shape == audio.shape
        assert out.dtype == audio.dtype
        assert np.all(np.isfinite(out))

    @pytest.mark.parametrize("stem", list(STEM_NAMES))
    def test_pre_delay_between_0_and_40ms(self, stem):
        """Early reflections < 40 ms (Swedien, book pág. 39); pre-delay
        separates the source from the reverb (pág. 214)."""
        profile = DIMENSION_PROFILES[stem]
        audio = _stereo(440.0)
        _, report = apply_stem_dimension(audio, _SR, 120.0, profile)
        assert report["applied"] is True
        assert 0.0 < report["pre_delay_ms"] < 40.0

    def test_all_profiles_have_tempo_delays_in_report(self):
        """vocals → quarter, other → eighth, drums/bass → none."""
        audio = _stereo(440.0)
        _, vocals = apply_stem_dimension(
            audio, _SR, 120.0, DIMENSION_PROFILES["vocals"]
        )
        _, other = apply_stem_dimension(
            audio, _SR, 120.0, DIMENSION_PROFILES["other"]
        )
        _, drums = apply_stem_dimension(
            audio, _SR, 120.0, DIMENSION_PROFILES["drums"]
        )
        _, bass = apply_stem_dimension(
            audio, _SR, 120.0, DIMENSION_PROFILES["bass"]
        )
        assert vocals["delay_ms"] == pytest.approx(500.0, abs=1.0)
        assert other["delay_ms"] == pytest.approx(250.0, abs=1.0)  # eighth
        assert drums["delay_ms"] is None
        assert bass["delay_ms"] is None

    def test_layering_rule_sizes_and_voicings(self):
        """Longest reverb → brightest (vocals); shortest → darkest (bass);
        dense content → lows cut on the effect (drums HP)."""
        voices = {stem: p["reverb"]["size"] for stem, p in DIMENSION_PROFILES.items()}
        assert DIMENSION_PROFILES["vocals"]["reverb"]["size"] == max(voices.values())
        assert DIMENSION_PROFILES["bass"]["reverb"]["size"] == min(voices.values())
        assert DIMENSION_PROFILES["vocals"]["reverb"]["return_eq"] == "bright"
        assert DIMENSION_PROFILES["bass"]["reverb"]["return_eq"] == "dark"
        assert DIMENSION_PROFILES["drums"]["reverb"]["hp_hz"] is not None
        assert 150.0 <= DIMENSION_PROFILES["drums"]["reverb"]["hp_hz"] <= 200.0


class TestApplyReturnEq:
    """Return EQ unit contract (book págs. 37–38): spectrally measurable."""

    def test_neutral_returns_same_object(self):
        audio = _stereo(1000.0)
        profile = {"reverb": {"return_eq": "neutral", "hp_hz": None, "lp_hz": None}}
        out = apply_return_eq(audio, profile, _SR)
        assert out is audio

    def test_bright_boosts_8_12k_band(self):
        """Bright return: shelf ~8–12 kHz (+~2–3 dB) vs the neutral path."""
        audio = _stereo(10000.0)
        bright = apply_return_eq(audio, DIMENSION_PROFILES["vocals"], _SR)
        neutral = apply_return_eq(audio, {"reverb": {"return_eq": "neutral"}}, _SR)
        # neutral passes the same object through — band energy must grow.
        assert _band_rms(bright, 8000.0, 12000.0) > 1.15 * _band_rms(
            neutral, 8000.0, 12000.0
        )

    def test_bright_leaves_low_content_untouched(self):
        """The shelf only colors the top: 4 kHz content passes ≈ unity."""
        audio = _stereo(4000.0)
        bright = apply_return_eq(audio, DIMENSION_PROFILES["vocals"], _SR)
        assert _band_rms(bright, 3000.0, 5000.0) > 0.95 * _band_rms(
            audio, 3000.0, 5000.0
        )

    def test_dark_reduces_high_frequencies(self):
        """Dark return: LP < 6 kHz approx — 10 kHz content is cut hard."""
        audio = _stereo(10000.0)
        dark = apply_return_eq(audio, DIMENSION_PROFILES["bass"], _SR)
        assert _band_rms(dark, 8000.0, 12000.0) < 0.6 * _band_rms(
            audio, 8000.0, 12000.0
        )

    def test_dark_keeps_low_mids(self):
        audio = _stereo(400.0)
        dark = apply_return_eq(audio, DIMENSION_PROFILES["bass"], _SR)
        assert _band_rms(dark, 300.0, 500.0) > 0.95 * _band_rms(audio, 300.0, 500.0)

    def test_drums_hp_cuts_100hz(self):
        """Dense-content return: HP 150–200 Hz on the effect (pág. 37–38)."""
        audio = _stereo(100.0)
        drums = apply_return_eq(audio, DIMENSION_PROFILES["drums"], _SR)
        assert _band_rms(drums, 80.0, 120.0) < 0.6 * _band_rms(audio, 80.0, 120.0)

    def test_drums_hp_spares_mid_content(self):
        audio = _stereo(2000.0)
        drums = apply_return_eq(audio, DIMENSION_PROFILES["drums"], _SR)
        assert _band_rms(drums, 1500.0, 2500.0) > 0.98 * _band_rms(
            audio, 1500.0, 2500.0
        )


class TestMixEngineDimension:
    """``build_mix`` integration: default on, ``{}`` off, keys intact."""

    def test_dimension_disabled_no_report_key(self, tmp_path, monkeypatch):
        """``dimension_profiles={}`` → exact Paso 03 routing: no
        ``dimension_report`` key, no BPM measurement, EQ/pan keys intact."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, dimension_profiles={},
        )
        assert "dimension_report" not in result
        assert "pan_report" not in result
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_dimension_default_active_with_fixed_bpm(self, tmp_path, monkeypatch):
        """``dimension_profiles=None`` → DIMENSION_PROFILES active; with a
        deterministic BPM the report carries every stem's applied values."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), pan_profiles={}
        )
        assert "dimension_report" in result
        report = result["dimension_report"]
        assert report["status"] == "active"
        assert report["bpm_used"] == 120.0
        assert report["layering"] == {"note": _LAYERING_NOTE}
        assert set(report["stems"]) == set(STEM_NAMES)
        vocals = report["stems"]["vocals"]
        assert vocals["delay"] == {
            "subdivision": "quarter", "ms": pytest.approx(500.0, abs=1.0),
        }
        assert 0.0 < vocals["reverb"]["pre_delay_ms"] < 40.0
        assert vocals["reverb"]["return_eq"] == "bright"
        assert vocals["applied"] is True
        drums = report["stems"]["drums"]
        assert drums["delay"]["subdivision"] is None
        assert drums["reverb"]["return_eq"] == "neutral"
        assert report["stems"]["bass"]["reverb"]["return_eq"] == "dark"
        # Paso 01–03 keys keep their contracts next to the new key.
        assert "pan_report" not in result
        assert "eq_profiles_applied" in result
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_dimension_real_bpm_measurement_on_synthetic(self, tmp_path, monkeypatch):
        """Unpatched BPM on 1 s synthetic tones: librosa reports tempo 0.0 →
        honest ``no_tempo`` report (verified in the venv, librosa 1.0.0),
        never a crash and never a missing key."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), pan_profiles={}
        )
        assert "dimension_report" in result
        status = result["dimension_report"]["status"]
        assert status in {"active", "no_tempo"}
        if status == "no_tempo":
            assert result["dimension_report"]["bpm_used"] is None
            for entry in result["dimension_report"]["stems"].values():
                assert entry["applied"] is False

    def test_dimension_missing_input_bpm_is_no_tempo(self, tmp_path, monkeypatch):
        """The input file may not exist (direct build_mix callers); the BPM
        helper degrades to no_tempo instead of crashing (Alex guard)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "missing.wav"), pan_profiles={}
        )
        assert result["dimension_report"]["status"] == "no_tempo"
        assert result["dimension_report"]["bpm_used"] is None

    def test_dimension_custom_profiles_only_reports_mapped_stems(
        self, tmp_path, monkeypatch,
    ):
        """A custom dict maps only some stems: the rest are untouched and
        do not appear in the report (panorama convention)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 90.0)
        custom = {"vocals": DIMENSION_PROFILES["vocals"]}
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, dimension_profiles=custom,
        )
        report = result["dimension_report"]
        assert set(report["stems"]) == {"vocals"}
        assert report["bpm_used"] == 90.0
        ms = report["stems"]["vocals"]["delay"]["ms"]
        assert ms == pytest.approx(60000.0 / 90.0, abs=1.0)  # quarter