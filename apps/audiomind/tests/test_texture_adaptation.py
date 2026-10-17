"""Master-side P4 texture adaptation (T3) — the recipe read and S4–S8.

The mix engine (P3) bakes a deliberate texture into the principal render and
measures it into a ``texture_recipe`` (S1). Mastering (`processing/engine.py`)
receives that render and, without the recipe, reads the noise as a defect. This
suite pins the two halves of the master handshake:

  * **S8 — the neutrality invariant.** No ``mix_metadata``, or one with no
    ``texture_recipe``, leaves every byte of the master and every key of the
    returned dict exactly as they are today. An unknown-schema or malformed
    recipe is discarded WHOLE with a named warning, never partially applied.
  * **S2–S7 — the adaptations.** The de-esser skip, the clarity-shelf
    withdrawal (floored at 0.0), the match EQ's ±2 dB-bounded HF offset, the
    loudness compensation, the boothed-stage thresholds and the gate correction
    are each driven by a value of the recipe and each reported in
    ``texture_adaptation``.

Conventions mirror the rest of the suite: ``sys.path.insert(0, "src")``,
synthetic numpy WAVs written as 32-bit float via ``soundfile`` into ``tmp_path``.
"""

import sys

sys.path.insert(0, "src")

import hashlib

import numpy as np
import pytest
import soundfile as sf

from audiomind.models.audio import AnalysisResult, MasteringParameters
from audiomind.models.mix_metadata import MixMetadata
from audiomind.processing.engine import (
    MATCH_EQ_HF_BAND_HZ,
    MATCH_EQ_HF_OFFSET_LIMIT_DB,
    TEXTURE_WARNING_MALFORMED,
    TEXTURE_WARNING_UNKNOWN_SCHEMA,
    _multiband_params_from_mastering,
    _read_texture_recipe,
    _texture_corrected_analysis,
    build_match_eq,
    process_audio,
    target_lufs,
)
from audiomind.processing.loudness import measure_lufs

SR = 44100


def _write_wav(path, samples, sr: int = SR) -> None:
    x = np.asarray(samples)
    sf.write(str(path), x.T if x.ndim == 2 else x, sr, subtype="FLOAT")


def _read_wav(path):
    arr, _ = sf.read(str(path), always_2d=True)
    return arr


def _program(seconds: float = 1.5, seed: int = 7) -> np.ndarray:
    """A tonal stereo program with a light noise floor (mirrors the suite)."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    env = 0.42 + 0.08 * np.sin(2 * np.pi * 0.5 * t)
    left = 0.38 * np.sin(2 * np.pi * 440 * t) * env
    left += 0.12 * np.sin(2 * np.pi * 1320.0 * t) * env
    left += 0.01 * rng.standard_normal(n)
    right = 0.38 * np.sin(2 * np.pi * 440 * t + 0.02) * env
    right += 0.12 * np.sin(2 * np.pi * 1330.0 * t) * env
    right += 0.01 * rng.standard_normal(n)
    x = np.stack([left, right])
    return x / np.max(np.abs(x)) * 10 ** (-7.0 / 20)


def _sibilant_program(seconds: float = 1.2, seed: int = 3) -> np.ndarray:
    """Program carrying a 6 kHz burst, so an engaged de-esser actually acts."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    left = 0.35 * np.sin(2 * np.pi * 440 * t) + 0.01 * rng.standard_normal(n)
    lo, hi = int(0.4 * SR), int(0.8 * SR)
    tb = t[lo:hi] - t[lo]
    left[lo:hi] += 0.6 * np.sin(2 * np.pi * 6000.0 * tb)
    x = np.stack([left, left])
    return x / np.max(np.abs(x)) * 10 ** (-7.0 / 20)


