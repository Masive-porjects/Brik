"""TDD tests for the Mix Engine Paso 06 — genre emphasis (vocal/groove).

RED → GREEN → REFACTOR contract for ``build_mix(emphasis_profiles=...)``:

* the genre detected by the analyzer (``analysis/analyzer.py``,
  ``_detect_genre``: pop, rock, electronic, hip_hop, reggaeton, jazz,
  classical, acoustic, metal, other) resolves through
  ``resolve_emphasis`` into a vocal-forward / groove-forward weight pair
  that sums to 1.0 (the "Interest" balance of the book, Ch8 pág. 58–60:
  "Dance/Rap → énfasis en groove (kick/bajo); Country/Pop → énfasis en
  vocal" — ``VIABILIDAD_MOTOR_DE_MEZCLA.md``),
* unknown genre / low confidence → NEUTRAL 0.5/0.5 fallback with
  ``neutral_fallback`` status — same behaviour as Paso 05 (no direction),
* ``scale_dimension_profile`` and ``scale_bus_profile`` move parameters
  INSIDE the standard ranges already defined by the engine (reverb.py /
  delay.py validation, dynamics recipe 2–3 dB), never saturating and
  clamping at the extremes,
* ``emphasis_profiles={}`` restores the exact Paso 05 routing (no
  ``emphasis_report`` key, bit-identical WAV),
* ``build_mix`` exposes the ``emphasis_report`` (genre / confidence /
  weights / scaling / status) next to every existing key.
"""
import uuid

import pytest
import soundfile as sf

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.dimension import DIMENSION_PROFILES
from audiomind.processing.dynamics import BUS_COMPRESSOR_PROFILE
from audiomind.processing.emphasis import (
    CONFIDENCE_THRESHOLD,
    GENRE_EMPHASIS_PROFILES,
    resolve_emphasis,
    scale_bus_profile,
    scale_dimension_profile,
)
from audiomind.processing.magic_frequencies import MAGIC_PROFILES
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from tests.test_mix_engine import _fake_split

#: The genre space the analyzer can return (``_detect_genre`` rule set).
ANALYZER_GENRES = {
    "pop", "rock", "electronic", "hip_hop", "reggaeton", "jazz",
    "classical", "acoustic", "metal", "other",
}

_NEUTRAL = {"vocal_forward": 0.5, "groove_forward": 0.5}
_POP = {"vocal_forward": 0.7, "groove_forward": 0.3}
_ELECTRONIC = {"vocal_forward": 0.3, "groove_forward": 0.7}


def _assert_weight_pair_valid(weights: dict) -> None:
    """Every profile: both weights in [0, 1], summing to exactly 1.0."""
    assert set(weights) == {"vocal_forward", "groove_forward"}
    assert 0.0 <= weights["vocal_forward"] <= 1.0
    assert 0.0 <= weights["groove_forward"] <= 1.0
    assert weights["vocal_forward"] + weights["groove_forward"] == pytest.approx(1.0)


class TestGenreWeightProfiles:
    """The genre → weights table (Interest balance, book Ch8 pág. 58–60)."""

    def test_every_profile_valid_sum_one(self):
        """Acceptance: each genre maps to a valid [0, 1] pair summing to 1."""
        assert GENRE_EMPHASIS_PROFILES, "table must not be empty"
        for _genre, weights in GENRE_EMPHASIS_PROFILES.items():
            _assert_weight_pair_valid(weights)

    def test_covers_every_analyzer_genre(self):
        """Acceptance: the REAL analyzer genre space has a profile each —
        unknown labels are the only path to the neutral fallback."""
        assert ANALYZER_GENRES <= set(GENRE_EMPHASIS_PROFILES)

    def test_book_anchor_directions(self):
        """Manual anchor (VIABILIDAD §Elemento 6): 'Country/Pop → énfasis en
        vocal' and 'Dance/Rap → énfasis en groove (kick/bajo)'."""
        assert GENRE_EMPHASIS_PROFILES["pop"]["vocal_forward"] > 0.5
        assert GENRE_EMPHASIS_PROFILES["electronic"]["groove_forward"] > 0.5
        assert GENRE_EMPHASIS_PROFILES["hip_hop"]["groove_forward"] > 0.5

    def test_full_direction_is_anchored(self):
        """The most vocal-forward genre beats the most groove-forward one on
        the vocal axis (the table really spans the balance, not a constant)."""
        max_vocal = max(
            p["vocal_forward"] for p in GENRE_EMPHASIS_PROFILES.values()
        )
        max_groove = max(
            p["groove_forward"] for p in GENRE_EMPHASIS_PROFILES.values()
        )
        assert max_vocal > 0.5 and max_groove > 0.5
        assert max_vocal + max_groove > 1.0


