"""Focused tests for the Brik decision layer — the route verdict (T1).

Covers S1 (verdict shape), S2 (needs_mix detection from crest + DR) and
S14 (SessionData persistence).

These tests pin the CONTRACT of ``audiomind.analysis.verdict``:

- ``build_verdict`` turns already-measured ``AnalysisResult`` numbers into a
  routing verdict, with NO new DSP and NO audio decoding.
- The three regimes documented in ``_detect_already_mastered`` must map to the
  right ``needs_mix``: raw mix -> True, finished mix -> False, mastered -> False.
- An already-mastered track NEVER needs a mix: separating a balanced master
  can only degrade it.
- ``AudioVerdict`` round-trips through JSON, because it is persisted on
  ``SessionData`` and shipped in the agent job result.
- A ``SessionData`` persisted before this feature loads with ``verdict=None``.
"""
import sys

sys.path.insert(0, "src")

import json
from pathlib import Path

import pytest

from audiomind.analysis.analyzer import TARGET_BANDS_HZ, get_genre_target_profile
from audiomind.analysis.verdict import (
    DEFICIENCY_THRESHOLD_DB,
    AudioVerdict,
    Deficiency,
    Route,
    build_verdict,
    compute_deficiencies,
)
from audiomind.models.audio import AnalysisResult, SessionData


def _analysis(
    *,
    crest: float,
    dr: float,
    lufs: float = -18.0,
    mastered: bool = False,
    mastered_conf: float = 0.0,
    genre: str = "pop",
) -> AnalysisResult:
    """An AnalysisResult with only the fields the verdict reads set explicitly.

    Built directly (not measured) on purpose: the verdict is a pure function of
    the numbers, so the test never pays for an audio decode.
    """
    return AnalysisResult(
        integrated_lufs=lufs,
        true_peak_db=-1.0,
        dynamic_range_db=dr,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=180.0,
        sample_rate=44100,
        channels=2,
        detected_genre=genre,
        genre_confidence=0.8,
        crest_factor_db=crest,
        is_already_mastered=mastered,
        mastering_confidence=mastered_conf,
    )


# ── S2: the three regimes ─────────────────────────────────────────────────


def test_raw_mix_needs_mix():
    """Crest 16-24 dB with DR 14-20 dB is a raw, unmixed track."""
    verdict = build_verdict(_analysis(crest=20.0, dr=17.0))
    assert verdict.needs_mix is True
    assert verdict.recommended_path == "mix_then_master"


def test_finished_mix_does_not_need_mix():
    """Crest 12-16 dB is a finished mix: master it, do not re-balance it."""
    verdict = build_verdict(_analysis(crest=14.0, dr=12.0))
    assert verdict.needs_mix is False
    assert verdict.recommended_path == "master_only"


def test_mastered_track_does_not_need_mix():
    """Crest <= 12 dB is already mastered: master_only, never separate."""
    verdict = build_verdict(
        _analysis(crest=9.0, dr=6.0, mastered=True, mastered_conf=0.9)
    )
    assert verdict.needs_mix is False
    assert verdict.recommended_path == "master_only"


def test_already_mastered_forces_master_only_even_with_raw_crest():
    """The DSP's own mastered flag WINS over a raw-looking crest.

    ``is_already_mastered`` is a weighted score, not a single-metric guess: when
    it fires, the track is balanced and separating it would only hurt. This is
    the 'si el audio ya venía mezclado simplemente aplicaba la masterización'
    guarantee at the verdict level.
    """
    verdict = build_verdict(
        _analysis(crest=18.0, dr=16.0, mastered=True, mastered_conf=0.85)
    )
    assert verdict.needs_mix is False
    assert verdict.recommended_path == "master_only"


def test_unmeasurable_crest_defaults_to_needs_mix():
    """Silence / unmeasurable crest is conservative: assume a mix is needed.

    A verdict of 'master_only' on a track we could not measure would skip the
    mix on a track that may badly need it. Fail toward doing the work.
    """
    verdict = build_verdict(_analysis(crest=0.0, dr=0.0))
    assert verdict.needs_mix is True


