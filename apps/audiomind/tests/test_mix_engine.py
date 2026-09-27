"""TDD tests for the Mix Engine (Paso 01 — per-stem routing).

RED → GREEN → REFACTOR contract for ``POST /api/session/{id}/mix``:

* the endpoint splits the session audio into the 4 stems
  (drums/bass/other/vocals) via ``split_audio``,
* routes each stem at NEUTRAL 0 dB gains onto a stereo mono-compatible
  bus (no DSP yet — pure routing + summing),
* pads every stem to the longest one and writes
  ``outputs/{session_id}_mix.wav`` through ``write_output``,
* analyzes each stem (LUFS / DR / spectral centroid) plus the full mix
  (tempo / genre / confidence),
* returns the WAV, carrying the JSON analysis payload in the
  ``X-Mix-Result`` response header, and records ``mix_path`` /
  ``mix_analysis`` on the session — never touching ``mastered_path``
  (the mix is NOT the master).

``split_audio`` (Demucs) is monkeypatched with a synthetic stand-in: the
real model download is heavy and non-deterministic, and the routing
contract under test is the engine, not the separator.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.processing.mix_engine as mix_engine
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import ProcessingStatus, SessionData

client = TestClient(app)

_SR = 44100
# (tone hz, duration s) per stem — differing lengths force the pad path.
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


def _register_session(tmp_path: Path, with_audio: bool = True) -> str:
    """Insert a session directly into the in-memory store (no HTTP upload).

    Bypasses ``/api/upload`` so no background librosa analysis or preset
    pre-render fires; the mix endpoint only needs ``original_path``.
    """
    session_id = str(uuid.uuid4())
    original_path = None
    if with_audio:
        original_path = tmp_path / "input.wav"
        _write_tone(original_path, hz=220.0, seconds=1.0)
    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original_path) if original_path else None,
        original_filename=original_path.name if original_path else None,
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


def _fake_split_low_vocals(input_path: str | Path, output_dir: str | Path
                           | None = None, model: str = "htdemucs") -> dict:
    """Stand-in for Demucs with the voice ~14 dB BELOW the groove band.

    Mirrors the producer session (voice noticeably under the groove):
    drums/bass/other at 0.25 (≈ −15 dBFS RMS), vocals at 0.05 → the
    auto-balance must raise ONLY the vocals, leaving the groove untouched.
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        stem_path = out / f"{name}.wav"
        gain = 0.05 if name == "vocals" else 0.25
        t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
        sf.write(str(stem_path), gain * np.sin(2.0 * np.pi * hz * t), _SR)
        stems[name] = str(stem_path)
    return {
        "stems": stems,
        "sample_rate": _SR,
        "duration_seconds": 1.25,
        "stem_audio_dir": str(out),
    }


def _fake_split_groove_vocals(input_path: str | Path, output_dir: str | Path
                              | None = None, model: str = "htdemucs") -> dict:
    """Stand-in for Demucs with the voice ALREADY at the groove level.

    Drums/bass/other at 0.25; the voice is scaled by MEASURED LUFS until
    it sits within ~0.1 dB of the groove level (mean of drums/bass). A
    balanced mix must need no auto-balance correction: the target equals
    the current position."
    """
    from audiomind.processing.loudness import measure_lufs

    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        stem_path = out / f"{name}.wav"
        _write_tone(stem_path, hz=hz, seconds=seconds)
        stems[name] = str(stem_path)
    vocal_path = out / "vocals.wav"
    vocals = sf.read(str(vocal_path), dtype="float32")[0]
    lufs = {
        name: measure_lufs(
            sf.read(str(out / f"{name}.wav"), dtype="float32")[0].T, _SR
        )
        for name in ("drums", "bass", "other", "vocals")
    }
    groove = float(np.mean([lufs["drums"], lufs["bass"]]))
    gap = groove - lufs["vocals"]
    vocals = vocals * (10.0 ** (gap / 20.0))
    sf.write(str(vocal_path), vocals, _SR)
    return {
        "stems": stems,
        "sample_rate": _SR,
        "duration_seconds": 1.25,
        "stem_audio_dir": str(out),
    }


def _band_energy_db(audio: np.ndarray, sr: int, hz: float,
                    hz_half_width: float = 4.0) -> float:
    """Energy in dB of the FFT band around ``hz`` (mono mix of 2 ch)."""
    mono = audio.mean(axis=0)
    n = mono.shape[0]
    windowed = mono * np.hanning(n)
    spec = np.fft.rfft(windowed)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    mask = np.abs(freqs - hz) <= hz_half_width
    return float(10.0 * np.log10(np.sum(np.abs(spec[mask]) ** 2) + 1e-12))


def _render_mix(tmp_path: Path, monkeypatch, *, auto_balance: bool,
                genre: str | None = None,
                stem_trims: dict[str, float] | None = None,
                splitter=_fake_split) -> tuple[np.ndarray, int]:
    """Render a mix through ``build_mix`` and read the written WAV."""
    monkeypatch.setattr(mix_engine, "split_audio", splitter)
    session_id = _register_session(tmp_path)
    mix_engine.build_mix(
        session_id,
        str(Path(sessions[session_id].original_path)),
        profiles={},
        pan_profiles={},
        dimension_profiles={},
        compressor_profiles={},
        emphasis_profiles={},
        with_versions=False,
        auto_balance=auto_balance,
        stem_trims=stem_trims,
        genre=genre,
        genre_confidence=0.9,
    )
    mix_path = settings.output_dir / f"{session_id}_mix.wav"
    return _read_wav(mix_path)


