"""TDD tests for the Mix Engine creative exploration (Paso 08).

RED → GREEN → REFACTOR contract for ``audiomind.processing.creative``
(plan maestro ``odd/tasks/plan-motor-de-mezcla.md``, paso 08 — repurpose
of the "Exploración creativa acotada", ``VIABILIDAD_MOTOR_DE_MEZCLA.md``
§4.2):

* the variant space is CONTINUOUS (floats sampled inside per-param
  envelopes, reproducible by seed) — never a finite preset table,
* ``creativity`` ∈ [0, 1] scales the deviation from the standard:
  0 = strict standard (bit-identical routing), 1 = wide exploration
  within the envelope,
* every sampled value stays INSIDE the standard's envelope
  (``min <= value <= max`` for every param of every variant),
* ``apply_variant_to_profiles`` maps a variant onto fresh copies of the
  six routing roots (EQ / pan / dimension / compressor / bus / trims)
  without ever mutating the shared module constants,
* ``variant_is_valid`` rejects variants that violate the positional /
  QC checks (mono compatible AND no anti-phase stems AND ``all_ok``
  QC summary); manual mode marks the output ``non_standard`` instead of
  rejecting it ("no se bloquea"),
* ``run_creative_mode`` never blocks: rejected variants are marked and
  the batch continues; same seed → the same report (reproducible A/B),
* ``build_mix`` integration: ``creative_variants=0`` / no seed → the
  exact previous routing (no ``creative_report`` key); creativity 0 with
  variants renders byte-identical principal audio; variant WAVs live at
  ``outputs/{session_id}_mix_creative_{i}.wav`` and only OK variants
  produce files.

The synthetic fixtures are the same tone engine the Mix Engine tests
use (``split_audio`` monkeypatched); the REAL ``run_qc_checks`` flags
the sine fixture (crest ≈ 3 dB < the 6 dB low-level window), so
integration tests that expect *accepted* variants patch
``mix_engine.run_qc_checks`` with an ``all_ok`` stand-in — the same
policy the principal QC tests follow.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf

import audiomind.processing.mix_engine as mix_engine
from audiomind.config import settings
from audiomind.processing import creative
from audiomind.processing.creative import (
    CREATIVE_PARAM_SPACE,
    apply_variant_to_profiles,
    draw_variant,
    run_creative_mode,
    variant_is_valid,
)

_SR = 44100
_STEM_SPECS = {
    "drums": (120.0, 0.75),
    "bass": (90.0, 1.0),
    "other": (330.0, 1.0),
    "vocals": (440.0, 1.25),
}


def _write_tone(path: Path, hz: float, seconds: float, sr: int = _SR) -> None:
    """Write a short mono sine tone (synthetic fixture, no DSP deps)."""
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), sr)


def _register_session(tmp_path: Path) -> str:
    """Insert a session with an input tone directly into the store."""
    session_id = str(uuid.uuid4())
    original_path = tmp_path / "input.wav"
    _write_tone(original_path, hz=220.0, seconds=1.0)
    from audiomind.api.upload import sessions
    from audiomind.models.audio import ProcessingStatus, SessionData

    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original_path),
        original_filename=original_path.name,
    )
    return session_id


def _fake_split(input_path: str | Path, output_dir: str | Path | None = None,
                model: str = "htdemucs") -> dict:
    """Stand-in for Demucs: writes 4 distinct synthetic stems synchronously."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        stem_path = out / f"{name}.wav"
        _write_tone(stem_path, hz=hz, seconds=seconds)
        stems[name] = str(stem_path)
    return {
        "stems": stems,
        "sample_rate": _SR,
        "duration_seconds": 1.25,
        "stem_audio_dir": str(out),
    }