def _flat_program(seconds: float = 1.5, seed: int = 0) -> np.ndarray:
    """A broadband (near-flat) stereo signal: band energies sit close enough
    that the match EQ's deltas stay inside its ±2 dB authority."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((2, int(SR * seconds))) * 0.1
    return x / np.max(np.abs(x)) * 10 ** (-7.0 / 20)


def _recipe(**overrides) -> dict:
    """A valid S1 recipe; dict-valued overrides merge into ``bed``/``measured``."""
    recipe = {
        "recipe_schema": 1,
        "profile": "commercial_alt_pop",
        "seed": 20261016,
        "stems": {
            "drums": [],
            "bass": ["saturation"],
            "other": ["wow_flutter", "chorus"],
            "vocals": ["slapback"],
        },
        "bed": {
            "applied": True,
            "transient": True,
            "hiss_dbfs": -48.0,
            "crackle_dbfs": -54.0,
            "crackle_rate_per_s": 12.0,
        },
        "measured": {
            "loudness_delta_lu": 0.0,
            "hf_excess_db": 0.0,
            "crest_delta_db": 0.0,
            "centroid_delta_hz": 0.0,
            "band_limited_vocal": False,
            "vocal_band_ratio": 1.0,
        },
    }
    for key, value in overrides.items():
        if key in ("bed", "measured") and isinstance(value, dict):
            recipe[key].update(value)
        else:
            recipe[key] = value
    return recipe


def _metadata(recipe: dict | None) -> dict:
    """A full MixMetadata dict; ``texture_recipe`` present only when given."""
    meta: dict = {
        "schema_version": 2 if recipe is not None else 1,
        "applied_spatial_width": 1.0,
        "side_energy_ratio": 0.0,
        "stem_lufs": {},
        "transient_headroom_db": 3.0,
        "mix_status": "completed",
    }
    if recipe is not None:
        meta["texture_recipe"] = recipe
    return meta


def _params(**overrides) -> MasteringParameters:
    base = {"target_lufs_db": -14.0}
    base.update(overrides)
    return MasteringParameters(**base)


def _run(tmp_path, name, params, *, mix_metadata=None, program=None):
    in_path = tmp_path / f"{name}_in.wav"
    out_path = tmp_path / f"{name}_out.wav"
    _write_wav(in_path, _program() if program is None else program)
    result = process_audio(in_path, out_path, params, mix_metadata=mix_metadata)
    return result, _read_wav(out_path)


# ── S2: the reader's contract ───────────────────────────────────────────


def test_reader_returns_none_for_absent_metadata_and_recipes():
    assert _read_texture_recipe(None) == (None, None)
    assert _read_texture_recipe({}) == (None, None)
    assert _read_texture_recipe(_metadata(None)) == (None, None)


def test_reader_accepts_a_valid_recipe_and_normalises_numbers():
    recipe, warning = _read_texture_recipe(_metadata(_recipe()))
    assert warning is None
    assert recipe is not None
    assert recipe["profile"] == "commercial_alt_pop"
    assert recipe["seed"] == 20261016
    assert recipe["bed"]["applied"] is True
    assert recipe["measured"]["hf_excess_db"] == 0.0


def test_reader_accepts_a_mix_metadata_instance():
    meta = MixMetadata(texture_recipe=_recipe())
    recipe, warning = _read_texture_recipe(meta)
    assert warning is None
    assert recipe is not None and recipe["profile"] == "commercial_alt_pop"


def test_reader_rejects_unknown_schema_whole():
    recipe, warning = _read_texture_recipe(_metadata(_recipe(recipe_schema=2)))
    assert recipe is None
    assert warning == TEXTURE_WARNING_UNKNOWN_SCHEMA


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("not_a_dict", id="non_dict_recipe"),
        pytest.param({"profile": "x"}, id="missing_schema"),
        pytest.param(_recipe(profile=7), id="profile_not_str"),
        pytest.param(_recipe(seed="x"), id="seed_not_int"),
        pytest.param(_recipe(bed={"hiss_dbfs": "loud"}), id="bed_level_not_number"),
        pytest.param(_recipe(bed={"applied": "yes"}), id="bed_applied_not_bool"),
        pytest.param(
            _recipe(measured={"hf_excess_db": None}),
            id="measured_not_number",
        ),
        pytest.param(
            _recipe(measured={"band_limited_vocal": "yes"}),
            id="band_limited_not_bool",
        ),
    ],
)
def test_reader_rejects_malformed_recipes_whole(bad):
    recipe, warning = _read_texture_recipe(_metadata(bad))
    assert recipe is None
    assert warning == TEXTURE_WARNING_MALFORMED


# ── S8: the neutrality invariant ────────────────────────────────────────


def test_no_mix_metadata_has_no_report_key_and_matches_metadata_less_run(tmp_path):
    params = _params()
    plain, plain_audio = _run(tmp_path, "plain", params)
    also_plain, also_audio = _run(tmp_path, "plain_none", params, mix_metadata=None)

    assert "texture_adaptation" not in plain
    assert list(plain.keys()) == list(also_plain.keys())
    np.testing.assert_array_equal(plain_audio, also_audio)


def test_mix_metadata_without_recipe_is_identical_and_adds_no_key(tmp_path):
    params = _params()
    baseline, baseline_audio = _run(tmp_path, "baseline", params)
    with_meta, meta_audio = _run(
        tmp_path, "no_recipe", params, mix_metadata=_metadata(None)
    )

    assert "texture_adaptation" not in with_meta
    assert list(with_meta.keys()) == list(baseline.keys())
    np.testing.assert_array_equal(baseline_audio, meta_audio)


@pytest.mark.parametrize(
    "bad_recipe, expected_warning",
    [
        (_recipe(recipe_schema=9), TEXTURE_WARNING_UNKNOWN_SCHEMA),
        (_recipe(measured={"crest_delta_db": "tight"}), TEXTURE_WARNING_MALFORMED),
        ({"profile": "x"}, TEXTURE_WARNING_MALFORMED),
    ],
)
def test_rejected_recipe_renders_identically_and_warns(
    tmp_path, bad_recipe, expected_warning
):
    params = _params()
    baseline, baseline_audio = _run(tmp_path, "base", params)
    result, audio = _run(tmp_path, "bad", params, mix_metadata=_metadata(bad_recipe))

    np.testing.assert_array_equal(baseline_audio, audio)
    assert expected_warning in result["warnings"]
    assert "texture_adaptation" not in result
    assert list(result.keys()) == list(baseline.keys())


#: SHA-256 of the rendered samples for ``_program`` (the suite's deterministic
#: seeded program) through the FULL mastering chain with ``_params()`` and NO
#: recipe. This is a BASELINE FINGERPRINT, not a self-comparison: it pins the
#: delivered bytes against a value committed here, so any drift in the DSP
#: stack — or a texture adaptation leaking into the no-recipe path — fails it.
#: It must be re-baselined DELIBERATELY (update the constant in the same commit
#: that intentionally changes the render), never by relaxing the assertion.
GOLDEN_NEUTRAL_RENDER_SHA256 = (
    "bdd4e1d388fe752b0198d52ae62285603ec7f22718ac172fb66bdb7749543f54"
)


@pytest.mark.parametrize(
    "bad_recipe",
    [
        pytest.param(["not", "a", "dict"], id="list"),
        pytest.param("not_a_recipe", id="str"),
        pytest.param(7, id="int"),
    ],
)
def test_non_dict_recipe_through_process_audio_never_crashes(tmp_path, bad_recipe):
    """The pre-existing ``MixMetadata(**mix_metadata)`` parse site now types
    ``texture_recipe`` as a dict, so a wrong-typed recipe used to raise a
    pydantic ``ValidationError`` mid-render. S2 says a wrong type is DATA, not
    configuration: discard it whole with a warning and render normally."""
    params = _params()
    baseline, baseline_audio = _run(tmp_path, "nd_base", params)
    result, audio = _run(tmp_path, "nd_bad", params, mix_metadata=_metadata(bad_recipe))

    np.testing.assert_array_equal(baseline_audio, audio)
    assert TEXTURE_WARNING_MALFORMED in result["warnings"]
    assert "texture_adaptation" not in result
    assert list(result.keys()) == list(baseline.keys())


def test_none_recipe_through_process_audio_matches_the_no_recipe_run(tmp_path):
    """An explicit ``texture_recipe: None`` is the no-recipe path: identical
    render, no warning, no report key."""
    meta = _metadata(None)
    meta["texture_recipe"] = None  # present-but-None, not merely absent
    params = _params()
    baseline, baseline_audio = _run(tmp_path, "none_base", params)
    result, audio = _run(tmp_path, "none_bad", params, mix_metadata=meta)

    np.testing.assert_array_equal(baseline_audio, audio)
    assert TEXTURE_WARNING_MALFORMED not in result["warnings"]
    assert "texture_adaptation" not in result


def test_no_recipe_render_matches_the_committed_golden_fingerprint(tmp_path):
    """A neutrality assertion that CAN fail on baseline drift (S8(1)).

    The three self-comparison tests above compare ``HEAD`` against ``HEAD``, so
    they cannot detect drift in the DSP stack. This one compares the delivered
    samples against a committed constant. If it fails, do NOT tweak the hash to
    match: re-baseline ``GOLDEN_NEUTRAL_RENDER_SHA256`` deliberately, in the
    commit that intentionally changes the render."""
    _, audio = _run(tmp_path, "golden", _params())
    digest = hashlib.sha256(np.ascontiguousarray(audio).tobytes()).hexdigest()
    assert digest == GOLDEN_NEUTRAL_RENDER_SHA256


# ── S4.2: the de-esser skip ─────────────────────────────────────────────


def test_deesser_skipped_for_crackle_bed_and_reported(tmp_path):
    params = _params(deesser_enabled=True, deesser_amount_db=6.0)
    program = _sibilant_program()
    recipe = _recipe(bed={"applied": True, "transient": True})

    skipped, skipped_audio = _run(
        tmp_path,
        "skip",
        params,
        mix_metadata=_metadata(recipe),
        program=program,
    )
    off, off_audio = _run(
        tmp_path,
        "off",
        _params(deesser_enabled=False),
        mix_metadata=_metadata(recipe),
        program=program,
    )
    active, active_audio = _run(
        tmp_path,
        "active",
        params,
        program=program,
    )

    assert skipped["texture_adaptation"]["deesser"] == {
        "skipped": True,
        "reason": "crackle_bed",
    }
    # The de-esser is genuinely skipped: the master equals the de-esser-off run,
    # and differs from the recipe-less run where it actually engaged.
    np.testing.assert_array_equal(skipped_audio, off_audio)
    assert not np.array_equal(skipped_audio, active_audio)


def test_deesser_skipped_for_band_limited_vocal_and_reported(tmp_path):
    params = _params(deesser_enabled=True, deesser_amount_db=6.0)
    recipe = _recipe(
        bed={"applied": False, "transient": False},
        measured={"band_limited_vocal": True},
    )
    result, audio = _run(
        tmp_path,
        "tel",
        params,
        mix_metadata=_metadata(recipe),
        program=_sibilant_program(),
    )
    off, off_audio = _run(
        tmp_path,
        "tel_off",
        _params(deesser_enabled=False),
        mix_metadata=_metadata(recipe),
        program=_sibilant_program(),
    )
    assert result["texture_adaptation"]["deesser"] == {
        "skipped": True,
        "reason": "band_limited_vocal",
    }
    np.testing.assert_array_equal(audio, off_audio)


# ── S4.3: the clarity shelf ─────────────────────────────────────────────


def test_clarity_shelf_reduced_by_the_declared_hf_excess(tmp_path):
    result, _ = _run(
        tmp_path,
        "clarity",
        _params(clarity_brightness_db=1.0),
        mix_metadata=_metadata(_recipe(measured={"hf_excess_db": 0.5})),
    )
    assert result["texture_adaptation"]["clarity_gain_db"] == {
        "requested": 1.0,
        "applied": 0.5,
    }


def test_clarity_shelf_is_floored_at_zero_never_a_cut(tmp_path):
    params = _params(clarity_brightness_db=1.0)
    recipe = _recipe(measured={"hf_excess_db": 3.0})  # excess > requested (1.0)

    floored, floored_audio = _run(
        tmp_path, "floored", params, mix_metadata=_metadata(recipe)
    )
    report = floored["texture_adaptation"]["clarity_gain_db"]
    assert report["requested"] == 1.0
    assert report["applied"] == 0.0
    assert report["applied"] >= 0.0  # never inverted into a cut

    # A 0.0 dB shelf is skipped, so the master equals the shelf-off run — proof
    # the withdrawal never became a cut.
    shelf_off, shelf_off_audio = _run(
        tmp_path,
        "shelf_off",
        _params(clarity_brightness_db=0.0),
        mix_metadata=_metadata(recipe),
    )
    assert "clarity_gain_db" not in shelf_off["texture_adaptation"]
    np.testing.assert_array_equal(floored_audio, shelf_off_audio)


# ── S4.1: the match EQ HF offset, bounded ───────────────────────────────


def test_match_eq_hf_offset_never_exceeds_the_two_db_bound():
    x = _program()
    for offset in (50.0, -50.0, 2.0, -2.0):
        plugins = build_match_eq(x, SR, [], None, hf_texture_offset_db=offset)
        for plugin in plugins:
            # pedalboard stores gain_db as float32; allow its representation error.
            assert abs(float(plugin.gain_db)) <= 2.0 + 1e-4


def test_match_eq_neutral_default_is_unchanged_by_the_offset_parameter():
    x = _program()
    default = build_match_eq(x, SR, [], None)
    explicit_zero = build_match_eq(x, SR, [], None, hf_texture_offset_db=0.0)
    assert [float(p.gain_db) for p in default] == [
        float(p.gain_db) for p in explicit_zero
    ]


def test_match_eq_hf_offset_changes_the_matcher_view():
    x = _flat_program()
    neutral = [round(float(p.gain_db), 2) for p in build_match_eq(x, SR, [], None)]
    shifted = [
        round(float(p.gain_db), 2)
        for p in build_match_eq(x, SR, [], None, hf_texture_offset_db=1.5)
    ]
    assert neutral != shifted


def test_match_eq_hf_offset_leaves_every_non_hf_band_bit_identical():
    """The offset may only narrow what the matcher sees for the HF bands.

    Applying the excess to the measured ENERGY (the pre-fix bug) moved the
    re-referencing mean and shifted EVERY band, adding brand-new cuts at
    non-HF frequencies (measured: 150 Hz and 60 Hz) that have nothing to do
    with the texture. S4.1 forbids exactly that ("never grants extra cut").
    """
    x = _flat_program()

    def pairs(offset: float) -> list[tuple[float, float]]:
        return [
            (float(p.cutoff_frequency_hz), float(p.gain_db))
            for p in build_match_eq(x, SR, [], None, hf_texture_offset_db=offset)
        ]

    neutral_non_hf = [p for p in pairs(0.0) if p[0] < MATCH_EQ_HF_BAND_HZ]
    shifted_non_hf = [p for p in pairs(2.0) if p[0] < MATCH_EQ_HF_BAND_HZ]
    # The non-HF bands are the regression surface: identical frequency, order
    # and gain — bit-identical, not merely "close".
    assert len(neutral_non_hf) > 0  # the assertion below is not vacuous
    assert neutral_non_hf == shifted_non_hf

    # … while the offset genuinely reached the HF bands.
    neutral_hf = [p for p in pairs(0.0) if p[0] >= MATCH_EQ_HF_BAND_HZ]
    shifted_hf = [p for p in pairs(2.0) if p[0] >= MATCH_EQ_HF_BAND_HZ]
    assert neutral_hf != shifted_hf


# ── S4.4: the exciter held neutral ──────────────────────────────────────


def test_exciter_held_neutral_when_a_bed_is_declared(tmp_path):
    aggressive = _params(
        exciter_enabled=True,
        exciter_band1_amount=0.5,
        exciter_band2_amount=0.5,
        exciter_band3_amount=0.5,
        exciter_band4_amount=0.5,
    )
    # A zero-amount exciter is the module's neutral path.
    silent = _params(exciter_enabled=True)
    recipe = _recipe()  # bed applied, all deltas 0 => the ONLY decision is the exciter

    held, held_audio = _run(
        tmp_path, "held", aggressive, mix_metadata=_metadata(recipe)
    )
    neutral, neutral_audio = _run(
        tmp_path, "silent", silent, mix_metadata=_metadata(recipe)
    )
    plain, plain_audio = _run(tmp_path, "plain_exciter", aggressive)

    assert held["texture_adaptation"]["exciter"] == {"held_neutral": True}
    np.testing.assert_array_equal(held_audio, neutral_audio)
    assert not np.array_equal(held_audio, plain_audio)


# ── S3: the report names only decisions actually taken ──────────────────


def test_deesser_is_not_reported_as_skipped_when_it_would_not_run(tmp_path):
    """``deesser_enabled=False`` renders the baseline, so a reported skip would
    name a decision that was never taken — the verifier's case."""
    recipe = _recipe(bed={"applied": True, "transient": True})
    program = _sibilant_program()

    off, off_audio = _run(
        tmp_path,
        "deesser_off_recipe",
        _params(deesser_enabled=False),
        mix_metadata=_metadata(recipe),
        program=program,
    )
    base, base_audio = _run(
        tmp_path, "deesser_off_base", _params(deesser_enabled=False), program=program
    )

    # Byte-identical to the no-recipe baseline: nothing was skipped.
    np.testing.assert_array_equal(off_audio, base_audio)
    assert "deesser" not in off["texture_adaptation"]
    # The recipe was still read and reported (profile/seed), though.
    assert off["texture_adaptation"]["profile"] == "commercial_alt_pop"