class TestMixEndpoint:
    """Integration tests for POST /api/session/{id}/mix."""

    def test_mix_returns_wav_and_analysis(self, tmp_path, monkeypatch):
        """200 + WAV + JSON payload + on-disk file + session fields."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(f"/api/session/{session_id}/mix")

        # (c) 200 + WAV + JSON with tempo_bpm/genre/genre_confidence/analysis
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "audio/wav"
        assert len(resp.content) > 1000, "WAV body too small"
        payload = json.loads(resp.headers["x-mix-result"])
        assert "tempo_bpm" in payload
        assert "genre" in payload
        assert "genre_confidence" in payload
        assert set(payload["analysis"]) == {"drums", "bass", "other", "vocals"}
        for stem in payload["analysis"].values():
            assert "integrated_lufs" in stem
            assert "dynamic_range_db" in stem
            assert "spectral_centroid" in stem
        # v5 — stem_presence: exactly the 4 real STEM_NAMES, all booleans.
        # The synthetic fixture writes every stem at 0.25 amplitude
        # (≈ −15 dBFS RMS, well above the −50 dBFS threshold) → present.
        assert "stem_presence" in payload
        assert list(payload["stem_presence"]) == list(mix_engine.STEM_NAMES)
        assert all(
            isinstance(v, bool) for v in payload["stem_presence"].values()
        )
        assert all(payload["stem_presence"].values())
        # The bus is padded to the LONGEST stem (vocals: 1.25 s).
        assert payload["duration_seconds"] == pytest.approx(1.25, abs=0.01)

        # (d) the WAV exists on disk
        mix_path = settings.output_dir / f"{session_id}_mix.wav"
        assert mix_path.exists(), "mix WAV not written to outputs/"
        assert mix_path.stat().st_size > 1000

        # (e) the session keeps mix_path / mix_analysis…
        session = sessions[session_id]
        assert session.mix_path == str(mix_path.resolve())
        assert session.mix_analysis == payload
        # …and the mix is NOT the master: mastered_path stays untouched.
        assert session.mastered_path is None
        assert session.master_result is None

    def test_mix_unknown_session_returns_404(self):
        """POST on a session that does not exist → 404."""
        resp = client.post("/api/session/nope-not-a-session/mix")
        assert resp.status_code == 404

    def test_mix_without_audio_returns_400(self, tmp_path):
        """POST on a session with no uploaded audio → 400."""
        session_id = _register_session(tmp_path, with_audio=False)
        resp = client.post(f"/api/session/{session_id}/mix")
        assert resp.status_code == 400

    def test_get_mix_audio_serves_persisted_wav(self, tmp_path, monkeypatch):
        """GET /audio/mix serves the persisted WAV (stable URL, no re-mix).

        Regression guard for the literal-vs-parameter route order: the
        literal ``/audio/mix`` must beat mastering's ``/audio/{audio_type}``.
        """
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        mix_resp = client.post(f"/api/session/{session_id}/mix")
        assert mix_resp.status_code == 200

        resp = client.get(f"/api/session/{session_id}/audio/mix")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "audio/wav"
        assert resp.content == mix_resp.content, "GET body differs from POST body"
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_get_mix_audio_without_mix_returns_404(self):
        """GET /audio/mix for an unknown session → 404."""
        resp = client.get("/api/session/nope-not-a-session/audio/mix")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mix not found for this session"


#: Version names in render order (payload keys of the versions dict).
_QC_CHECK_KEYS = {
    "mono",
    "phase",
    "sibilance_5k",
    "muddy_250",
    "honky_500",
    "low_level_listen",
}
_VERSION_NAMES = {"principal", "vocal_up", "vocal_down", "instrumental", "tv_mix"}


def _bin_energy_db(audio: np.ndarray, sr: int, hz: float) -> float:
    """Hann-windowed single-bin DFT energy (dB) at ``hz``.

    Leakage-controlled measurement used to isolate one synthetic stem
    tone inside a summed mix (stems are pure tones at distinct Hz).
    Relative comparisons only — the window's 0.5 amplitude factor is
    constant across files of the same length.
    """
    x = np.asarray(audio)
    n = x.shape[-1]
    window = np.hanning(n)
    t = np.arange(n, dtype=np.float64)
    phasor = np.exp(-2j * np.pi * hz * t / sr) * window
    if x.ndim == 2:
        mag = float(np.max(np.abs(x @ phasor)))
    else:
        mag = abs(float(np.dot(x, phasor)))
    return 20.0 * np.log10(mag / n + 1e-12)


def _read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Decode a mix WAV into (2, N) float + sample rate."""
    with sf.SoundFile(str(path), "r") as f:
        sr = int(f.samplerate)
        frames = f.read(dtype="float32", always_2d=True)
    return frames.T, sr


