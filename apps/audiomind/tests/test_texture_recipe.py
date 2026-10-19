"""Tests for the P4 texture recipe (T2 — the mix side of mastering cohesion).

Spec: ``odd/tasks/mastering-cohesion.md`` S1 and S2's emission side.

S1 says the mix engine writes ``texture_recipe`` into ``MixMetadata`` only when
the character stage ran, and every number in it is MEASURED on the two buses
that exist at that moment: the clean bus (the stem sum without the character
stages) and the shaped bus (the bus input of the 2-bus compressor, bed
included). ``build_texture_recipe`` is a pure function over those two arrays, so
these tests drive it with synthetic buses and check its numbers against values
computed independently in the test.

Requirement 5 (neutrality) is the other half: with ``character=None`` no
measurement runs, no ``texture_recipe`` key appears, and ``schema_version``
stays ``1`` — the neutral payload keeps the exact six-key shape it has today.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

import audiomind.processing.mix_engine as mix_engine
from audiomind.api.upload import sessions
from audiomind.models.audio import ProcessingStatus, SessionData
from audiomind.processing.character import (
    CHARACTER_DEFAULT_SEED,
    CHARACTER_STAGES,
    HF_BAND_HZ,
    crest_db,
)
from audiomind.processing.texture_recipe import build_texture_recipe

_SR = 44100
PROFILE = "commercial_alt_pop"
_STEM_SPECS = {
    "drums": (120.0, 0.75),
    "bass": (90.0, 1.0),
    "other": (330.0, 1.0),
    "vocals": (440.0, 1.25),
}
#: The exact neutral ``mix_metadata`` shape that must survive P4 untouched.
_MIX_METADATA_KEYS = {
    "schema_version",
    "applied_spatial_width",
    "side_energy_ratio",
    "stem_lufs",
    "transient_headroom_db",
    "mix_status",
}
_MEASURED_KEYS = {
    "loudness_delta_lu",
    "hf_excess_db",
    "crest_delta_db",
    "centroid_delta_hz",
    "band_limited_vocal",
    "vocal_band_ratio",
}
_BED_KEYS = {
    "applied",
    "transient",
    "hiss_dbfs",
    "crackle_dbfs",
    "crackle_rate_per_s",
}


# ── synthetic buses (pure-function tests) ────────────────────────────────


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono]).astype(np.float32)


def _tone(freq: float, seconds: float = 1.0, amp: float = 0.25) -> np.ndarray:
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    return _stereo(amp * np.sin(2.0 * np.pi * freq * t))


def _noise(
    seconds: float = 1.0, level_dbfs: float = -30.0, seed: int = 0
) -> np.ndarray:
    """A deterministic low-level noise bed (white, same level in both channels)."""
    n = int(_SR * seconds)
    amp = 10.0 ** (level_dbfs / 20.0)
    return _stereo(amp * np.random.default_rng(seed).standard_normal(n))


def _bandpass(mono: np.ndarray, low: float, high: float) -> np.ndarray:
    sos = butter(2, [low, high], btype="bandpass", fs=_SR, output="sos")
    return np.asarray(sosfilt(sos, mono.astype(np.float64)))


def _recipe(
    clean: np.ndarray,
    shaped: np.ndarray,
    *,
    bed: dict | None = None,
    vocal: np.ndarray | None = None,
) -> dict:
    return build_texture_recipe(
        profile=PROFILE,
        seed=CHARACTER_DEFAULT_SEED,
        stages=CHARACTER_STAGES,
        clean_bus=clean,
        shaped_bus=shaped,
        sr=_SR,
        bed={"status": "skipped"} if bed is None else bed,
        vocal_audio=vocal,
    )


_ACTIVE_BED = {
    "status": "active",
    "hiss_level_dbfs": -48.0,
    "crackle_level_dbfs": -54.0,
    "crackle_rate_per_s": 12.0,
}


class TestMeasuredDeltas:
    """S1: every measured value is a real delta between the two buses."""

    def test_identical_buses_measure_zero(self):
        bus = _tone(440.0)
        measured = _recipe(bus, bus.copy(), vocal=_tone(440.0))["measured"]
        assert measured["loudness_delta_lu"] == pytest.approx(0.0, abs=1e-9)
        assert measured["hf_excess_db"] == pytest.approx(0.0, abs=1e-9)
        assert measured["crest_delta_db"] == pytest.approx(0.0, abs=1e-9)
        assert measured["centroid_delta_hz"] == pytest.approx(0.0, abs=1e-9)

    def test_a_noise_bed_raises_loudness_and_high_frequency_energy(self):
        clean = _tone(220.0)
        shaped = (clean.astype(np.float64) + _noise(level_dbfs=-30.0)).astype(
            np.float32
        )
        measured = _recipe(clean, shaped, vocal=clean)["measured"]
        assert measured["loudness_delta_lu"] > 0.0
        assert measured["hf_excess_db"] > 0.0

    def test_the_crest_delta_is_clean_minus_shaped(self):
        clean = _tone(220.0)
        shaped = (clean.astype(np.float64) + _noise(level_dbfs=-26.0)).astype(
            np.float32
        )
        measured = _recipe(clean, shaped, vocal=clean)["measured"]
        # Direction is measured, not assumed: the test recomputes the expected
        # difference with the same public helper the recipe uses.
        expected = crest_db(clean) - crest_db(shaped)
        assert measured["crest_delta_db"] == pytest.approx(expected, abs=1e-9)

    def test_the_centroid_delta_is_shaped_minus_clean(self):
        clean = _tone(220.0)
        # Adding high-frequency content must raise the magnitude centroid; that
        # is a property of the high band, not an assumption about the bed.
        shaped = (clean.astype(np.float64) + _tone(8000.0)).astype(np.float32)
        measured = _recipe(clean, shaped, vocal=clean)["measured"]
        assert measured["centroid_delta_hz"] > 0.0

    def test_the_high_band_delta_is_restricted_to_the_hf_band(self):
        clean = _tone(220.0)
        # A low-frequency-only change lives BELOW HF_BAND_HZ (4-10 kHz): the
        # band-restricted delta must stay near zero.
        shaped = (clean.astype(np.float64) + _tone(110.0)).astype(np.float32)
        measured = _recipe(clean, shaped, vocal=clean)["measured"]
        assert measured["hf_excess_db"] == pytest.approx(0.0, abs=0.5)
        assert HF_BAND_HZ == (4000.0, 10000.0)


class TestVocalBand:
    """S1: the vocal band is measured on the vocals stem, not asserted."""

    def test_a_telephone_band_vocal_is_band_limited(self):
        # A vocal whose energy is confined INSIDE the 300-3400 Hz band. The
        # passband sits clear of the band edges: a real Butterworth filter has
        # skirts, so a filter designed exactly at the edges still leaks some
        # energy outside them and would (correctly) read as not band-limited.
        noise = np.random.default_rng(3).standard_normal(_SR)
        vocal = _stereo(_bandpass(noise, 500.0, 2500.0))
        measured = _recipe(_tone(220.0), _tone(220.0), vocal=vocal)["measured"]
        assert measured["band_limited_vocal"] is True
        assert measured["vocal_band_ratio"] >= 0.9

    def test_a_full_band_vocal_is_not_band_limited(self):
        noise = np.random.default_rng(4).standard_normal(_SR)
        measured = _recipe(_tone(220.0), _tone(220.0), vocal=_stereo(noise))["measured"]
        assert measured["band_limited_vocal"] is False
        assert measured["vocal_band_ratio"] < 0.9

    def test_a_missing_vocal_never_claims_to_be_band_limited(self):
        measured = _recipe(_tone(220.0), _tone(220.0))["measured"]
        assert measured["band_limited_vocal"] is False
        assert measured["vocal_band_ratio"] == 0.0


class TestRecipeShape:
    """S1: the recipe shape is frozen — exact keys, exact types."""

    def test_every_s1_key_is_present_with_the_declared_type(self):
        recipe = _recipe(
            _tone(220.0), _tone(220.0), bed=_ACTIVE_BED, vocal=_tone(440.0)
        )
        assert set(recipe) == {
            "recipe_schema",
            "profile",
            "seed",
            "stems",
            "bed",
            "measured",
        }
        assert recipe["recipe_schema"] == 1
        assert isinstance(recipe["recipe_schema"], int)
        assert recipe["profile"] == PROFILE
        assert recipe["seed"] == CHARACTER_DEFAULT_SEED

        assert set(recipe["stems"]) == {"drums", "bass", "other", "vocals"}
        assert recipe["stems"] == {
            "drums": [],
            "bass": ["saturation"],
            "other": ["wow_flutter", "chorus"],
            "vocals": ["slapback"],
        }

        bed = recipe["bed"]
        assert set(bed) == _BED_KEYS
        assert bed["applied"] is True
        assert bed["transient"] is True
        assert bed["hiss_dbfs"] == -48.0
        assert bed["crackle_dbfs"] == -54.0
        assert bed["crackle_rate_per_s"] == 12.0
        for key in ("hiss_dbfs", "crackle_dbfs", "crackle_rate_per_s"):
            assert isinstance(bed[key], float)

        measured = recipe["measured"]
        assert set(measured) == _MEASURED_KEYS
        assert isinstance(measured["band_limited_vocal"], bool)
        for key in (
            "loudness_delta_lu",
            "hf_excess_db",
            "crest_delta_db",
            "centroid_delta_hz",
            "vocal_band_ratio",
        ):
            assert isinstance(measured[key], float)

    def test_a_skipped_bed_is_reported_as_not_applied(self):
        bed = _recipe(
            _tone(220.0),
            _tone(220.0),
            bed={"status": "skipped", "reason": "no_negative_space"},
            vocal=_tone(220.0),
        )["bed"]
        assert bed["applied"] is False
        assert bed["transient"] is False
        assert bed["hiss_dbfs"] == 0.0
        assert bed["crackle_dbfs"] == 0.0
        assert bed["crackle_rate_per_s"] == 0.0


# ── build_mix integration (neutrality + emission) ────────────────────────


def _write_tone(path: Path, hz: float, seconds: float) -> None:
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), _SR)


def _fake_split(input_path, output_dir=None, model="htdemucs"):
    """Demucs stand-in: four synthetic stems with differing lengths."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        stem_path = out / f"{name}.wav"
        _write_tone(stem_path, hz, seconds)
        stems[name] = str(stem_path)
    return {
        "stems": stems,
        "sample_rate": _SR,
        "duration_seconds": 1.25,
        "stem_audio_dir": str(out),
    }