def test_exciter_is_not_reported_as_held_when_every_amount_is_already_zero(
    tmp_path,
):
    """A zero-amount exciter is already its neutral path, so ``held_neutral``
    would again name a decision that was never taken."""
    result, _ = _run(
        tmp_path,
        "exciter_zero",
        _params(exciter_enabled=True),  # enabled, all amounts 0.0
        mix_metadata=_metadata(_recipe()),
    )
    assert "exciter" not in result["texture_adaptation"]


# ── S5: the loudness compensation ───────────────────────────────────────


def test_target_lufs_compensation_raises_the_applied_gain():
    x = _program()
    base = target_lufs(x, SR, -14.0)
    comp = target_lufs(x, SR, -14.0, loudness_delta_lu=1.0)
    base_rms = np.sqrt(np.mean(base**2))
    comp_rms = np.sqrt(np.mean(comp**2))
    assert comp_rms / base_rms == pytest.approx(10 ** (1.0 / 20.0), rel=1e-9)


def test_loudness_compensation_lands_the_program_where_neutral_lands():
    program = _program()
    rng = np.random.default_rng(11)
    bed = 0.004 * rng.standard_normal(program.shape)
    x = program + bed
    delta = measure_lufs(x, SR) - measure_lufs(program, SR)
    assert delta > 0.0

    out = target_lufs(x, SR, -14.0, loudness_delta_lu=delta)
    gain = float(np.sum(out * x) / np.sum(x * x))  # exact scalar gain (out = g*x)
    program_landed = measure_lufs(program * gain, SR)

    # The PROGRAM lands on the target (where a neutral master lands) ...
    assert program_landed == pytest.approx(-14.0, abs=0.05)
    # ... and the meter reads higher by exactly the declared delta.
    assert measure_lufs(out, SR) == pytest.approx(-14.0 + delta, abs=0.05)