class TestResolveEmphasis:
    """Genre hook → weights, with the neutral fallback (Alex guard)."""

    def test_known_genre_active(self):
        resolved = resolve_emphasis("pop", 0.87)
        assert resolved["genre"] == "pop"
        assert resolved["genre_confidence"] == 0.87
        assert resolved["vocal_forward"] == pytest.approx(0.7)
        assert resolved["groove_forward"] == pytest.approx(0.3)
        assert resolved["status"] == "active"

    def test_unknown_genre_neutral(self):
        resolved = resolve_emphasis(None, None)
        assert resolved["genre"] == "unknown"
        assert resolved["genre_confidence"] is None
        assert resolved["vocal_forward"] == 0.5
        assert resolved["groove_forward"] == 0.5
        assert resolved["status"] == "neutral_fallback"

    def test_out_of_table_genre_neutral(self):
        """A label the table does not know → neutral, never a crash."""
        resolved = resolve_emphasis("country", 0.9)
        assert resolved["genre"] == "unknown"
        assert resolved["status"] == "neutral_fallback"
        assert resolved["vocal_forward"] == 0.5
        assert resolved["groove_forward"] == 0.5

    def test_empty_string_genre_neutral(self):
        resolved = resolve_emphasis("", 0.9)
        assert resolved["genre"] == "unknown"
        assert resolved["status"] == "neutral_fallback"

    def test_low_confidence_neutral_fallback(self):
        """Low confidence → the label is reported but NOT followed
        (neutral weights, neutral_fallback status)."""
        resolved = resolve_emphasis("pop", 0.3)
        assert resolved["genre"] == "pop"
        assert resolved["status"] == "neutral_fallback"
        assert resolved["vocal_forward"] == 0.5
        assert resolved["groove_forward"] == 0.5

    def test_confidence_threshold_boundary(self):
        """Documented threshold: confidence >= 0.5 trusts the genre."""
        assert CONFIDENCE_THRESHOLD == 0.5
        assert resolve_emphasis("pop", 0.5)["status"] == "active"
        assert resolve_emphasis("pop", 0.49)["status"] == "neutral_fallback"

    def test_missing_confidence_is_trusted(self):
        """Explicit genre without confidence → the caller asserts the label."""
        assert resolve_emphasis("pop", None)["status"] == "active"

    def test_custom_profiles_table_override(self):
        custom = {"pop": {"vocal_forward": 0.8, "groove_forward": 0.2}}
        resolved = resolve_emphasis("pop", 0.9, profiles=custom)
        assert resolved["vocal_forward"] == pytest.approx(0.8)
        assert resolved["groove_forward"] == pytest.approx(0.2)
        assert resolved["status"] == "active"