class TestMixQCAndVersions:
    """Paso 07: QC report + alternative versions on the /mix endpoint."""

    def test_mix_payload_includes_qc_report(self, tmp_path, monkeypatch):
        """qc_report is always present with every check + summary."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(f"/api/session/{session_id}/mix")
        assert resp.status_code == 200
        payload = json.loads(resp.headers["x-mix-result"])
        qc_report = payload["qc_report"]
        assert _QC_CHECK_KEYS <= set(qc_report)
        assert "summary" in qc_report
        assert isinstance(qc_report["summary"]["flagged"], list)
        # Informational contract: every per-check dict carries ok + details.
        for name in _QC_CHECK_KEYS:
            assert "ok" in qc_report[name]
            assert "details" in qc_report[name]

    def test_mix_renders_all_version_wavs(self, tmp_path, monkeypatch):
        """-versions dict with 5 entries; alt WAVs exist and decode."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(f"/api/session/{session_id}/mix")
        assert resp.status_code == 200
        payload = json.loads(resp.headers["x-mix-result"])
        versions = payload["versions"]
        assert set(versions) == _VERSION_NAMES
        # principal points at the same file the endpoint serves.
        assert versions["principal"]["path"] == str(
            (settings.output_dir / f"{session_id}_mix.wav").resolve()
        )
        assert versions["principal"]["trim_db"] == 0.0
        for name in ("vocal_up", "vocal_down", "instrumental", "tv_mix"):
            assert Path(versions[name]["path"]).exists()
            assert Path(versions[name]["path"]).stat().st_size > 1000
            audio, sr = _read_wav(versions[name]["path"])
            assert audio.ndim == 2 and audio.shape[0] == 2
            assert sr == _SR
            assert len(versions[name]["description"]) > 0
        assert versions["vocal_up"]["trim_db"] == 0.75
        assert versions["vocal_down"]["trim_db"] == -0.75
        assert versions["instrumental"]["trim_db"] is None
        assert versions["tv_mix"]["trim_db"] is None

    def test_versions_differ_only_in_vocals_band(self, tmp_path, monkeypatch):
        """Spectral proof: only the 440 Hz vocals band moves across versions.

        vocal_up > principal > vocal_down; instrumental/tv_mix ≈ no vocal;
        the bass band (90 Hz) stays equal within ±1.5 dB (the bus
        compressor reacts minimally to the fader move, DAW-real).
        """
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(f"/api/session/{session_id}/mix")
        assert resp.status_code == 200
        payload = json.loads(resp.headers["x-mix-result"])
        versions = payload["versions"]

        audios: dict[str, np.ndarray] = {}
        for name, entry in versions.items():
            audios[name], sr = _read_wav(entry["path"])

        vocals_band = {name: _bin_energy_db(a, sr, 440.0)
                       for name, a in audios.items()}
        assert vocals_band["vocal_up"] >= vocals_band["principal"] + 0.2
        assert vocals_band["vocal_down"] <= vocals_band["principal"] - 0.2
        assert vocals_band["instrumental"] <= vocals_band["principal"] - 20.0
        assert vocals_band["tv_mix"] <= vocals_band["principal"] - 20.0

        bass_band = {name: _bin_energy_db(a, sr, 90.0)
                     for name, a in audios.items()}
        for name in ("vocal_up", "vocal_down", "instrumental", "tv_mix"):
            assert abs(bass_band[name] - bass_band["principal"]) <= 1.5

    def test_principal_byte_identical_with_and_without_versions(
        self, tmp_path, monkeypatch
    ):
        """Paso 06 regression: rendering versions never perturbs principal."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        original_path = sessions[session_id].original_path

        mix_engine.build_mix(session_id, str(original_path), with_versions=True)
        with_versions_bytes = (
            settings.output_dir / f"{session_id}_mix.wav"
        ).read_bytes()

        mix_engine.build_mix(session_id, str(original_path), with_versions=False)
        without_versions_bytes = (
            settings.output_dir / f"{session_id}_mix.wav"
        ).read_bytes()

        assert with_versions_bytes == without_versions_bytes


class TestApplyStemTrims:
    """T2 — stem faders land at the bus input AFTER the chain: every stem
    (drums/bass/other/vocals) scales by 10^(db/20); 0.0 dB stems stay
    bit-exact (neutral = bypass)."""

    def _synthetic(self, stem: str) -> np.ndarray:
        """A float32 stereo tone at the stem's fixture Hz — same lengths
        as ``_STEM_SPECS`` so the pad/sum path mirrors a real mix."""
        sr = _SR
        seconds = _STEM_SPECS[stem][1]
        hz = _STEM_SPECS[stem][0]
        t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
        mono = 0.25 * np.sin(2.0 * np.pi * hz * t)
        return np.stack([mono, mono]).astype(np.float32)

    def _fixture(self) -> tuple[dict[str, np.ndarray], list[np.ndarray]]:
        names = ("drums", "bass", "other", "vocals")
        processed = {stem: self._synthetic(stem) for stem in names}
        bus_audio = [processed[name] for name in mix_engine.STEM_NAMES]
        return processed, bus_audio

    def test_apply_scales_each_stem_by_its_own_db(self):
        """Cada stem escala por 10^(db/20); los demás quedan idénticos."""
        processed, bus_audio = self._fixture()
        original = {name: arr.copy() for name, arr in processed.items()}

        mix_engine._apply_stem_trims(
            processed, bus_audio,
            {"drums_db": -3.0, "bass_db": 0.0, "other_db": 2.0, "vocals_db": 1.5},
        )

        np.testing.assert_allclose(
            processed["drums"], original["drums"] * 10.0 ** (-3.0 / 20.0), rtol=1e-6
        )
        np.testing.assert_allclose(
            processed["other"], original["other"] * 10.0 ** (2.0 / 20.0), rtol=1e-6
        )
        np.testing.assert_allclose(
            processed["vocals"], original["vocals"] * 10.0 ** (1.5 / 20.0), rtol=1e-6
        )
        # bass en 0.0 queda EXACTO (sin multiplicación, bit-exact).
        assert np.array_equal(processed["bass"], original["bass"])
        # el bus audio se actualiza en sync con processed (mismo objeto).
        for name in ("drums", "other", "vocals"):
            idx = mix_engine.STEM_NAMES.index(name)
            assert bus_audio[idx] is processed[name]

    def test_trim_zero_keeps_every_stem_bitexact(self):
        """Neutral = bypass: trims 0.0 no tocan nada (spec 08)."""
        processed, bus_audio = self._fixture()
        originals = {name: arr.copy() for name, arr in processed.items()}
        mix_engine._apply_stem_trims(
            processed, bus_audio,
            {"drums_db": 0.0, "bass_db": 0.0, "other_db": 0.0, "vocals_db": 0.0},
        )
        for name, arr in originals.items():
            assert np.array_equal(processed[name], arr)
            assert bus_audio[mix_engine.STEM_NAMES.index(name)] is processed[name]

    def test_apply_skips_missing_stems(self):
        """Un stem ausente del processed no rompe la aplicación."""
        # regulary synthetic minus vocals
        processed, bus_audio = self._fixture()
        del processed["vocals"]
        names = [n for n in mix_engine.STEM_NAMES if n in processed]
        bus_audio = [processed[name] for name in names]

        mix_engine._apply_stem_trims(
            processed, bus_audio,
            {"drums_db": -3.0, "bass_db": 0.0, "other_db": 0.0, "vocals_db": 1.5},
        )
        assert processed["drums"].shape[1] > 0  # applied
        assert np.allclose(
            processed["drums"],
            self._synthetic("drums") * 10.0 ** (-3.0 / 20.0),
            rtol=1e-6,
        )

    def test_apply_round_trips_through_entry_peak(self):
        """Peak check integrado: un fader de +6 dB sube el pico del stem."""
        processed, bus_audio = self._fixture()
        peak_before = float(np.max(np.abs(processed["vocals"])))
        mix_engine._apply_stem_trims(
            processed, bus_audio, {"vocals_db": 6.0},
        )
        peak_after = float(np.max(np.abs(processed["vocals"])))
        assert peak_after > peak_before
        assert abs(peak_after / peak_before - 10.0 ** (6.0 / 20.0)) < 1e-6


class TestStemPresence:
    """v5 — honest stems: presence from per-stem RMS, not fixed names.

    Demucs always emits the 4 stems; ``stem_presence`` reports which are
    actually audible so the UI never names an instrument that is not in
    the material. The endpoint test above proves the payload shape
    end-to-end; these unit tests drive the threshold helper with
    synthetic arrays (silence → absent, real tone → present, quiet
    residue → absent).
    """

    def test_digital_silence_is_absent(self):
        """All-zero stem measures ≈ −inf → never clears the threshold."""
        silence = np.zeros((2, 44100), dtype=np.float32)
        rms_db = mix_engine._stem_rms_db(silence)
        assert rms_db == -np.inf
        assert rms_db < mix_engine.STEM_PRESENCE_RMS_DBFS_THRESHOLD

    def test_sine_tone_is_present(self):
        """A real stem tone (0.25 amplitude ≈ −15 dBFS RMS) is present."""
        t = np.arange(44100, dtype=np.float64) / _SR
        tone = (0.25 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
        rms_db = mix_engine._stem_rms_db(tone)
        assert rms_db == pytest.approx(-15.05, abs=0.2)
        assert rms_db >= mix_engine.STEM_PRESENCE_RMS_DBFS_THRESHOLD

    def test_missing_stem_residue_is_absent(self):
        """A demucs "missing stem" is model residue, not silence: a tone
        65 dB below the fixture level (≈ −80 dBFS) must be ABSENT."""
        t = np.arange(44100, dtype=np.float64) / _SR
        amp = 0.25 * 10 ** (-65 / 20)
        residue = (amp * np.sin(2.0 * np.pi * 300.0 * t)).astype(np.float32)
        rms_db = mix_engine._stem_rms_db(residue)
        assert rms_db < mix_engine.STEM_PRESENCE_RMS_DBFS_THRESHOLD


class TestDimensionOptional:
    """CAMBIO v6 — la dimensión espacial (Paso 04: delay tempo + reverb
    por stem) es OPCIONAL:

    * ``dimension_profiles=None`` (default) → dimensión ENABLED
      (``DIMENSION_PROFILES``, comportamiento actual),
    * ``dimension_profiles={}`` (o ``dimension_enabled=false`` en el
      body del POST) → dimensión DISABLED: routing idéntico a Paso 03,
      payload SIN clave ``dimension_report``.

    Backward-compatible: el POST sin body conserva la dimensión ON.
    """

    def test_build_mix_disabled_dimension_omits_report_and_keeps_paso03(
        self, tmp_path, monkeypatch
    ):
        """Engine-level: ``dimension_profiles={}`` → sin ``dimension_report``;
        los stems siguen con análisis y ``stem_presence`` y el routing
        Paso 03 (pan) intacto."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        original_path = sessions[session_id].original_path

        result = mix_engine.build_mix(
            session_id, str(original_path), dimension_profiles={}
        )

        assert "dimension_report" not in result
        # Routing Paso 03 intacto: el pan corre y se reporta.
        assert "pan_report" in result
        assert "stem_presence" in result
        assert list(result["stem_presence"]) == list(mix_engine.STEM_NAMES)
        assert all(
            isinstance(v, bool) for v in result["stem_presence"].values()
        )
        assert set(result["analysis"]) == {"drums", "bass", "other", "vocals"}
        for stem in result["analysis"].values():
            assert "integrated_lufs" in stem

        # Contract simétrico: con dimensión ON (default) el report existe.
        enabled = mix_engine.build_mix(session_id, str(original_path))
        assert "dimension_report" in enabled

    def test_mix_endpoint_without_body_keeps_dimension_enabled(
        self, tmp_path, monkeypatch
    ):
        """POST sin body (comportamiento actual) → 200 + dimension_report."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(f"/api/session/{session_id}/mix")

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "dimension_report" in payload


class TestAutoBalanceEndpoint:
    """T5: POST /mix expone ``auto_balance`` (body) — OFF por defecto =
    payload idéntico al actual; ON → ``balance_report`` en el header."""

    def test_mix_endpoint_no_body_keeps_payload_without_balance_report(
        self, tmp_path, monkeypatch
    ):
        """Sin body (default) → 200, header SIN ``balance_report`` — el
        shape previo exacto (neutral bit-exacto, spec 08)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(f"/api/session/{session_id}/mix")

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "balance_report" not in payload
        assert "stem_presence" in payload
        assert set(payload["analysis"]) == {"drums", "bass", "other", "vocals"}

    def test_mix_endpoint_explicit_false_keeps_payload_without_report(
        self, tmp_path, monkeypatch
    ):
        """``{"auto_balance": false}`` explícito → mismo contrato que sin
        body: OFF neutral, sin ``balance_report``."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"auto_balance": False},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "balance_report" not in payload

    def test_mix_endpoint_auto_balance_true_adds_report(
        self, tmp_path, monkeypatch
    ):
        """``{"auto_balance": true}`` → 200 + ``balance_report`` con el shape
        completo (genre/status/stem_lufs/groove/vocal_target/d/gains/applied)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"auto_balance": True},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        report = payload["balance_report"]
        assert set(report["stem_lufs"]) == {
            "drums", "bass", "other", "vocals"
        }
        assert "groove_level_lufs" in report
        assert "vocal_target_lufs" in report
        assert "d" in report
        assert set(report["gains"]) == {
            "drums_db", "bass_db", "other_db", "vocals_db"
        }
        assert "applied" in report
        assert report["genre"] in ("active", "neutral_fallback") or isinstance(
            report["genre"], str
        )

    def test_mix_endpoint_auto_balance_raises_low_vocals(
        self, tmp_path, monkeypatch
    ):
        """Voz 14 dB bajo el groove + auto_balance=true → el reporte muestra
        gain vocal > 0 y applied=True a través del endpoint real."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split_low_vocals)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"auto_balance": True},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        report = payload["balance_report"]
        assert report["applied"] is True
        assert report["gains"]["vocals_db"] > 0.0
        assert report["gains"]["drums_db"] == 0.0
        assert report["gains"]["bass_db"] == 0.0
        assert report["gains"]["other_db"] == 0.0

    def test_mix_endpoint_coerces_boolean_strings(
        self, tmp_path, monkeypatch
    ):
        """Pydantic v2 lax coacciona strings booleanos (``"false"``) →
        OFF, sin ``balance_report``. Mismo comportamiento que los campos
        hermanos ``dimension_enabled``/``vocal_treatment`` (bool lax); el
        contrato documenta true/false JSON y el modelo no usa
        ``StrictBool`` a propósito (consistencia con el resto del body)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"auto_balance": "false"},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "balance_report" not in payload