def test_loudness_compensation_direction_in_the_engine(tmp_path):
    params = _params()
    recipe = _recipe(measured={"loudness_delta_lu": 1.0})
    _, neutral_audio = _run(tmp_path, "lufs_neutral", params)
    result, comp_audio = _run(
        tmp_path, "lufs_comp", params, mix_metadata=_metadata(recipe)
    )
    assert result["texture_adaptation"]["loudness_compensation_lu"] == 1.0
    assert measure_lufs(comp_audio.T, SR) > measure_lufs(neutral_audio.T, SR)


def test_transparent_path_compensates_loudness_and_reports_only_with_a_recipe(
    tmp_path,
):
    """Requirement 3's intent also holds on the transparent delivery path: the
    loudness stage removes the declared texture contribution, so a textured
    transparent master is not quieter than a neutral one, and the report key
    appears ONLY when a recipe was read."""
    recipe = _recipe(measured={"loudness_delta_lu": 2.0})
    params = _params(processing_mode="transparent")

    neutral, neutral_audio = _run(tmp_path, "tr_neutral", params)
    comp, comp_audio = _run(tmp_path, "tr_comp", params, mix_metadata=_metadata(recipe))

    assert "texture_adaptation" not in neutral  # no recipe ⇒ no key
    assert comp["texture_adaptation"]["loudness_compensation_lu"] == 2.0
    assert measure_lufs(comp_audio.T, SR) > measure_lufs(neutral_audio.T, SR)