class TestScaleDimensionProfile:
    """Dimension scaling stays INSIDE the engine's standard ranges."""

    def test_neutral_weights_preserve_base_exactly(self):
        """Acceptance: weights 0.5/0.5 → the scaled profile carries the base
        values unchanged (identical behaviour to Paso 05)."""
        for stem, profile in DIMENSION_PROFILES.items():
            scaled = scale_dimension_profile(
                profile, _NEUTRAL, vocal_lead=(stem == "vocals")
            )
            assert scaled == profile, f"{stem}: neutral scaling changed values"

    def test_vocal_lead_forward_increases_vocal_dimension(self):
        """Pop direction: the lead voice gets a longer/brighter reverb and a
        more present delay (per the manual's vocal rule)."""
        scaled = scale_dimension_profile(
            DIMENSION_PROFILES["vocals"], _POP, vocal_lead=True
        )
        assert scaled["reverb"]["mix"] == pytest.approx(0.25 * 1.4)
        assert scaled["reverb"]["size"] == pytest.approx(0.85 * 1.08)
        assert scaled["delay"]["mix"] == pytest.approx(0.18 * 1.2)
        assert scaled["reverb"]["pre_delay_ms"] == pytest.approx(30.0)
        assert scaled["reverb"]["return_eq"] == "bright"
        assert scaled["delay"]["subdivision"] == "quarter"

    def test_groove_forward_wakens_the_bed(self):
        """Electronic direction on the drums (bed): more space for the kit —
        the groove's engine gets presence."""
        scaled = scale_dimension_profile(
            DIMENSION_PROFILES["drums"], _ELECTRONIC, vocal_lead=False
        )
        assert scaled["reverb"]["mix"] == pytest.approx(0.15 * 1.4)
        # No delay in the base kit profile → scaling keeps it at 0 (the kit
        # provides the pulse, dimension.py — never invents a new delay).
        assert scaled["delay"]["mix"] == 0.0
        assert scaled["delay"]["subdivision"] is None

    def test_vocal_forward_dries_the_bed(self):
        """Pop direction on the drums: LESS space, so the voice's reverb
        stands out over a drier kit (layering, pág. 37–38)."""
        scaled = scale_dimension_profile(
            DIMENSION_PROFILES["drums"], _POP, vocal_lead=False
        )
        assert scaled["reverb"]["mix"] == pytest.approx(0.15 * 0.6)

    def test_bounds_never_saturate_across_all_genres(self):
        """Acceptance: NO scaled parameter leaves the standard engine ranges
        (reverb mix [0, 1], size [0.1, 1.0], delay mix [0, 1]) — for every
        stem profile, every genre table entry, and both stem roles."""
        for _stem, profile in DIMENSION_PROFILES.items():
            for genre_weights in GENRE_EMPHASIS_PROFILES.values():
                for vocal_lead in (False, True):
                    scaled = scale_dimension_profile(
                        profile, genre_weights, vocal_lead=vocal_lead
                    )
                    assert 0.0 <= scaled["reverb"]["mix"] <= 1.0
                    assert 0.1 <= scaled["reverb"]["size"] <= 1.0
                    assert 0.0 <= scaled["delay"]["mix"] <= 1.0

    def test_extreme_weights_are_clamped(self):
        """Clamp verification at the extremes (weights 1.0/0.0 and 0.0/1.0):
        the size multiplier would push 0.85·1.2 = 1.02 → clamped to 1.0."""
        hard_vocal = {"vocal_forward": 1.0, "groove_forward": 0.0}
        hard_groove = {"vocal_forward": 0.0, "groove_forward": 1.0}
        for weights in (hard_vocal, hard_groove):
            for vocal_lead in (False, True):
                for profile in DIMENSION_PROFILES.values():
                    scaled = scale_dimension_profile(
                        profile, weights, vocal_lead=vocal_lead
                    )
                    assert 0.0 <= scaled["reverb"]["mix"] <= 1.0
                    assert 0.1 <= scaled["reverb"]["size"] <= 1.0
                    assert 0.0 <= scaled["delay"]["mix"] <= 1.0

    def test_non_scaled_keys_untouched(self):
        """Only the direction knobs move: pre-delay, return EQ, HP/LP, tempo
        subdivision and feedback keep the Paso 04 values verbatim."""
        for stem, profile in DIMENSION_PROFILES.items():
            scaled = scale_dimension_profile(
                profile, _POP, vocal_lead=(stem == "vocals")
            )
            base_reverb = profile["reverb"]
            scaled_reverb = scaled["reverb"]
            assert scaled_reverb["pre_delay_ms"] == base_reverb["pre_delay_ms"]
            assert scaled_reverb["return_eq"] == base_reverb["return_eq"]
            assert scaled_reverb["hp_hz"] == base_reverb["hp_hz"]
            assert scaled_reverb["lp_hz"] == base_reverb["lp_hz"]
            assert scaled["delay"]["subdivision"] == profile["delay"]["subdivision"]
            assert scaled["delay"]["feedback"] == profile["delay"]["feedback"]