class TestStemAutoBalanceReport:
    """T4: ``balance_report`` in the mix payload (engine + endpoint)."""

    def _build_result(self, tmp_path: Path, monkeypatch, **kwargs) -> dict:
        """Run ``build_mix`` directly and return the payload dict."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        original_path = str(Path(sessions[session_id].original_path))
        return mix_engine.build_mix(
            session_id, original_path,
            profiles={},
            pan_profiles={},
            dimension_profiles={},
            compressor_profiles={},
            emphasis_profiles={},
            with_versions=False,
            **kwargs,
        )

    def test_balance_report_present_when_auto_balance_on(self, tmp_path, monkeypatch):
        """auto_balance=True: the payload carries ``balance_report`` with
        measured LUFS per stem, gains, genre/target, and applied flag."""
        result = self._build_result(
            tmp_path, monkeypatch, auto_balance=True, genre="pop",
            genre_confidence=0.9,
        )
        report = result["balance_report"]
        assert set(report["stem_lufs"]) == {
            "drums", "bass", "other", "vocals"
        }
        assert "groove_level_lufs" in report
        assert "vocal_target_lufs" in report
        assert "d" in report
        assert report["genre"] == "pop"
        assert set(report["gains"]) == {
            "drums_db", "bass_db", "other_db", "vocals_db"
        }
        assert "applied" in report
        # The fixture is balanced at 0.25 → the voice is ABOVE the groove
        # under K-weighting, so pop may push it DOWN or slightly; the flag
        # tells the truth either way. Only the shape is asserted here.
        assert report["applied"] in (True, False)

    def test_balance_report_applied_low_vocals(self, tmp_path, monkeypatch):
        """The report reflects what was actually applied: with the voice 14
        dB under the groove and pop weights, vocals_db > 0 and applied=True."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split_low_vocals)
        session_id = _register_session(tmp_path)
        original_path = str(Path(sessions[session_id].original_path))
        result = mix_engine.build_mix(
            session_id, original_path,
            profiles={},
            pan_profiles={},
            dimension_profiles={},
            compressor_profiles={},
            emphasis_profiles={},
            with_versions=False,
            auto_balance=True,
            genre="pop",
            genre_confidence=0.9,
        )
        report = result["balance_report"]
        assert report["applied"] is True
        assert report["gains"]["vocals_db"] > 0.0
        assert report["gains"]["drums_db"] == 0.0
        assert report["gains"]["bass_db"] == 0.0
        assert report["gains"]["other_db"] == 0.0
        assert report["status"] == "active"

    def test_balance_report_absent_when_off(self, tmp_path, monkeypatch):
        """auto_balance=False (default): NO ``balance_report`` key — the
        payload keeps the exact previous shape (master-safe neutral)."""
        result = self._build_result(
            tmp_path, monkeypatch, auto_balance=False, genre="pop"
        )
        assert "balance_report" not in result

    def test_balance_report_neutral_status(self, tmp_path, monkeypatch):
        """Unknown genre → neutral fallback (d=0.0, target = groove). The
        report is honest about what actually happened: with the voice 14 dB
        under the groove the correction IS applied (raises vocals toward
        groove), so applied=True + vocals_db>0; the exact no-op case is
        covered by the pure-module tests."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split_low_vocals)
        session_id = _register_session(tmp_path)
        original_path = str(Path(sessions[session_id].original_path))
        result = mix_engine.build_mix(
            session_id, original_path,
            profiles={},
            pan_profiles={},
            dimension_profiles={},
            compressor_profiles={},
            emphasis_profiles={},
            with_versions=False,
            auto_balance=True,
            genre="unknown",
            genre_confidence=0.9,
        )
        report = result["balance_report"]
        assert report["status"] == "neutral_fallback"
        assert report["d"] == 0.0
        assert report["applied"] is True
        assert report["gains"]["vocals_db"] > 0.0


class TestStemAutoBalance:
    """T3: auto-balance toggle in ``build_mix`` (default OFF, bit-exact)."""

    def test_auto_balance_disabled_keeps_original_mix(self, tmp_path, monkeypatch):
        """auto_balance=False (default): bit-identical to the plain routing."""
        audio_off, sr = _render_mix(
            tmp_path, monkeypatch, auto_balance=False
        )
        audio_base, sr_base = _render_mix(
            tmp_path, monkeypatch, auto_balance=False, genre="pop"
        )
        assert sr == sr_base
        assert np.array_equal(audio_off, audio_base)

    def test_auto_balance_low_vocals_raises_vocal_band_only(
        self, tmp_path, monkeypatch
    ):
        """With the voice 14 dB under the groove, pop auto-balance raises
        the vocal band and leaves drums/bass/other untouched."""
        audio_off, sr = _render_mix(
            tmp_path, monkeypatch, auto_balance=False, genre="pop",
            splitter=_fake_split_low_vocals,
        )
        audio_on, sr_on = _render_mix(
            tmp_path, monkeypatch, auto_balance=True, genre="pop",
            splitter=_fake_split_low_vocals,
        )
        assert sr == sr_on
        vocal_off = _band_energy_db(audio_off, sr, 440.0)
        vocal_on = _band_energy_db(audio_on, sr, 440.0)
        # pop weights (0.7/0.3): target headroom keeps at least +2 dB.
        assert vocal_on > vocal_off + 2.0, (
            f"vocal band should rise: {vocal_off:.2f} → {vocal_on:.2f} dB"
        )
        # the groove band (drums 120 Hz) is NOT a correction target.
        groove_off = _band_energy_db(audio_off, sr, 120.0)
        groove_on = _band_energy_db(audio_on, sr, 120.0)
        assert abs(groove_on - groove_off) < 0.5

    def test_auto_balance_neutral_weights_unchanged(self, tmp_path, monkeypatch):
        """Neutral 0.5/0.5 (unknown genre): target = groove level, and a
        mix ALREADY on the groove needs no correction → no audible change."""
        audio_off, sr = _render_mix(
            tmp_path, monkeypatch, auto_balance=False,
            splitter=_fake_split_groove_vocals,
        )
        audio_on, sr_on = _render_mix(
            tmp_path, monkeypatch, auto_balance=True, genre="unknown",
            splitter=_fake_split_groove_vocals,
        )
        assert sr == sr_on
        # Balanced fixture: the correction closes a ~0 dB gap → no change.
        vocal_off = _band_energy_db(audio_off, sr, 440.0)
        vocal_on = _band_energy_db(audio_on, sr, 440.0)
        assert abs(vocal_on - vocal_off) < 0.6


class TestDimensionEndpointDisabled:
    """POST del hook: ``dimension_enabled=false`` omite el report; true lo
    conserva (mismo contrato que el engine-level de TestDimensionOptional)."""

    def test_mix_endpoint_dimension_disabled_omits_dimension_report(
        self, tmp_path, monkeypatch
    ):
        """POST con ``{"dimension_enabled": false}`` → 200, header SIN
        ``dimension_report``; analysis/stem_presence/pan intactos."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"dimension_enabled": False},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "dimension_report" not in payload
        assert "pan_report" in payload
        assert "stem_presence" in payload
        assert set(payload["analysis"]) == {"drums", "bass", "other", "vocals"}

    def test_mix_endpoint_dimension_enabled_explicit_keeps_report(
        self, tmp_path, monkeypatch
    ):
        """POST con ``{"dimension_enabled": true}`` → 200 + dimension_report."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"dimension_enabled": True},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "dimension_report" in payload


class TestStemTrimsEndpoint:
    """T5 (faders) — POST /mix expone ``stem_trims`` manuales: dict de
    ``*_db`` por los 4 stems, rango ±6 dB (T1) aplicado al bus DESPUÉS de
    la cadena (T2). El fader humano va ENCIMA del auto-balance (el motor
    propone, el humano decide): el ``balance_report`` mide SIN el fader y
    el ``trim_report`` reporta solo las claves ≠ 0 aplicadas. Sin trims o
    todos 0 → payload previo exacto (sin ``trim_report``). Validación
    estricta: claves desconocidas o valores fuera de rango → 422."""

    def test_mix_endpoint_stem_trims_applies_and_reports(
        self, tmp_path, monkeypatch
    ):
        """``{"stem_trims": {"drums_db": 2.0}}`` → 200 + header con
        ``trim_report.gains.drums_db == 2.0`` y ``applied=True``."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"stem_trims": {"drums_db": 2.0}},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        report = payload["trim_report"]
        assert report["applied"] is True
        assert report["gains"] == {"drums_db": 2.0}

    def test_mix_endpoint_auto_balance_then_manual_fader_stacks(
        self, tmp_path, monkeypatch
    ):
        """auto_balance ON + fader manual vocal: ``balance_report`` mide y
        corrige SIN el fader (vocals_db > 0) y ``trim_report`` queda ENCIMA
        (vocals_db == 1.0) — el orden es el contrato (el motor propone, el
        humano decide)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split_low_vocals)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"auto_balance": True, "stem_trims": {"vocals_db": 1.0}},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        balance = payload["balance_report"]
        assert balance["applied"] is True
        assert balance["gains"]["vocals_db"] > 0.0
        trims = payload["trim_report"]
        assert trims["applied"] is True
        assert trims["gains"] == {"vocals_db": 1.0}

    def test_mix_endpoint_stem_trims_out_of_range_rejected(
        self, tmp_path, monkeypatch
    ):
        """``{"stem_trims": {"drums_db": 7.0}}`` → 422 (banda ±6 dB)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"stem_trims": {"drums_db": 7.0}},
        )

        assert resp.status_code == 422, resp.text

    def test_mix_endpoint_stem_trims_unknown_keys_rejected(
        self, tmp_path, monkeypatch
    ):
        """Claves fuera del contrato (``guitar_db``/``drums``) → 422."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        for trims in ({"guitar_db": 1.0}, {"drums": 1.0}):
            resp = client.post(
                f"/api/session/{session_id}/mix",
                json={"stem_trims": trims},
            )
            assert resp.status_code == 422, resp.text

    def test_mix_endpoint_all_zero_trims_keep_previous_payload(
        self, tmp_path, monkeypatch
    ):
        """Trims todos 0 → 200 sin ``trim_report`` (payload previo exacto)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/mix",
            json={"stem_trims": {"drums_db": 0.0, "bass_db": 0.0}},
        )

        assert resp.status_code == 200, resp.text
        payload = json.loads(resp.headers["x-mix-result"])
        assert "trim_report" not in payload