# ── S4 (boothed stages): the bed-below-threshold raise ──────────────────


def test_multiband_high_threshold_raised_above_the_declared_bed(tmp_path):
    params = _params(
        multiband_enabled=True,
        multiband_high_ratio=2.0,
        multiband_high_threshold_db=-40.0,
    )
    recipe = _recipe(bed={"hiss_dbfs": -30.0, "crackle_dbfs": -33.0})
    mapped = _multiband_params_from_mastering(params, recipe)
    assert mapped.bands[2].threshold_db == -27.0  # max(-40, -30 + 3 dB margin)

    result, _ = _run(tmp_path, "mb", params, mix_metadata=_metadata(recipe))
    assert result["texture_adaptation"]["multiband_high"] == {
        "threshold_db": -27.0,
        "offset_db": 13.0,
    }


def test_multiband_high_threshold_untouched_when_bed_already_below(tmp_path):
    params = _params(
        multiband_enabled=True,
        multiband_high_ratio=2.0,
        multiband_high_threshold_db=-20.0,
    )
    recipe = _recipe(bed={"hiss_dbfs": -48.0, "crackle_dbfs": -54.0})
    mapped = _multiband_params_from_mastering(params, recipe)
    assert mapped.bands[2].threshold_db == -20.0  # default threshold already clears it

    result, _ = _run(tmp_path, "mb_noop", params, mix_metadata=_metadata(recipe))
    assert "multiband_high" not in result["texture_adaptation"]


