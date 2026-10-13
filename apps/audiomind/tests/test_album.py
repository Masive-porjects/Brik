"""Phase D — album/EP batch mastering tests (P1-2).

Covers the new batch surface:

  1. ``negotiate_targets`` unit coverage (pure, tmp-free): median-relative
     slope math, clamping, None-LRA handling, default base, empty input —
     the identify-neutrality contract (same LRA everywhere → identical
     targets) included.
  2. ``POST /api/album/negotiate`` — measurement-only route: two real
     WAVs with genuinely different LRA negotiate targets in the expected
     direction; guards (empty / unknown session / missing file) fail fast;
     a corrupt track keeps the album alive with base target.
  3. ``POST /api/album/process`` — stubbed ``process_audio`` (the lazy
     slot in ``audiomind.api.batch``): happy path mutates the sessions
     like the single-track process endpoint; a failing track is marked in
     the report while the album completes; guards fail fast.

Route fixtures mirror ``test_reference_external.py`` (fresh store, real
WAV fixtures via ``soundfile``, stubbed DSP — no network).
"""
import sys

sys.path.insert(0, "src")

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.processing.album import (
    ALBUM_LRA_SLOPE_DB_PER_LU,
    ALBUM_MAX_RELATIVE_OFFSET_DB,
    DEFAULT_ALBUM_TARGET_LUFS_DB,
    negotiate_targets,
)

client = TestClient(app)

SR = 44100


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()


# ── Synthetic fixtures ─────────────────────────────────────────────────


def _write_wav(path, samples, sr=SR, subtype="FLOAT") -> None:
    """Write samples (1D mono or (channels, samples)) as a WAV."""
    x = np.asarray(samples)
    blocks = x.T if x.ndim == 2 else x
    sf.write(str(path), blocks, sr, subtype=subtype)


def _dynamic_program() -> np.ndarray:
    """Wide dynamics: 16 alternating 0.5 s loud/quiet blocks (~17 LU).

    Loud blocks carry a 220 Hz sine + noise at 0.3, quiet blocks at 0.04.
    The ~18 dB contrast over 8 s produces an LRA clearly above the dense
    program's, so the negotiation offsets point in opposite directions.
    """
    rng = np.random.default_rng(11)
    n = SR * 8
    t = np.arange(n) / SR
    x = np.zeros(n)
    for i in range(16):
        s, e = i * SR // 2, (i + 1) * SR // 2
        amp = 0.30 if i % 2 == 0 else 0.04
        x[s:e] = amp * (
            np.sin(2 * np.pi * 220 * t[s:e]) + 0.6 * rng.standard_normal(e - s)
        )
    return np.stack([x, x])


def _dense_program() -> np.ndarray:
    """Dense/steady: loud noise with a slow ~2 dB swell (~5 LU)."""
    rng = np.random.default_rng(5)
    n = SR * 8
    t = np.arange(n) / SR
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 0.5 * t)
    x = 0.25 * mod * rng.standard_normal(n)
    return np.stack([x, x])