def test_confidence_is_bounded():
    """Confidence is always a 0..1 float, never a raw score."""
    for crest, dr in [(20.0, 17.0), (14.0, 12.0), (9.0, 6.0)]:
        verdict = build_verdict(_analysis(crest=crest, dr=dr))
        assert 0.0 <= verdict.confidence <= 1.0


# ── S1: verdict shape ─────────────────────────────────────────────────────


def test_verdict_always_offers_both_routes():
    """Every verdict carries both routes, exactly one recommended."""
    verdict = build_verdict(_analysis(crest=20.0, dr=17.0))
    ids = {route.id for route in verdict.routes}
    assert ids == {"mix_then_master", "master_only"}
    recommended = [route for route in verdict.routes if route.recommended]
    assert len(recommended) == 1
    assert recommended[0].id == verdict.recommended_path


def test_verdict_reasoning_key_is_enum_like():
    """A reasoning key, not free prose: the UI translates it."""
    verdict = build_verdict(_analysis(crest=20.0, dr=17.0))
    assert verdict.reasoning_key in {
        "raw_mix_detected",
        "finished_mix_detected",
        "already_mastered",
        "unmeasurable",
    }


# ── S14: persistence ──────────────────────────────────────────────────────


def test_verdict_round_trips_json():
    """The verdict is stored and shipped, so JSON mode must be lossless."""
    verdict = build_verdict(_analysis(crest=20.0, dr=17.0, genre="reggaeton"))
    dumped = verdict.model_dump(mode="json")
    restored = AudioVerdict.model_validate(json.loads(json.dumps(dumped)))
    assert restored == verdict


def test_session_data_persists_verdict():
    """SessionData carries the verdict so a reload does not lose the analysis."""
    verdict = build_verdict(_analysis(crest=20.0, dr=17.0))
    session = SessionData(session_id="s1", verdict=verdict)
    reloaded = SessionData.model_validate(
        json.loads(json.dumps(session.model_dump(mode="json")))
    )
    assert reloaded.verdict is not None
    assert reloaded.verdict.needs_mix is True


def test_session_data_without_verdict_loads():
    """A session persisted before the feature loads with verdict=None."""
    session = SessionData.model_validate({"session_id": "old-session"})
    assert session.verdict is None


def test_session_data_validates_in_a_fresh_interpreter():
    """The forward reference must NOT depend on import order.

    In-process tests cannot catch this: this module imports the verdict at the
    top, so ``AudioVerdict`` is already resolved by the time any assertion runs.
    The real failure lives in a process that touches ``SessionData`` FIRST --
    and that is not hypothetical: ``services/session_backend.py``,
    ``session_store.py`` and ``storage/cache.py`` all import ``SessionData``
    without importing the verdict. An unresolved forward reference makes pydantic
    refuse the model entirely, so ``session_backend.load_all`` drops EVERY
    persisted row and a reload silently loses the whole session list.

    Every genuine entry point is covered, across BOTH import orders and all three
    construction paths. A fix that only patches ``model_validate`` passes the
    first assert and still loses data through ``SessionData(...)``, which the
    codebase uses just as much.
    """
    import subprocess
    import sys

    src = str(Path(__file__).resolve().parents[1] / "src")
    construction = (
        "from audiomind.models.audio import SessionData\n"
        "assert SessionData.model_validate({'session_id': 'a'}).verdict is None\n"
        "assert SessionData(session_id='b').verdict is None\n"
        "assert SessionData.model_validate_json('{\"session_id\": \"c\"}').verdict is None\n"
    )
    bodies = {
        "models.audio alone": construction,
        "analysis.verdict first": (
            "import audiomind.analysis.verdict  # noqa: F401\n" + construction
        ),
        "services.agent_jobs first": (
            "import audiomind.services.agent_jobs  # noqa: F401\n" + construction
        ),
        "services.session_backend first (real loader)": (
            "import audiomind.services.session_backend  # noqa: F401\n" + construction
        ),
        "session_store first": (
            "import audiomind.session_store  # noqa: F401\n" + construction
        ),
        "storage.cache first": (
            "import audiomind.storage.cache  # noqa: F401\n" + construction
        ),
    }

    for label, body in bodies.items():
        code = f"import sys\nsys.path.insert(0, {src!r})\n" + body + "print('ok')\n"
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, (
            f"SessionData no valida con el orden '{label}': su referencia "
            f"adelantada a AudioVerdict depende del orden de imports.\n"
            f"{result.stderr}"
        )
        assert "ok" in result.stdout