# ── S7: the gate correction ─────────────────────────────────────────────


def test_the_gate_correction_undoes_both_bed_biases():
    analysis = AnalysisResult(
        integrated_lufs=-13.7,
        true_peak_db=-7.0,
        dynamic_range_db=12.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=SR,
        channels=2,
        crest_factor_db=8.9,
        is_already_mastered=True,
    )
    recipe = _recipe(measured={"crest_delta_db": 2.0, "centroid_delta_hz": 500.0})
    corrected = _texture_corrected_analysis(analysis, recipe)
    assert corrected is not None
    assert corrected.crest_factor_db == pytest.approx(10.9)
    assert corrected.spectral_centroid == pytest.approx(2500.0)


def test_no_recipe_returns_the_analysis_object_untouched():
    analysis = AnalysisResult(
        integrated_lufs=-13.7,
        true_peak_db=-7.0,
        dynamic_range_db=12.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=SR,
        channels=2,
        crest_factor_db=8.9,
    )
    assert _texture_corrected_analysis(analysis, None) is analysis


def test_engine_reports_the_gate_correction_when_analysis_is_present(tmp_path):
    analysis = AnalysisResult(
        integrated_lufs=-13.7,
        true_peak_db=-7.0,
        dynamic_range_db=12.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=SR,
        channels=2,
        crest_factor_db=8.9,
        is_already_mastered=True,
    )
    in_path = tmp_path / "gate_in.wav"
    out_path = tmp_path / "gate_out.wav"
    _write_wav(in_path, _program())
    recipe = _recipe(measured={"crest_delta_db": 1.5, "centroid_delta_hz": 300.0})
    result = process_audio(
        in_path,
        out_path,
        _params(),
        analysis_result=analysis,
        mix_metadata=_metadata(recipe),
    )
    assert result["texture_adaptation"]["gate_correction"] == {
        "crest_delta_db": 1.5,
        "centroid_delta_hz": 300.0,
    }


# ── S3: the report shape ────────────────────────────────────────────────


def test_report_carries_profile_and_seed_when_a_recipe_is_applied(tmp_path):
    result, _ = _run(tmp_path, "shape", _params(), mix_metadata=_metadata(_recipe()))
    report = result["texture_adaptation"]
    assert report["profile"] == "commercial_alt_pop"
    assert report["seed"] == 20261016


def test_report_key_is_absent_when_no_recipe(tmp_path):
    result, _ = _run(tmp_path, "absent", _params())
    assert "texture_adaptation" not in result
    assert "warnings" in result


def test_bound_constant_is_two_db():
    assert MATCH_EQ_HF_OFFSET_LIMIT_DB == 2.0