def _read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Decode a WAV into (2, N) float + sample rate."""
    with sf.SoundFile(str(path), "r") as f:
        sr = int(f.samplerate)
        frames = f.read(dtype="float32", always_2d=True)
    return frames.T, sr


def _qc_all_ok(bus: np.ndarray, sr: int, pan_info: dict | None = None) -> dict:
    """QC stand-in: every check passes (accepted-variant integration tests)."""
    return {
        "mono": {"ok": True, "details": {}},
        "phase": {"ok": True, "details": {}},
        "sibilance_5k": {"ok": True, "details": {}},
        "muddy_250": {"ok": True, "details": {}},
        "honky_500": {"ok": True, "details": {}},
        "low_level_listen": {"ok": True, "details": {}},
        "summary": {"all_ok": True, "flagged": []},
        "note": "test stand-in",
    }


def _qc_flagged(bus: np.ndarray, sr: int, pan_info: dict | None = None) -> dict:
    """QC stand-in: low_level_listen flagged (every variant would fail)."""
    report = _qc_all_ok(bus, sr, pan_info)
    report["low_level_listen"] = {"ok": False, "details": {}}
    report["summary"] = {"all_ok": False, "flagged": ["low_level_listen"]}
    return report


def _validation_ok() -> dict:
    """Positional validation pass (mirrors ``validate_positions``)."""
    return {
        "roles": {},
        "stems": {},
        "mono_check": {
            "bus_loss_db": -1.0,
            "mono_compatible": True,
            "anti_phase_stems": [],
        },
        "human_decision": [],
    }


def _validation_bad() -> dict:
    """Positional validation fail: mono-incompatible AND anti-phase stems."""
    return {
        "roles": {},
        "stems": {},
        "mono_check": {
            "bus_loss_db": -12.0,
            "mono_compatible": False,
            "anti_phase_stems": ["other"],
        },
        "human_decision": [{"stem": "other", "reason": "anti-phase"}],
    }


class TestCreativeParamSpace:
    """The space is a CONTINUOUS envelope, never a finite preset table."""

    def test_space_is_large_and_continuous(self):
        """≥ 40 params, every one a real (min, max) envelope with the
        standard inside — richer than any finite preset list."""
        assert len(CREATIVE_PARAM_SPACE) >= 40
        stages = {entry["stage"] for entry in CREATIVE_PARAM_SPACE}
        # The plan's "bits de todo": EQ, comp, sends(dimension), pan, bus.
        assert {"eq", "comp", "dimension", "pan", "bus", "trim"} <= stages

    def test_every_param_has_valid_envelope_and_source(self):
        """Invariants: min < max, standard inside [min, max], source cited."""
        for entry in CREATIVE_PARAM_SPACE:
            assert entry["min"] < entry["max"], entry["key"]
            assert entry["min"] <= entry["standard"] <= entry["max"], entry["key"]
            assert entry["source"], entry["key"]

    def test_space_is_continuous_not_a_finite_grid(self):
        """120 deterministic draws at creativity 1.0 → ≥ 50 distinct values
        per param. A finite preset table could never reach this (each
        param would collapse to ≲ presets values). Params whose STANDARD
        sits at the envelope edge (e.g. the drums 2nd segment cut, q 1.4 =
        the book range max) clamp half their mass on that edge — still
        dozens of distinct values, never a grid."""
        distinct: dict[str, set[float]] = {}
        for i in range(120):
            variant = draw_variant(1000 + i, creativity=1.0)
            for key, value in variant.items():
                distinct.setdefault(key, set()).add(value)
        assert set(distinct) == {entry["key"] for entry in CREATIVE_PARAM_SPACE}
        for key, values in distinct.items():
            assert len(values) >= 50, f"{key}: only {len(values)} distinct values"

    def test_zero_creativity_returns_exact_standards(self):
        """creativity=0 → EVERY param takes its standard value exactly
        (the strict-standard routing that stays bit-identical)."""
        variant = draw_variant(42, creativity=0.0)
        standards = {entry["key"]: entry["standard"] for entry in CREATIVE_PARAM_SPACE}
        assert variant == standards
        assert all(isinstance(v, float) for v in variant.values())

    def test_draw_is_reproducible_by_seed(self):
        """Same seed → the exact same variant (honest A/B contract)."""
        assert draw_variant(7, creativity=0.5) == draw_variant(7, creativity=0.5)
        # Two different seeds must not systematically collide.
        assert draw_variant(7, creativity=1.0) != draw_variant(8, creativity=1.0)

    def test_draw_never_leaves_the_envelope(self):
        """Rejection-sampling guarantee level 0: every sampled value stays
        inside its (min, max) envelope, whatever the seed/creativity."""
        bounds = {entry["key"]: (entry["min"], entry["max"])
                  for entry in CREATIVE_PARAM_SPACE}
        for seed in range(60):
            variant = draw_variant(seed, creativity=1.0)
            for key, value in variant.items():
                lo, hi = bounds[key]
                assert lo <= value <= hi, f"{key}: {value} ∉ [{lo}, {hi}]"

    def test_deviation_scales_with_creativity(self):
        """Higher creativity spreads wider around the standard."""
        mean_abs_dev = {}
        for creativity in (0.2, 0.6, 1.0):
            deviations = []
            for seed in range(30):
                variant = draw_variant(seed, creativity=creativity)
                deviations.extend(
                    abs(value - entry["standard"])
                    for entry, (_, value) in zip(
                        CREATIVE_PARAM_SPACE, variant.items(), strict=True
                    )
                )
            mean_abs_dev[creativity] = float(np.mean(deviations))
        assert mean_abs_dev[0.2] < mean_abs_dev[0.6] < mean_abs_dev[1.0]


class TestTrimParamSpace:
    """T1 — faders por stem: cada stem (drums/bass/other/vocals) tiene un
    trim ±6 dB en el espacio de parámetros, mapeado a su key. Neutral
    sigue siendo 0.0 dB en los cuatro."""

    FIVE = 5.0

    def _trim_entries(self):
        return [e for e in CREATIVE_PARAM_SPACE if e["stage"] == "trim"]

    def test_all_four_stems_have_a_trim(self):
        """Los 4 stems tienen entrada stage=trim (drums, bass, other, vocals)."""
        stems = {e["stem"] for e in self._trim_entries()}
        assert stems == {"drums", "bass", "other", "vocals"}

    def test_trim_envelope_is_plusminus_6_db(self):
        """Cada trim es ±6 dB con standard 0.0 (fader manual de balance)."""
        for entry in self._trim_entries():
            assert entry["min"] == -6.0, entry["key"]
            assert entry["max"] == 6.0, entry["key"]
            assert entry["standard"] == 0.0, entry["key"]
            assert entry["min"] < entry["standard"] < entry["max"]

    def test_trim_paths_resolve_on_the_trim_root(self):
        """Aplicar un trim de un stem deja los demás en 0.0."""
        variant = {"trim.drums_db": 2.5, "trim.vocals_db": -1.5}
        _, _, _, _, _, trims = apply_variant_to_profiles(variant)
        assert trims["drums_db"] == 2.5
        assert trims["bass_db"] == 0.0
        assert trims["other_db"] == 0.0
        assert trims["vocals_db"] == -1.5

    def test_trim_entries_are_wired_into_the_space(self):
        """Las keys de trim existen en CREATIVE_PARAM_SPACE (no hay keys
        huérfanas en el root que el reporte no documente)."""
        space_keys = {e["key"] for e in CREATIVE_PARAM_SPACE}
        trim_keys = {e["key"] for e in self._trim_entries()}
        assert trim_keys <= space_keys
        assert trim_keys == {
            "trim.drums_db",
            "trim.bass_db",
            "trim.other_db",
            "trim.vocals_db",
        }


class TestApplyVariantToProfiles:
    """Variant params → fresh routing roots; base constants never mutate."""

    def test_apply_none_returns_neutral_distinct_copies(self):
        """No variant → 6 roots with the base values; objects are fresh
        copies (mutating one never leaks into the module constants)."""
        (profiles, pan, dimension, comp, bus, trims) = apply_variant_to_profiles(None)
        for root, stage in (
            (profiles, "eq"),
            (pan, "pan"),
            (dimension, "dimension"),
            (comp, "comp"),
            (bus, "bus"),
            (trims, "trim"),
        ):
            for entry in CREATIVE_PARAM_SPACE:
                if entry["stage"] == stage:
                    assert _path_get(root, entry["path"]) == entry["standard"]
        # Isolation: clobber the returned EQ root, the base stays intact.
        from audiomind.processing.magic_frequencies import MAGIC_PROFILES

        profiles["vocals"][0]["gain_db"] = 99.0
        assert MAGIC_PROFILES["vocals"][0]["gain_db"] == -2.0  # 200 Hz cut

    def test_apply_partial_variant_touches_only_that_param(self):
        """A one-key variant moves exactly that param on its root."""
        variant = {"eq.vocals.0.gain_db": -4.0}
        profiles, _, _, _, _, _ = apply_variant_to_profiles(variant)
        assert profiles["vocals"][0]["gain_db"] == -4.0
        # The neighbouring band of the same stem stays at its standard.
        assert profiles["vocals"][1]["gain_db"] == pytest.approx(0.75)

    def test_apply_drums_band_compressor_path(self):
        """Nested paths resolve: comp drums band_compressor lands inside
        the drums profile's sub-dict."""
        variant = {"comp.drums.band_compressor.ratio": 6.0}
        _, _, _, comp, _, _ = apply_variant_to_profiles(variant)
        assert comp["drums"]["band_compressor"]["ratio"] == 6.0
        assert comp["vocals"]["ratio"] == pytest.approx(4.0)

    def test_apply_bus_and_trim_roots(self):
        """Bus params land on the bus profile; trims land on the trims root."""
        variant = {"bus.ratio": 3.0, "trim.vocals_db": -0.5}
        _, _, _, _, bus, trims = apply_variant_to_profiles(variant)
        assert bus["ratio"] == 3.0
        assert trims["vocals_db"] == -0.5

    def test_apply_unknown_key_raises(self):
        """A key outside the param space is a contract violation."""
        with pytest.raises(KeyError):
            apply_variant_to_profiles({"eq.nope.0.gain_db": 1.0})

    def test_full_variant_applies_every_param_at_its_path(self):
        """Wiring proof: after applying a full draw, walking every param's
        path on its stage root yields exactly the drawn value."""
        variant = draw_variant(9, creativity=0.8)
        roots = dict(
            zip(
                ("eq", "pan", "dimension", "comp", "bus", "trim"),
                apply_variant_to_profiles(variant),
                strict=True,
            )
        )
        for entry in CREATIVE_PARAM_SPACE:
            root = roots[entry["stage"]]
            assert _path_get(root, entry["path"]) == variant[entry["key"]], (
                f"{entry['key']} not applied at its path"
            )