# ── Model shape ───────────────────────────────────────────────────────────


def test_deficiency_shape():
    """Deficiencies name a band, a signed delta and a direction."""
    d = Deficiency(band_hz=60, delta_db=-3.2, direction="lacks")
    assert d.band_hz == 60
    assert d.direction == "lacks"


def test_route_shape():
    """Routes carry user-facing Spanish copy plus the recommendation flag."""
    r = Route(
        id="master_only",
        label_es="Solo masterizar",
        description_es="El audio ya tiene una mezcla terminada.",
        recommended=True,
    )
    assert r.recommended is True


# ── S3: deficiencies against the genre target ─────────────────────────────
#
# The engine already moves every band by ``target - current_shape`` where
# ``current_shape`` is the measured energy RELATIVE to its own mean. The
# verdict must name the same gap, or the chat would contradict the DSP.


def test_deficiency_matches_the_engine_delta():
    """The reported delta IS the gain the Match EQ would apply.

    Same math as ``engine.py:534-552``: subtract the measurement's own mean
    (the shape) and compare against the genre target. A pure level difference
    is NOT a deficiency — only a shape difference is.

    The expectation is recomputed here from the REAL profile, so this test
    fails if either side of the contract drifts — not just if the
    implementation changes to match a hardcoded copy of itself.
    """
    measured = [-40.0, -30.0, -20.0, -10.0, -20.0, -30.0, -40.0, -50.0]
    genre = "other"
    deficiencies = compute_deficiencies(measured, genre=genre)
    by_band = {d.band_hz: d for d in deficiencies}

    profile = get_genre_target_profile(genre)
    avg = sum(measured) / len(measured)
    for band_hz, target, energy in zip(
        TARGET_BANDS_HZ, profile, measured, strict=False
    ):
        shape = energy - avg
        if abs(shape) > 20.0:
            assert band_hz not in by_band
            continue
        expected = target - shape
        if abs(expected) <= DEFICIENCY_THRESHOLD_DB:
            assert band_hz not in by_band
        else:
            assert by_band[band_hz].delta_db == pytest.approx(expected, abs=0.05)


def test_target_relative_offset_is_the_normalization():
    """The genre profile is relative to pink noise, so the measurement is too.

    Drift the SAME 3 dB onto every band (a pure level change): the shape vs
    the target must not change, so no band may flip its direction.
    """
    measured = [-40.0, -30.0, -20.0, -10.0, -20.0, -30.0, -40.0, -50.0]
    louder = [b + 3.0 for b in measured]

    base = {(d.band_hz, d.direction) for d in compute_deficiencies(measured)}
    shifted = {(d.band_hz, d.direction) for d in compute_deficiencies(louder)}

    # Bands within the threshold of the boundary may enter/leave the list;
    # no band that appears twice on both runs may change its direction.
    common = {hz for hz, _ in base} & {hz for hz, _ in shifted}
    for hz in common:
        assert (hz, "lacks") in base or (hz, "excess") in base
        assert (
            (hz, "lacks") in base and (hz, "lacks") in shifted
        ) or (
            (hz, "excess") in base and (hz, "excess") in shifted
        )