class TestScaleBusProfile:
    """Bus scaling stays inside the recipe's 2–3 dB band (págs. 53–56)."""

    def test_neutral_weights_preserve_base(self):
        scaled = scale_bus_profile(BUS_COMPRESSOR_PROFILE, _NEUTRAL)
        assert scaled["bus_gr_target_db"] == pytest.approx(2.5)
        assert scaled["threshold_offset_db"] == pytest.approx(
            BUS_COMPRESSOR_PROFILE["threshold_offset_db"]
        )

    def test_groove_forward_adds_bus_glue(self):
        """Groove direction → a bit MORE bus GR ('pegamento' rítmico)."""
        scaled = scale_bus_profile(BUS_COMPRESSOR_PROFILE, _ELECTRONIC)
        assert scaled["bus_gr_target_db"] > 2.5
        assert scaled["bus_gr_target_db"] <= 3.0

    def test_vocal_forward_lets_the_voice_breathe(self):
        """Vocal direction → a bit LESS bus GR."""
        scaled = scale_bus_profile(BUS_COMPRESSOR_PROFILE, _POP)
        assert scaled["bus_gr_target_db"] < 2.5
        assert scaled["bus_gr_target_db"] >= 2.0

    def test_target_never_leaves_the_recipe_band(self):
        """Acceptance: for EVERY genre table entry the scaled GR target stays
        inside the book's 2–3 dB recipe band (metadata => scaling, not a
        new out-of-range value)."""
        lo, hi = BUS_COMPRESSOR_PROFILE["target_gr_db"]
        for weights in GENRE_EMPHASIS_PROFILES.values():
            scaled = scale_bus_profile(BUS_COMPRESSOR_PROFILE, weights)
            assert lo <= scaled["bus_gr_target_db"] <= hi
        # Extrema too: the clamp holds at hard 1.0/0.0 weights.
        hard = {"vocal_forward": 1.0, "groove_forward": 0.0}
        assert scale_bus_profile(BUS_COMPRESSOR_PROFILE, hard)[
            "bus_gr_target_db"
        ] == pytest.approx(lo)
        assert scale_bus_profile(
            BUS_COMPRESSOR_PROFILE, {"vocal_forward": 0.0, "groove_forward": 1.0}
        )["bus_gr_target_db"] == pytest.approx(hi)

    def test_non_scaled_profile_keys_unchanged(self):
        """Only the GR driver moves: ratio/attack/release/makeup keep Paso 05."""
        scaled = scale_bus_profile(BUS_COMPRESSOR_PROFILE, _POP)
        for key in ("ratio", "attack_ms", "release_ms", "makeup_db"):
            assert scaled[key] == BUS_COMPRESSOR_PROFILE[key]