def _authorized_bed(input_path):
    """Force the bed gate open so ``bed.applied`` is exercised in the render."""
    return True, {
        "status": "measured",
        "negative_space_ratio": 0.5,
        "gate_db": -40.0,
        "bed_authorized": True,
    }


def _render(tmp_path: Path, monkeypatch, **kwargs) -> dict:
    monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
    monkeypatch.setattr(mix_engine, "_bed_authorization", _authorized_bed)
    session_id = str(uuid.uuid4())
    original_path = tmp_path / "input.wav"
    _write_tone(original_path, hz=220.0, seconds=1.0)
    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original_path),
        original_filename=original_path.name,
    )
    return mix_engine.build_mix(
        session_id,
        str(original_path),
        profiles={},
        pan_profiles={},
        dimension_profiles={},
        compressor_profiles={},
        emphasis_profiles={},
        with_versions=False,
        genre="alternative",
        genre_confidence=0.9,
        **kwargs,
    )


class TestNeutralMixMetadata:
    """Requirement 5: no character → nothing measured, nothing added."""

    def test_no_character_keeps_the_six_key_v1_payload(self, tmp_path, monkeypatch):
        meta = _render(tmp_path, monkeypatch)["mix_metadata"]
        assert "texture_recipe" not in meta
        assert meta["schema_version"] == 1
        assert set(meta) == _MIX_METADATA_KEYS