def test_threshold_drops_inaudible_deltas():
    """A band within 2 dB of the target is not worth telling the user about."""
    flat = [-20.0, -20.0, -20.0, -20.0, -20.0, -20.0, -20.0, -20.0]
    deficiencies = compute_deficiencies(flat, genre="jazz")
    # jazz's target spans at most 1.0 dB around pink noise -> nothing passes.
    assert deficiencies == []


def test_direction_sign_follows_the_lack():
    """Positive delta means the band LACKS energy; negative means it EXCESSes.

    Built from MUSICAL distances, not extremes: a bass-forward, mid-recessed
    shape where every band still sits well inside the runaway guard. The rule
    under test is the sign convention, not the guard (covered separately).
    """
    measured = [-18.0, -20.0, -26.0, -32.0, -32.0, -28.0, -26.0, -28.0]
    deficiencies = compute_deficiencies(measured, genre="other")
    by_band = {d.band_hz: d for d in deficiencies}

    # 60 Hz sits 10 dB above the mean -> far above the near-flat target: excess.
    assert by_band[60].delta_db < 0
    assert by_band[60].direction == "excess"
    # 1000 Hz sits 4 dB below the mean -> below target: lacks.
    assert by_band[1000].delta_db > 0
    assert by_band[1000].direction == "lacks"


def test_direction_sign_is_consistent_everywhere():
    """The direction can never contradict the sign of its own delta."""
    measured = [-18.0, -20.0, -26.0, -32.0, -32.0, -28.0, -26.0, -28.0]
    for d in compute_deficiencies(measured, genre="reggaeton"):
        assert d.direction == ("lacks" if d.delta_db > 0 else "excess")


def test_deficiencies_are_ordered_by_magnitude():
    """The UI shows them in order; the biggest gap must come first."""
    measured = [0.0, -10.0, -20.0, -30.0, -40.0, -50.0, -60.0, -70.0]
    deficiencies = compute_deficiencies(measured, genre="pop")
    magnitudes = [abs(d.delta_db) for d in deficiencies]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_unknown_genre_falls_back_to_other_profile():
    """An unknown genre never produces an empty target: 'other' is used."""
    measured = [0.0, -10.0, -20.0, -30.0, -40.0, -50.0, -60.0, -70.0]
    unknown = compute_deficiencies(measured, genre="polka")
    fallback = compute_deficiencies(measured, genre="other")
    assert unknown == fallback


def test_missing_band_measurement_is_skipped_not_guessed():
    """A short/short-circuited band list yields no band, never a fabricated one."""
    assert compute_deficiencies([-20.0, -20.0], genre="pop") == []


def test_silence_yields_no_deficiencies():
    """Digital silence (every band at the floor) is not a shape to report."""
    floor = [-80.0] * 8
    assert compute_deficiencies(floor, genre="pop") == []


def test_runaway_band_is_excluded():
    """A band separated from the material's own mean by >20 dB is not folded
    back as signal: that is a gap, not musical content."""
    # One band 60 dB below the rest: its delta vs any target is huge.
    measured = [-20.0, -20.0, -20.0, -20.0, -20.0, -20.0, -20.0, -80.0]
    band_hz = {d.band_hz for d in compute_deficiencies(measured, genre="other")}
    assert 15000 not in band_hz


def test_verdict_carries_the_deficiencies():
    """``build_verdict`` accepts the measurement and attaches the bands.

    Without band energies the list stays empty; the verdict itself is
    unchanged. This is the backward-compatible signature.
    """
    analysis = _analysis(crest=20.0, dr=17.0, genre="other")
    assert build_verdict(analysis).deficiencies == []

    measured = [0.0, -10.0, -20.0, -30.0, -40.0, -50.0, -60.0, -70.0]
    with_bands = build_verdict(analysis, band_energies_db=measured)
    assert len(with_bands.deficiencies) > 0
    # Everything else about the verdict is untouched by the measurement.
    assert with_bands.needs_mix is True
    assert with_bands.recommended_path == "mix_then_master"