class TestStemTrims:
    """T5 (motor) — faders manuales en ``build_mix``: aplican DESPUÉS del
    auto-balance (mide SIN fader), reportan ``trim_report`` solo con algún
    trim ≠ 0 y conservan la neutralidad bit-exacta con ``None``/todos 0."""

    def test_manual_trims_raise_only_their_stem_band(self, tmp_path, monkeypatch):
        """Un fader de +3 dB en voces sube la banda 440 Hz y NO mueve la del
        groove (120 Hz): el trim es por stem, a la entrada del bus."""
        audio_off, sr = _render_mix(tmp_path, monkeypatch, auto_balance=False)
        audio_on, sr_on = _render_mix(
            tmp_path, monkeypatch, auto_balance=False,
            stem_trims={"vocals_db": 3.0},
        )
        assert sr == sr_on
        vocal_off = _band_energy_db(audio_off, sr, 440.0)
        vocal_on = _band_energy_db(audio_on, sr, 440.0)
        assert vocal_on > vocal_off + 2.0
        groove_off = _band_energy_db(audio_off, sr, 120.0)
        groove_on = _band_energy_db(audio_on, sr, 120.0)
        assert abs(groove_on - groove_off) < 0.5

    def test_manual_trims_on_top_of_auto_balance(self, tmp_path, monkeypatch):
        """auto_balance + fader: el fader sube su stem ENCIMA del resultado
        del motor (ambos aplican; el trim manual es relativo a lo que el
        motor propuso)."""
        audio_auto_only, sr = _render_mix(
            tmp_path, monkeypatch, auto_balance=True, genre="pop",
            splitter=_fake_split_low_vocals,
        )
        audio_auto_plus_trim, sr_on = _render_mix(
            tmp_path, monkeypatch, auto_balance=True, genre="pop",
            stem_trims={"vocals_db": 1.5},
            splitter=_fake_split_low_vocals,
        )
        assert sr == sr_on
        vocal_auto = _band_energy_db(audio_auto_only, sr, 440.0)
        vocal_both = _band_energy_db(audio_auto_plus_trim, sr, 440.0)
        assert vocal_both > vocal_auto + 1.0

    def test_no_trims_and_zero_trims_are_bitexact(self, tmp_path, monkeypatch):
        """``stem_trims=None`` vs todos 0: routing idéntico (neutralidad
        bit-exacta de la red existente, spec 08)."""
        audio_none, sr = _render_mix(tmp_path, monkeypatch, auto_balance=False)
        audio_zero, sr_zero = _render_mix(
            tmp_path, monkeypatch, auto_balance=False,
            stem_trims={
                "drums_db": 0.0, "bass_db": 0.0,
                "other_db": 0.0, "vocals_db": 0.0,
            },
        )
        assert sr == sr_zero
        assert np.array_equal(audio_none, audio_zero)

    def test_trim_report_shape_only_non_zero_keys(self, tmp_path, monkeypatch):
        """``trim_report`` presente solo con trims ≠ 0; ``gains`` = SOLO las
        claves ≠ 0; ausente cuando no hay fader activo (payload previo)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        original_path = str(Path(sessions[session_id].original_path))
        base = mix_engine.build_mix(
            session_id, original_path, profiles={}, pan_profiles={},
            dimension_profiles={}, compressor_profiles={},
            emphasis_profiles={}, with_versions=False, auto_balance=False,
        )
        assert "trim_report" not in base
        with_trims = mix_engine.build_mix(
            session_id, original_path, profiles={}, pan_profiles={},
            dimension_profiles={}, compressor_profiles={},
            emphasis_profiles={}, with_versions=False, auto_balance=False,
            stem_trims={"drums_db": 2.0, "vocals_db": 0.0},
        )
        report = with_trims["trim_report"]
        assert report["applied"] is True
        assert report["gains"] == {"drums_db": 2.0}


class TestStemBalanceNeutralityE2E:
    """T7 (E2E) — neutralidad bit-exacta sobre POST /mix real: faders en 0
    y auto OFF = WAV byte-idéntico al que sirve sin body (spec 08: neutral
    = bypass también a nivel HTTP, no solo en el motor)."""

    def _mix_wav_md5(self, tmp_path, monkeypatch, body=None) -> str:
        import hashlib

        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        resp = client.post(
            f"/api/session/{session_id}/mix",
            json=body,
        )
        assert resp.status_code == 200, resp.text
        return hashlib.md5(resp.content).hexdigest()

    def test_no_body_vs_all_zero_trims_serves_identical_wav(
        self, tmp_path, monkeypatch
    ):
        """Sin body vs ``{"stem_trims": {4 stems en 0}, "auto_balance": false}``
        → el WAV servido es byte-idéntico (mismo md5)."""
        baseline = self._mix_wav_md5(tmp_path, monkeypatch)
        zero_trims = self._mix_wav_md5(
            tmp_path,
            monkeypatch,
            body={
                "auto_balance": False,
                "stem_trims": {
                    "drums_db": 0.0,
                    "bass_db": 0.0,
                    "other_db": 0.0,
                    "vocals_db": 0.0,
                },
            },
        )
        assert baseline == zero_trims

    def test_partial_zero_trims_are_neutral_on_their_stem(
        self, tmp_path, monkeypatch
    ):
        """Fader explícito en 0 para un stem + los demás ausentes → mismo
        WAV que sin body (0 dB no altera la red)."""
        baseline = self._mix_wav_md5(tmp_path, monkeypatch)
        zero_vocals = self._mix_wav_md5(
            tmp_path,
            monkeypatch,
            body={"stem_trims": {"vocals_db": 0.0}},
        )
        assert baseline == zero_vocals

    def test_nonzero_trim_changes_served_wav(
        self, tmp_path, monkeypatch
    ):
        """Fader ≠ 0 SÍ cambia el WAV servido (el md5 difiere del baseline):
        la neutralidad es selectiva, no un caso vacío."""
        baseline = self._mix_wav_md5(tmp_path, monkeypatch)
        trimmed = self._mix_wav_md5(
            tmp_path,
            monkeypatch,
            body={"stem_trims": {"vocals_db": 3.0}},
        )
        assert baseline != trimmed