class TestVariantIsValid:
    """Rejection sampling: positional + QC checks; manual never blocks."""

    def test_valid_when_positional_and_qc_ok(self):
        assert variant_is_valid(_validation_ok(), _qc_all_ok(np.zeros((2, 4)), _SR))

    def test_rejected_when_qc_flagged(self):
        assert not variant_is_valid(
            _validation_ok(), _qc_flagged(np.zeros((2, 4)), _SR)
        )

    def test_rejected_when_mono_incompatible(self):
        assert not variant_is_valid(
            _validation_bad(), _qc_all_ok(np.zeros((2, 4)), _SR)
        )

    def test_manual_never_rejects(self):
        """Manual mode: the producer's deliberate choice is marked, not
        blocked — even with failing positional/QC checks."""
        assert variant_is_valid(
            _validation_bad(), _qc_flagged(np.zeros((2, 4)), _SR), manual=True
        )


class TestRunCreativeMode:
    """The batch loop: reproducible, non-blocking, capped attempts."""

    def _fake_render(self, validation, qc):
        def render(attempt_seed: int, params: dict[str, float]) -> dict:
            audio = np.zeros((2, 16), dtype=np.float32)
            return {"validation": validation, "qc": qc, "bus": audio}

        return render

    def _fake_save(self, calls: list):
        def save(index: int, attempt_seed: int, bus: np.ndarray) -> str:
            calls.append((index, attempt_seed))
            return f"/tmp/creative_{index}.wav"

        return save

    def test_report_shape_with_ok_variants(self):
        """Every ok entry carries index/seed/params/checks/non_standard/path."""
        report = run_creative_mode(
            5,
            creativity=0.6,
            variants_count=3,
            render=self._fake_render(
                _validation_ok(), _qc_all_ok(np.zeros((2, 4)), _SR)
            ),
            save=self._fake_save([]),
        )
        assert report["seed"] == 5
        assert report["creativity"] == 0.6
        assert report["status"] == "active"
        assert len(report["variants"]) == 3
        assert report["rejected_count"] == 0
        for i, entry in enumerate(report["variants"]):
            assert entry["index"] == i
            assert entry["status"] == "ok"
            assert entry["qc_ok"] is True
            assert entry["positional_ok"] is True
            assert entry["non_standard"] is False
            assert entry["path"] == f"/tmp/creative_{i}.wav"
            assert set(entry["params"]) == {
                spec["key"] for spec in CREATIVE_PARAM_SPACE
            }

    def test_report_reproducible_by_seed(self):
        """Same seed → same params, same statuses, same paths."""
        first = run_creative_mode(
            11,
            creativity=0.9,
            variants_count=2,
            render=self._fake_render(
                _validation_ok(), _qc_all_ok(np.zeros((2, 4)), _SR)
            ),
            save=self._fake_save([]),
        )
        second = run_creative_mode(
            11,
            creativity=0.9,
            variants_count=2,
            render=self._fake_render(
                _validation_ok(), _qc_all_ok(np.zeros((2, 4)), _SR)
            ),
            save=self._fake_save([]),
        )
        assert first["variants"] == second["variants"]

    def test_rejections_never_block_the_batch(self):
        """All-failing QC → every entry rejected, no file saved, the report
        still comes back complete (never raises)."""
        saves: list = []
        report = run_creative_mode(
            3,
            creativity=0.8,
            variants_count=4,
            render=self._fake_render(
                    _validation_ok(), _qc_flagged(np.zeros((2, 4)), _SR)
                ),
            save=self._fake_save(saves),
        )
        assert len(report["variants"]) == 4
        assert report["rejected_count"] == 4
        assert all(entry["status"] == "rejected" for entry in report["variants"])
        assert all(entry["path"] is None for entry in report["variants"])
        assert saves == []  # rejected variants produce no file

    def test_rejection_resamples_then_ok(self):
        """rejection sampling: after a rejected attempt the next seed
        (seed + index*1000 + attempt) is drawn and can pass."""
        calls: list = []

        def render(attempt_seed: int, params: dict[str, float]) -> dict:
            audio = np.zeros((2, 16), dtype=np.float32)
            # First attempt of index 0 (seed 1) fails; any later attempt passes.
            if attempt_seed == 1:
                return {
                    "validation": _validation_bad(),
                    "qc": _qc_all_ok(audio, _SR),
                    "bus": audio,
                }
            return {
                "validation": _validation_ok(),
                "qc": _qc_all_ok(audio, _SR),
                "bus": audio,
            }

        report = run_creative_mode(
            1,
            creativity=0.5,
            variants_count=1,
            render=render,
            save=self._fake_save(calls),
        )
        entry = report["variants"][0]
        assert entry["status"] == "ok"
        assert entry["seed"] == 1 + 0 * 1000 + 1  # the second attempt
        assert calls == [(0, 2)]  # save receives the accepted attempt_seed

    def test_manual_marks_non_standard_and_never_rejects(self):
        """manual=True: failing checks still render, marked non_standard."""
        report = run_creative_mode(
            2,
            creativity=1.0,
            variants_count=2,
            render=self._fake_render(
                _validation_bad(), _qc_flagged(np.zeros((2, 4)), _SR)
            ),
            save=self._fake_save([]),
            manual=True,
        )
        assert report["rejected_count"] == 0
        assert all(entry["status"] == "ok" for entry in report["variants"])
        assert all(entry["non_standard"] is True for entry in report["variants"])
        assert all(entry["path"] is not None for entry in report["variants"])

    def test_attempts_are_capped_per_variant(self):
        """An always-failing variant exhausts max_attempts and is marked
        rejected — the loop never spins forever and the batch still
        yields exactly variants_count entries."""
        report = run_creative_mode(
            4,
            creativity=1.0,
            variants_count=3,
            render=self._fake_render(
                _validation_bad(), _qc_flagged(np.zeros((2, 4)), _SR)
            ),
            save=self._fake_save([]),
        )
        assert len(report["variants"]) == 3
        assert all(entry["status"] == "rejected" for entry in report["variants"])
        # The resampling stride is documented: seed + index*1000 + attempt.
        for i, entry in enumerate(report["variants"]):
            assert entry["seed"] == 4 + i * 1000 + (creative.MAX_CREATIVE_ATTEMPTS - 1)