class TestBuildMixEmphasis:
    """``build_mix`` integration: enabled by default, ``{}`` off, keys intact."""

    def test_empty_emphasis_no_report_key(self, tmp_path, monkeypatch):
        """``emphasis_profiles={}`` → exact Paso 05 routing: no
        ``emphasis_report`` key, Paso 01–05 keys intact."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, emphasis_profiles={},
        )
        assert "emphasis_report" not in result
        assert "dimension_report" in result
        assert "compressor_report" in result
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_missing_input_measurement_degrades_to_neutral(
        self, tmp_path, monkeypatch,
    ):
        """Input file missing (direct build_mix callers): the genre probe
        degrades to the NEUTRAL fallback instead of crashing (Alex guard) —
        report present, weights 0.5/0.5, scaling at the base values."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "missing.wav"), pan_profiles={}
        )
        report = result["emphasis_report"]
        assert report["status"] == "neutral_fallback"
        assert report["genre"] == "unknown"
        assert report["genre_confidence"] is None
        assert report["vocal_forward"] == 0.5
        assert report["groove_forward"] == 0.5
        assert report["scaling"]["dimension"]["vocals_reverb_mix"] == pytest.approx(
            DIMENSION_PROFILES["vocals"]["reverb"]["mix"]
        )
        assert report["scaling"]["bus_gr_target_db"] == pytest.approx(2.5)

    def test_neutral_fallback_is_bit_identical_to_paso05(
        self, tmp_path, monkeypatch,
    ):
        """Acceptance: low-confidence genre → neutral 0.5/0.5 → the SAME
        routing as ``emphasis_profiles={}``: byte-identical WAV and identical
        dimension/compressor reports (no duplicated heavy assertions)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)

        def _run(**kwargs) -> tuple[dict, bytes]:
            session_id = str(uuid.uuid4())
            result = build_mix(
                session_id, str(tmp_path / "input.wav"),
                pan_profiles={}, **kwargs,
            )
            audio, sr = sf.read(result["mix_path"], dtype="float32")
            assert sr != 0
            return result, audio.tobytes()

        base, base_bytes = _run(emphasis_profiles={})
        neutral, neutral_bytes = _run(
            genre="pop", genre_confidence=0.1,
        )
        assert neutral_bytes == base_bytes
        assert neutral["emphasis_report"]["status"] == "neutral_fallback"
        assert neutral["emphasis_report"]["vocal_forward"] == 0.5
        assert neutral["emphasis_report"]["groove_forward"] == 0.5
        assert neutral["dimension_report"] == base["dimension_report"]
        assert neutral["compressor_report"] == base["compressor_report"]

    def test_active_genre_applies_scaling_and_reports(self, tmp_path, monkeypatch):
        """Pop direction: the scaled profiles reach the dimension stage (the
        report proves it: vocals reverb mix 0.35 + size/delay scaled), the
        bus target moves below the base 2.5, and every Paso 01–05 key stays."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, genre="pop", genre_confidence=0.9,
        )
        report = result["emphasis_report"]
        assert report["genre"] == "pop"
        assert report["genre_confidence"] == 0.9
        assert report["status"] == "active"
        assert report["vocal_forward"] == pytest.approx(0.7)
        assert report["groove_forward"] == pytest.approx(0.3)

        scaling = report["scaling"]
        assert scaling["dimension"]["vocals_reverb_mix"] == pytest.approx(0.35)
        assert scaling["dimension"]["vocals_reverb_size"] == pytest.approx(0.92)
        assert scaling["dimension"]["vocals_delay_mix"] == pytest.approx(0.22)
        assert scaling["dimension"]["drums_reverb_mix"] == pytest.approx(0.09)
        assert scaling["dimension"]["drums_delay_mix"] == 0.0
        assert scaling["bus_gr_target_db"] == pytest.approx(2.3)

        # The scaled profile REALLY reached the dimension stage: the per-stem
        # report carries the scaled reverb mix (0.35 > base 0.25).
        dimension = result["dimension_report"]
        assert dimension["status"] == "active"
        assert dimension["stems"]["vocals"]["reverb"]["mix"] == pytest.approx(0.35)
        assert "compressor_report" in result
        assert result["compressor_report"]["bus"]["gr_ok"] is True
        # Paso 01–02 keys intact next to the new key.
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_groove_genre_applies_opposite_direction(self, tmp_path, monkeypatch):
        """Electronic direction: the bed gets wetter/more present and the bus
        target moves ABOVE the base (glue) — the weights span both ends."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _path: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, genre="electronic", genre_confidence=0.9,
        )
        report = result["emphasis_report"]
        assert report["status"] == "active"
        assert report["groove_forward"] == pytest.approx(0.7)
        assert report["scaling"]["dimension"]["drums_reverb_mix"] == pytest.approx(
            0.21
        )
        assert report["scaling"]["dimension"]["vocals_reverb_mix"] == pytest.approx(
            0.15
        )
        assert report["scaling"]["bus_gr_target_db"] == pytest.approx(2.7)
        assert result["compressor_report"]["bus"]["gr_ok"] is True