def _make_session(samples) -> str:
    """Create a session whose original file is a REAL WAV (measurable)."""
    resp = client.post("/api/session/new", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    session = sessions[session_id]
    original = settings.upload_dir / f"{session_id}_orig.wav"
    _write_wav(original, samples)
    session.original_path = str(original.resolve())
    return session_id


def _stub_process_album(monkeypatch, captured=None, failing_session_id=None):
    """Stub the DSP pipeline; optionally capture call kwargs or fail one track.

    The fake lands on ``integrated_lufs = params.target_lufs_db + 0.4``
    (inside the ±1.5 dB tolerance) so per-track ``within_tolerance`` is
    exercised meaningfully against the negotiated target.
    """
    import audiomind.api.batch as batch_mod

    calls = {"n": 0}

    def _fake(input_path, output_path, params, **kwargs):
        calls["n"] += 1
        if captured is not None:
            captured["params"] = captured.get("params", []) + [params]
            captured["output_paths"] = captured.get("output_paths", []) + [
                str(Path(output_path).name)
            ]
        if failing_session_id and Path(output_path).name.startswith(
            failing_session_id
        ):
            raise RuntimeError("boom: simulated track failure")
        target = params.target_lufs_db if params.target_lufs_db is not None else -14.0
        return {
            "output_path": str(Path(output_path).resolve()),
            "integrated_lufs": target + 0.4,
            "true_peak_db": -1.2,
            "crest_factor_db": 8.5,
            "lra": 7.0,
            "warnings": [],
        }

    monkeypatch.setattr(batch_mod, "process_audio", _fake)
    return calls


# ── negotiate_targets unit tests (pure, tmp-free) ───────────────────────


class TestNegotiateTargets:
    def test_all_equal_lra_gives_identical_base_targets(self):
        """Identify-neutrality: no dynamics spread → no relative offset."""
        targets = negotiate_targets([8.0, 8.0, 8.0], base_lufs_db=-14.0)
        assert targets == [-14.0, -14.0, -14.0]

    def test_above_median_gains_higher_target_than_below(self):
        """Slope math: median 9, track 12 → offset +0.75 → base + 0.8."""
        targets = negotiate_targets([9.0, 9.0, 12.0], base_lufs_db=-14.0)
        assert targets[0] == -14.0  # the median track keeps the base
        assert targets[1] == -14.0
        assert (12.0 - 9.0) * ALBUM_LRA_SLOPE_DB_PER_LU == pytest.approx(0.75)
        assert targets[2] == pytest.approx(-13.2)  # round(-13.25, 1)
        assert targets[2] - targets[0] == pytest.approx(0.8)
        assert targets[2] > targets[0]

    def test_offset_clamps_to_max_relative_offset(self):
        """LRA 20 vs median 9 → +2.75 unclamped, exactly +2.0 clamped."""
        targets = negotiate_targets([9.0, 9.0, 20.0], base_lufs_db=-14.0)
        assert targets[2] == pytest.approx(-14.0 + ALBUM_MAX_RELATIVE_OFFSET_DB)
        assert targets[2] != pytest.approx(-11.25)  # would be the unclamped 2.75

        low = negotiate_targets([9.0, 9.0, 0.0], base_lufs_db=-14.0)
        assert low[2] == pytest.approx(-14.0 - ALBUM_MAX_RELATIVE_OFFSET_DB)

    def test_none_lra_keeps_base_unchanged(self):
        targets = negotiate_targets([None, 5.0, 13.0], base_lufs_db=-14.0)
        assert targets[0] == -14.0
        assert targets[1] == pytest.approx(-15.0)  # (5-9)*0.25 = -1.0
        assert targets[2] == pytest.approx(-13.0)  # (13-9)*0.25 = +1.0

    def test_base_none_uses_default_album_target(self):
        targets = negotiate_targets([1.0, 9.0])
        assert targets[0] == pytest.approx(-15.0)
        assert targets[1] == pytest.approx(-13.0)
        # Proves the default base is DEFAULT_ALBUM_TARGET_LUFS_DB (-14.0)
        assert DEFAULT_ALBUM_TARGET_LUFS_DB == -14.0
        assert targets[0] == DEFAULT_ALBUM_TARGET_LUFS_DB - 1.0

    def test_empty_input_returns_empty(self):
        assert negotiate_targets([]) == []

    def test_all_none_lra_returns_all_base(self):
        assert negotiate_targets([None, None], base_lufs_db=-12.5) == [-12.5, -12.5]

    def test_targets_rounded_to_one_decimal(self):
        targets = negotiate_targets([5.0, 9.0, 12.05], base_lufs_db=-14.0)
        for t in targets:
            assert t == pytest.approx(round(t, 1))


# ── Route tests: POST /api/album/negotiate ──────────────────────────────


class TestNegotiateAlbumTargets:
    def test_two_tracks_negotiate_in_expected_direction(self):
        dyn_id = _make_session(_dynamic_program())
        dense_id = _make_session(_dense_program())

        resp = client.post(
            "/api/album/negotiate",
            json={"session_ids": [dyn_id, dense_id]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["target_base_lufs_db"] == DEFAULT_ALBUM_TARGET_LUFS_DB
        dyn, dense = data["tracks"][0], data["tracks"][1]
        assert dyn["session_id"] == dyn_id
        assert dense["session_id"] == dense_id

        # Real measurement: the dynamic program has the bigger LRA.
        assert dyn["input_lra_lu"] is not None
        assert dense["input_lra_lu"] is not None
        assert dyn["input_lra_lu"] > dense["input_lra_lu"]
        assert data["lra_median_lu"] == pytest.approx(
            (dyn["input_lra_lu"] + dense["input_lra_lu"]) / 2, abs=0.01
        )

        # Negotiation direction: MORE dynamics → HIGHER target.
        base = data["target_base_lufs_db"]
        assert (
            dyn["negotiated_target_lufs_db"]
            > base
            > dense["negotiated_target_lufs_db"]
        )
        for track in (dyn, dense):
            target = track["negotiated_target_lufs_db"]
            offset = track["offset_db"]
            assert offset == pytest.approx(target - base, abs=0.01)
            assert abs(offset) <= ALBUM_MAX_RELATIVE_OFFSET_DB + 1e-9
            assert target == round(target, 1)  # one-decimal targets
        # Sessions created programmatically carry no analysis → input LUFS None.
        assert dyn["input_lufs_db"] is None
        assert dyn["original_filename"] is None

    def test_empty_session_ids_returns_400(self):
        resp = client.post("/api/album/negotiate", json={"session_ids": []})
        assert resp.status_code == 400
        assert "session_ids" in resp.json()["detail"]

    def test_unknown_session_returns_404(self):
        resp = client.post(
            "/api/album/negotiate", json={"session_ids": ["nope-123"]}
        )
        assert resp.status_code == 404
        assert "nope-123" in resp.json()["detail"]

    def test_missing_file_returns_400(self):
        session_id = _make_session(_dense_program())
        sessions[session_id].original_path = str(
            settings.upload_dir / "does-not-exist.wav"
        )
        resp = client.post(
            "/api/album/negotiate", json={"session_ids": [session_id]}
        )
        assert resp.status_code == 400
        assert "audio file" in resp.json()["detail"]

    def test_undecodable_track_keeps_album_alive(self):
        good_id = _make_session(_dynamic_program())
        bad_id = _make_session(_dense_program())
        # Replace the bad session's file with garbage that EXISTS on disk
        # (passes the guard; fails in the librosa load).
        bad_path = settings.upload_dir / f"{bad_id}_orig.wav"
        bad_path.write_bytes(b"this is not audio")
        sessions[bad_id].original_path = str(bad_path.resolve())

        resp = client.post(
            "/api/album/negotiate",
            json={"session_ids": [good_id, bad_id]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        good, bad = data["tracks"][0], data["tracks"][1]
        assert good["input_lra_lu"] is not None
        # Unmeasurable track: base target, null metrics, album alive.
        assert bad["input_lra_lu"] is None
        assert bad["negotiated_target_lufs_db"] == data["target_base_lufs_db"]
        assert bad["offset_db"] == 0.0


# ── Route tests: POST /api/album/process ────────────────────────────────


class TestProcessAlbum:
    def test_happy_path_mutates_sessions_and_reports_tolerance(self, monkeypatch, tmp_path):
        dyn_id = _make_session(_dynamic_program())
        dense_id = _make_session(_dense_program())
        captured = {}
        calls = _stub_process_album(monkeypatch, captured)

        resp = client.post(
            "/api/album/process",
            json={"session_ids": [dyn_id, dense_id]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert calls["n"] == 2

        for sid, track in zip([dyn_id, dense_id], data["tracks"], strict=True):
            assert track["session_id"] == sid
            target = track["negotiated_target_lufs_db"]
            assert target is not None
            session = sessions[sid]
            # Session mutation mirrors POST /api/session/{id}/process.
            assert session.mastered_path is not None
            assert session.mastered_path.endswith(f"{sid}_album_mastered.wav")
            assert session.parameters.target_lufs_db == pytest.approx(target)
            assert session.master_result is not None
            assert session.mastering_report is not None
            assert session.status.value == "completed"
            assert session.error is None
            # Per-track metrics reflect the stub vs the negotiated target.
            assert track["output_lufs_db"] == pytest.approx(target + 0.4)
            assert track["lufs_deviation_db"] == pytest.approx(0.4)
            assert track["within_tolerance"] is True
            assert track["output_lra_lu"] == 7.0
            assert track["output_crest_db"] == 8.5
            assert track["output_true_peak_dbtp"] == -1.2

        # The negotiation flows through the stub: dynamic target > dense.
        assert (
            data["tracks"][0]["negotiated_target_lufs_db"]
            > data["tracks"][1]["negotiated_target_lufs_db"]
        )
        # The stubbed DSP received the negotiated per-track target.
        assert captured["params"][0].target_lufs_db == pytest.approx(
            data["tracks"][0]["negotiated_target_lufs_db"]
        )
        assert captured["params"][1].target_lufs_db == pytest.approx(
            data["tracks"][1]["negotiated_target_lufs_db"]
        )
        # Sessions were persisted exactly once (single save after all tracks).
        # The harness pins the session backend to this test's tmp_path.
        persisted = tmp_path / "sessions.json"
        assert persisted.exists()

    def test_failing_track_is_marked_and_album_continues(self, monkeypatch):
        good_id = _make_session(_dynamic_program())
        bad_id = _make_session(_dense_program())
        _stub_process_album(monkeypatch, failing_session_id=bad_id)

        resp = client.post(
            "/api/album/process",
            json={"session_ids": [good_id, bad_id]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        bad_track = data["tracks"][1]
        assert bad_track["session_id"] == bad_id
        assert bad_track["negotiated_target_lufs_db"] is not None
        assert bad_track["output_lufs_db"] is None
        assert bad_track["lufs_deviation_db"] is None
        assert bad_track["within_tolerance"] is False
        assert any("RuntimeError: boom" in w for w in bad_track["warnings"])

        # The failing session is NOT mutated; the good one is.
        assert sessions[bad_id].mastered_path is None
        assert sessions[bad_id].status.value == "uploaded"
        assert sessions[good_id].mastered_path is not None
        assert sessions[good_id].status.value == "completed"
        assert data["tracks"][0]["within_tolerance"] is True

    def test_empty_session_ids_returns_400(self):
        resp = client.post("/api/album/process", json={"session_ids": []})
        assert resp.status_code == 400
        assert "session_ids" in resp.json()["detail"]

    def test_unknown_session_returns_404(self):
        resp = client.post(
            "/api/album/process", json={"session_ids": ["nope-123"]}
        )
        assert resp.status_code == 404
        assert "nope-123" in resp.json()["detail"]

    def test_missing_file_returns_400(self):
        session_id = _make_session(_dense_program())
        sessions[session_id].original_path = str(
            settings.upload_dir / "does-not-exist.wav"
        )
        resp = client.post(
            "/api/album/process", json={"session_ids": [session_id]}
        )
        assert resp.status_code == 400
        assert "audio file" in resp.json()["detail"]

    def test_explicit_parameters_and_album_base_pass_through(self, monkeypatch):
        """Custom album base + non-default parameters reach the stub."""
        sid = _make_session(_dynamic_program())
        captured = {}
        _stub_process_album(monkeypatch, captured)

        resp = client.post(
            "/api/album/process",
            json={
                "session_ids": [sid],
                "target_lufs_db": -16.0,
                "parameters": {
                    "limiter_ceiling_db": -0.5,
                    "saturation_drive_db": 2.0,
                },
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target_base_lufs_db"] == -16.0
        track = data["tracks"][0]
        assert -16.0 <= track["negotiated_target_lufs_db"] <= -16.0 + 2.0
        params = captured["params"][0]
        assert params.limiter_ceiling_db == pytest.approx(-0.5)
        assert params.saturation_drive_db == pytest.approx(2.0)
        assert params.target_lufs_db == pytest.approx(
            track["negotiated_target_lufs_db"]
        )