class TestCreativeMix:
    """build_mix integration (fake split + optional QC stand-in)."""

    def test_no_creative_report_by_default(self, tmp_path, monkeypatch):
        """creative_variants=0 (default) → the exact previous routing: no
        creative_report key at all."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        result = mix_engine.build_mix(
            session_id, str(sessions_path(session_id)), with_versions=False
        )
        assert "creative_report" not in result

    def test_creative_report_present_with_variants(self, tmp_path, monkeypatch):
        """seed + variants → creative_report with N ok entries and WAVs."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "run_qc_checks", _qc_all_ok)
        session_id = _register_session(tmp_path)
        result = mix_engine.build_mix(
            session_id,
            str(sessions_path(session_id)),
            creative_seed=42,
            creativity=0.5,
            creative_variants=2,
            with_versions=False,
        )
        report = result["creative_report"]
        assert report["seed"] == 42
        assert report["creativity"] == 0.5
        assert report["status"] == "active"
        assert len(report["variants"]) == 2
        assert report["rejected_count"] == 0
        for i, entry in enumerate(report["variants"]):
            assert entry["status"] == "ok"
            assert entry["non_standard"] is False
            path = Path(entry["path"])
            assert path.name == f"{session_id}_mix_creative_{i}.wav"
            assert path.exists() and path.stat().st_size > 1000
            audio, sr = _read_wav(path)
            assert audio.shape[0] == 2 and sr == _SR

    def test_creativity_zero_keeps_principal_byte_identical(
        self, tmp_path, monkeypatch
    ):
        """creativity=0 with variants → the principal render is byte-
        identical to the plain run (strict standard = bit-identical)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "run_qc_checks", _qc_all_ok)
        session_id = _register_session(tmp_path)
        source = sessions_path(session_id)

        mix_engine.build_mix(session_id, str(source), with_versions=False)
        plain_bytes = (settings.output_dir / f"{session_id}_mix.wav").read_bytes()

        result = mix_engine.build_mix(
            session_id,
            str(source),
            creative_seed=7,
            creativity=0.0,
            creative_variants=2,
            with_versions=False,
        )
        creative_bytes = (settings.output_dir / f"{session_id}_mix.wav").read_bytes()
        assert creative_bytes == plain_bytes
        assert len(result["creative_report"]["variants"]) == 2

    def test_real_qc_passes_multi_sine_variants(self, tmp_path, monkeypatch):
        """Without a QC stand-in the REAL run_qc_checks runs on every
        variant bus. The multi-tone fixture sums to crest ≈ 8.2 dB —
        INSIDE the calibrated [6, 18] window — so all 3 variants are
        accepted, files land, and the principal path still delivered
        (the batch never blocks; the gate is the rejection sampler)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        source = sessions_path(session_id)

        result = mix_engine.build_mix(
            session_id,
            str(source),
            creative_seed=13,
            creativity=1.0,
            creative_variants=3,
            with_versions=False,
        )
        report = result["creative_report"]
        assert report["rejected_count"] == 0
        assert all(entry["status"] == "ok" for entry in report["variants"])
        assert all(entry["path"] is not None for entry in report["variants"])
        creative_files = sorted(
            settings.output_dir.glob(f"{session_id}_mix_creative_*.wav")
        )
        assert len(creative_files) == 3
        # The principal path still delivered.
        assert result["mix_path"].endswith(f"{session_id}_mix.wav")

    def test_creative_variants_differ_from_principal(self, tmp_path, monkeypatch):
        """creativity=1.0 shakes the routing: at least one variant WAV is
        not byte-identical to the principal (deterministic seed → stable)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        monkeypatch.setattr(mix_engine, "run_qc_checks", _qc_all_ok)
        session_id = _register_session(tmp_path)
        source = sessions_path(session_id)

        result = mix_engine.build_mix(
            session_id,
            str(source),
            creative_seed=99,
            creativity=1.0,
            creative_variants=2,
            with_versions=False,
        )
        principal = Path(result["mix_path"]).read_bytes()
        variant_paths = [
            Path(entry["path"]) for entry in result["creative_report"]["variants"]
        ]
        assert any(Path(p).read_bytes() != principal for p in variant_paths)

    def test_creative_requires_a_seed(self, tmp_path, monkeypatch):
        """variants without a seed is a contract violation (a seed is what
        makes the A/B reproducible)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        with pytest.raises(ValueError, match="seed"):
            mix_engine.build_mix(
                session_id,
                str(sessions_path(session_id)),
                creative_variants=2,
                with_versions=False,
            )

    def test_creative_creativity_range_validated(self, tmp_path, monkeypatch):
        """creativity lives in [0, 1] — a slider, not a gas pedal."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        with pytest.raises(ValueError, match="creativity"):
            mix_engine.build_mix(
                session_id,
                str(sessions_path(session_id)),
                creative_seed=1,
                creativity=1.5,
                creative_variants=1,
                with_versions=False,
            )


def sessions_path(session_id: str) -> Path:
    """The session's original audio (mirrors test_mix_engine helpers)."""
    from audiomind.api.upload import sessions

    return Path(sessions[session_id].original_path)


def _path_get(root: dict, path: tuple) -> float:
    """Resolve a param ``path`` against its stage root (test-side mirror
    of the apply walker — keeps the space wiring independently verifiable)."""
    node: dict | list = root
    for key in path:
        node = node[key]
    return float(node)