class TestCharacterEmitsTheRecipe:
    """S1/S2: the character run publishes a v2 recipe with the frozen shape."""

    def test_the_character_run_publishes_a_v2_recipe(self, tmp_path, monkeypatch):
        meta = _render(tmp_path, monkeypatch, character=PROFILE)["mix_metadata"]
        assert meta["schema_version"] == 2
        recipe = meta["texture_recipe"]
        assert recipe["recipe_schema"] == 1
        assert recipe["profile"] == PROFILE
        assert recipe["seed"] == CHARACTER_DEFAULT_SEED
        assert recipe["stems"] == {
            "drums": [],
            "bass": ["saturation"],
            "other": ["wow_flutter", "chorus"],
            "vocals": ["slapback"],
        }
        assert set(recipe["bed"]) == _BED_KEYS
        assert recipe["bed"]["applied"] is True
        assert recipe["bed"]["transient"] is True
        assert set(recipe["measured"]) == _MEASURED_KEYS
        assert isinstance(recipe["measured"]["band_limited_vocal"], bool)
        assert isinstance(recipe["measured"]["loudness_delta_lu"], float)

    def test_the_recipe_carries_the_resolved_seed(self, tmp_path, monkeypatch):
        meta = _render(tmp_path, monkeypatch, character=PROFILE, character_seed=99)[
            "mix_metadata"
        ]
        assert meta["texture_recipe"]["seed"] == 99

    def test_the_shaped_bus_is_actually_different_from_the_clean_one(
        self, tmp_path, monkeypatch
    ):
        # A recipe whose deltas are all zero would be vacuous: the character
        # DOES change the bus, so at least one measured delta must be non-zero.
        recipe = _render(tmp_path, monkeypatch, character=PROFILE)["mix_metadata"][
            "texture_recipe"
        ]
        measured = recipe["measured"]
        assert any(
            abs(measured[key]) > 1e-9
            for key in (
                "loudness_delta_lu",
                "hf_excess_db",
                "crest_delta_db",
                "centroid_delta_hz",
            )
        )
