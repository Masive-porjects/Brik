"""Integration tests for the character stage inside the mix render (P3, T4/T5).

The feature rests on one structural claim: the character is applied to COPIES of
the processed stems and to the bus, so the alternative versions (which re-sum the
processed stems) and the creative variants (which re-render from the raw stems)
cannot see it. These tests assert that claim the only way that cannot be argued
with — by byte-comparing the files.

There is a second claim underneath it: the mix engine aliases
``processed_stems[name]`` and ``bus_audio[i]`` to the SAME array (``_apply_stem_trims``
mutates both), so a character stage that wrote in place would leak texture into the
versions through an alias nobody would think to look at. The byte comparisons are
what turn that from a design intention into a checked property.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.processing.mix_engine as mix_engine
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import ProcessingStatus, SessionData
from audiomind.processing.character import CHARACTER_DEFAULT_SEED
from audiomind.processing.quality_checks import MAX_QC_RELAX_DB

client = TestClient(app)

_SR = 44100
_STEM_SPECS = {
    "drums": (120.0, 0.75),
    "bass": (90.0, 1.0),
    "other": (330.0, 1.0),
    "vocals": (440.0, 1.25),
}
PROFILE = "commercial_alt_pop"
_VERSION_NAMES = {"principal", "vocal_up", "vocal_down", "instrumental", "tv_mix"}


def _write_tone(path: Path, hz: float, seconds: float) -> None:
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), _SR)


def _fake_split(input_path, output_dir=None, model="htdemucs"):
    """Demucs stand-in: four distinct synthetic stems, differing lengths."""
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


def _qc_all_ok(bus, sr, pan_info=None, budget=None):
    """QC stand-in for the creative batch: the synthetic bus is not mix material."""
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


def _register_session(tmp_path: Path) -> str:
    session_id = str(uuid.uuid4())
    original_path = tmp_path / "input.wav"
    _write_tone(original_path, hz=220.0, seconds=1.0)
    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original_path),
        original_filename=original_path.name,
    )
    return session_id


def _render(tmp_path, monkeypatch, **kwargs) -> tuple[dict, str]:
    """One full ``build_mix`` → ``(result, session_id)``."""
    monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
    session_id = _register_session(tmp_path)
    result = mix_engine.build_mix(
        session_id,
        str(sessions[session_id].original_path),
        profiles={},
        pan_profiles={},
        dimension_profiles={},
        compressor_profiles={},
        emphasis_profiles={},
        genre="alternative",
        genre_confidence=0.9,
        **kwargs,
    )
    return result, session_id


def _wav_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()


class TestNeutrality:
    """``character=None`` is the previous render, not a differently-shaped one."""

    def test_no_character_means_no_character_report(self, tmp_path, monkeypatch):
        result, _ = _render(tmp_path, monkeypatch)
        assert "character_report" not in result

    def test_the_character_actually_changes_the_principal(self, tmp_path, monkeypatch):
        plain, plain_id = _render(tmp_path, monkeypatch)
        shaped, shaped_id = _render(tmp_path, monkeypatch, character=PROFILE)
        assert shaped["character_report"]["status"] == "active"
        assert _wav_bytes(settings.output_dir / f"{plain_id}_mix.wav") != _wav_bytes(
            settings.output_dir / f"{shaped_id}_mix.wav"
        )

    def test_an_unknown_profile_is_a_loud_error(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="unknown character profile"):
            _render(tmp_path, monkeypatch, character="trap")


class TestThePrincipalSurvivesTheAlternatives:
    """Requirement 1: the texture lands on the PRINCIPAL render only."""

    def test_every_alternative_version_is_byte_identical(self, tmp_path, monkeypatch):
        plain, _ = _render(tmp_path, monkeypatch, with_versions=True)
        shaped, _ = _render(
            tmp_path, monkeypatch, with_versions=True, character=PROFILE
        )
        plain_versions = plain["versions"]
        shaped_versions = shaped["versions"]
        assert set(plain_versions) == _VERSION_NAMES
        assert set(shaped_versions) == _VERSION_NAMES

        for name in sorted(shaped_versions):
            if name == "principal":
                continue
            assert _wav_bytes(plain_versions[name]["path"]) == _wav_bytes(
                shaped_versions[name]["path"]
            ), f"version {name} was touched by the character stage"

        # ...and the principal DID change, so the identity above is not vacuous.
        assert _wav_bytes(plain_versions["principal"]["path"]) != _wav_bytes(
            shaped_versions["principal"]["path"]
        )

    def test_creative_variants_do_not_see_the_character(self, tmp_path, monkeypatch):
        # The variants re-render from the RAW stems, which the character never
        # touches: a zero-creativity variant must come out bit-identical.
        monkeypatch.setattr(mix_engine, "run_qc_checks", _qc_all_ok)
        plain, _ = _render(
            tmp_path,
            monkeypatch,
            creative_variants=1,
            creative_seed=7,
            creativity=0.0,
        )
        shaped, _ = _render(
            tmp_path,
            monkeypatch,
            creative_variants=1,
            creative_seed=7,
            creativity=0.0,
            character=PROFILE,
        )
        plain_entry = plain["creative_report"]["variants"][0]
        shaped_entry = shaped["creative_report"]["variants"][0]
        assert plain_entry["status"] == "ok"
        assert shaped_entry["status"] == "ok"
        assert _wav_bytes(plain_entry["path"]) == _wav_bytes(shaped_entry["path"])


class TestCharacterReport:
    """The report is the only channel through which the stage speaks."""

    def test_names_every_stage_and_the_bed_gate(self, tmp_path, monkeypatch):
        result, _ = _render(tmp_path, monkeypatch, character=PROFILE)
        report = result["character_report"]
        assert report["profile"] == PROFILE
        assert report["seed"] == CHARACTER_DEFAULT_SEED
        assert set(report["stems"]) == {"drums", "bass", "other", "vocals"}
        assert report["stems"]["vocals"]["stages"] == ["slapback"]
        assert report["stems"]["other"]["stages"] == ["wow_flutter", "chorus"]
        assert report["stems"]["bass"]["stages"] == ["saturation"]
        assert report["stems"]["drums"]["status"] == "untreated"
        assert report["negative_space"]["status"] == "measured"
        assert report["bed"]["status"] in {"active", "skipped"}
        if report["bed"]["status"] == "skipped":
            assert report["bed"]["reason"] == "no_negative_space"

    def test_the_same_seed_reproduces_the_render_byte_for_byte(
        self, tmp_path, monkeypatch
    ):
        first, first_id = _render(
            tmp_path, monkeypatch, character=PROFILE, character_seed=99
        )
        second, second_id = _render(
            tmp_path, monkeypatch, character=PROFILE, character_seed=99
        )
        assert first["character_report"]["seed"] == 99
        assert second["character_report"]["seed"] == 99
        assert _wav_bytes(settings.output_dir / f"{first_id}_mix.wav") == _wav_bytes(
            settings.output_dir / f"{second_id}_mix.wav"
        )


class TestQCBudget:
    """Requirement 5: the declared budget reaches the principal QC call."""

    def test_the_principal_qc_declares_the_profiles_deviations(
        self, tmp_path, monkeypatch
    ):
        result, _ = _render(tmp_path, monkeypatch, character=PROFILE)
        summary = result["qc_report"]["summary"]
        budget = result["character_report"]["qc_budget"]
        assert summary["allowed_intentional"] == budget["allowed_intentional"]
        assert budget["allowed_intentional"]  # non-empty provenance

    def test_the_crest_floor_is_the_measured_one(self, tmp_path, monkeypatch):
        result, _ = _render(tmp_path, monkeypatch, character=PROFILE)
        report = result["character_report"]
        details = result["qc_report"]["low_level_listen"]["details"]
        needed = float(report["crest_relax_needed_db"])
        if needed <= 0.0:
            assert "budget_relax_db" not in details
            return
        assert details["crest_floor_standard_db"] == 6.0
        assert details["budget_relax_db"] == pytest.approx(min(needed, MAX_QC_RELAX_DB))
        # The window is reported as a pair, so a reader can see the floor moved.
        assert details["crest_ok_range_db"][0] == pytest.approx(
            details["crest_floor_standard_db"] - details["budget_relax_db"]
        )

    def test_without_the_character_the_qc_stays_strict(self, tmp_path, monkeypatch):
        result, _ = _render(tmp_path, monkeypatch)
        summary = result["qc_report"]["summary"]
        assert "intentional_deviations" not in summary
        assert "allowed_intentional" not in summary


class TestBedAuthorization:
    """The bed's gate is a measurement, and a failed one is never a yes."""

    def test_a_real_measurement_reports_itself(self, tmp_path):
        quiet = tmp_path / "quiet.wav"
        _write_tone(quiet, hz=220.0, seconds=1.0)
        authorized, report = mix_engine._bed_authorization(quiet)
        assert report["status"] == "measured"
        assert authorized is report["bed_authorized"]
        assert 0.0 <= float(report["negative_space_ratio"]) <= 1.0

    def test_a_failed_measurement_skips_the_bed_and_says_so(self, tmp_path):
        authorized, report = mix_engine._bed_authorization(
            tmp_path / "does-not-exist.wav"
        )
        assert authorized is False
        assert report["status"] == "unavailable"
        assert report["reason"] == "inspection_failed"


class TestMixEndpointOptIn:
    def test_known_profile_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(
            f"/api/session/{session_id}/mix", json={"character": PROFILE}
        )
        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert payload["character_report"]["profile"] == PROFILE

    def test_unknown_profile_answers_422(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(f"/api/session/{session_id}/mix", json={"character": "trap"})
        assert resp.status_code == 422
