"""TDD tests for the adaptive vocal treatment by measured register.

RED → GREEN → REFACTOR contract (Eje A, entregable 2 —
``odd/tasks/voz-tratamiento-adaptativo.md``):

Eje B (``analysis/register_detection.py``, librosa.pyin, green) fills
``AnalysisResult.vocal_register`` / ``vocal_median_f0_hz``, but nothing in
the engine CONSUMED that measurement to treat the vocal stem — the adaptive
treatment did not exist. These tests pin it:

* T1 — ``resolve_vocal_treatment`` consumes the measured register/f0 and
  resolves the per-register chain: presence/sibilance EQ + LP per class
  (grave/medio/agudo) + OPTIONAL dimension (reverb) refinement; no credible
  voice (or unknown label) → neutral plan, never an invented register.
* T2 — every value without a source is marked HIPÓTESIS; the continuous
  knobs (presence gain, LP corner) are DERIVED from the measured median f0
  by documented hypothesis formulas.
* T3 — transparency: ``apply_vocal_treatment`` reports what ran and why
  (Spanish neutral); no credible voice → THE SAME array object (honest
  bypass); ``build_mix(vocal_treatment=True)`` exposes
  ``vocal_treatment_report``; the API accepts the opt-in.
* T4 — master-safe: default off = the exact previous routing (no
  ``vocal_treatment_report`` key, no behaviour change); the register
  refinement never leaves the engine's validated ranges (reverb mix
  [0, 1], size [0.1, 1.0], pre-delay < 40 ms); no compressor is forced
  ("solo EQ + Reverb sin compresor" is a licit variant).

Runner real: ``apps/audiomind/.venv/Scripts/python.exe -m pytest``.
"""
import sys

sys.path.insert(0, "src")

import uuid

import numpy as np
import pytest
import soundfile as sf

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.dimension import DIMENSION_PROFILES
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from audiomind.processing.vocal_adaptive import (
    REGISTER_DIMENSION_ADJUSTMENTS,
    apply_register_dimension,
    apply_vocal_treatment,
    resolve_vocal_treatment,
)
from tests.test_mix_engine import _fake_split

_SR = 44100
_REGISTER_CLASSES = ("grave", "medio", "agudo")
_HYPO_TOKEN = "HIPÓTESIS"


# ── Synthetic fixtures ──────────────────────────────────────────────────

def _harmonic_vocal(f0_hz: float, duration: float = 3.0) -> np.ndarray:
    """Harmonic-rich synthetic voice (same construction as
    ``tests/test_register_detection.py`` — pyin-friendly, proven to
    classify through ``analyze_audio``)."""
    t = np.linspace(0, duration, int(_SR * duration), endpoint=False)
    phase = 2 * np.pi * f0_hz * t
    y = (
        np.sin(phase)
        + 0.5 * np.sin(2 * phase)
        + 0.35 * np.sin(3 * phase)
        + 0.2 * np.sin(4 * phase)
    )
    rng = np.random.default_rng(7)
    y = y + 0.005 * rng.standard_normal(len(t))
    return 0.25 * y / max(abs(y))


def _split_with_vocals(vocal: np.ndarray):
    """``split_audio`` stand-in whose vocal stem carries ``vocal``."""
    def _split(input_path, output_dir=None, model="htdemucs"):
        out = mix_engine.Path(output_dir).resolve() if output_dir else None
        out = out or (mix_engine.settings.output_dir / "stems")
        out.mkdir(parents=True, exist_ok=True)
        specs = {"drums": (120.0, 0.75), "bass": (90.0, 1.0), "other": (330.0, 1.0)}
        stems: dict[str, str] = {}
        for name, (hz, seconds) in specs.items():
            path = out / f"{name}.wav"
            t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
            sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), _SR)
            stems[name] = str(path)
        vocal_path = out / "vocals.wav"
        sf.write(str(vocal_path), vocal, _SR)
        stems["vocals"] = str(vocal_path)
        return {
            "stems": stems,
            "sample_rate": _SR,
            "duration_seconds": 3.0,
            "stem_audio_dir": str(out),
        }
    return _split


def _tone(freq: float, duration: float = 1.0) -> np.ndarray:
    """Short float32 stereo sine (channels, samples)."""
    n = int(_SR * duration)
    t = np.linspace(0.0, duration, n, endpoint=False)
    s = np.sin(2.0 * np.pi * freq * t).astype(np.float32)
    return np.stack([s, s])


def _band_rms(audio: np.ndarray, lo_hz: float, hi_hz: float, sr: int = _SR) -> float:
    mono = audio[0]
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    assert np.any(mask), f"no FFT bins in [{lo_hz}, {hi_hz}] Hz"
    return float(np.sqrt(np.mean(spec[mask] ** 2)))


# ── T1: resolve consumes the measured register/f0 (motor B) ────────────

class TestResolveVocalTreatment:
    """Register + median f0 in → per-register treatment plan out."""

    @pytest.mark.parametrize("register", _REGISTER_CLASSES)
    def test_every_measured_register_gets_an_applied_plan(self, register):
        plan = resolve_vocal_treatment(register, 180.0)
        assert plan["status"] == "applied"
        assert plan["register"] == register
        assert plan["median_f0_hz"] == 180.0
        assert plan["eq_bands"], "applied plan must carry the register EQ"
        assert plan["dimension_adjustment"] == REGISTER_DIMENSION_ADJUSTMENTS[
            register
        ]

    def test_no_register_neutral_plan(self):
        """No credible voice (AnalysisResult.vocal_register is None) →
        neutral plan: no EQ, no LP, no dimension adjustment."""
        plan = resolve_vocal_treatment(None, None)
        assert plan["status"] == "no_voice"
        assert plan["register"] is None
        assert plan["median_f0_hz"] is None
        assert plan["eq_bands"] == []
        assert plan["lp_hz"] is None
        assert plan["dimension_adjustment"] == {}
        assert plan["why"]

    def test_unknown_register_label_neutral_plan(self):
        """Alex guard: a label the classifier never emits never triggers
        treatment (no crash, no invented knobs)."""
        plan = resolve_vocal_treatment("radio", 200.0)
        assert plan["status"] == "no_voice"
        assert plan["eq_bands"] == []
        assert plan["dimension_adjustment"] == {}

    def test_eq_carry_presence_and_sibilance_per_class(self):
        """T1: the chain is presence + sibilance EQ chosen by class."""
        for register in _REGISTER_CLASSES:
            plan = resolve_vocal_treatment(register, 200.0)
            freqs = [band["freq_hz"] for band in plan["eq_bands"]]
            assert len(freqs) == 2
            assert any(2500.0 <= f <= 5000.0 for f in freqs), "presence band"
            assert any(6000.0 <= f <= 9000.0 for f in freqs), "sibilance band"
            types = {band["type"] for band in plan["eq_bands"]}
            assert "boost" in types  # presence
            assert "cut" in types    # sibilance

    def test_lp_is_defined_per_class_agudo_only(self):
        """T1: LP por clase — declared for every class, engaged for
        ``agudo`` (hypothesis: tame the top of a bright voice)."""
        assert resolve_vocal_treatment("grave", 110.0)["lp_hz"] is None
        assert resolve_vocal_treatment("medio", 200.0)["lp_hz"] is None
        lp = resolve_vocal_treatment("agudo", 300.0)["lp_hz"]
        assert lp is not None
        assert 11000.0 <= lp <= 15000.0

    def test_dimension_adjustments_cover_every_class(self):
        assert set(_REGISTER_CLASSES) <= set(REGISTER_DIMENSION_ADJUSTMENTS)
        # medio = base preserved (empty adjustment), the honest default.
        assert REGISTER_DIMENSION_ADJUSTMENTS["medio"] == {}
        # grave/agudo carry real direction (shorter/darker / longer separation).
        assert REGISTER_DIMENSION_ADJUSTMENTS["grave"]
        assert REGISTER_DIMENSION_ADJUSTMENTS["agudo"]

    def test_why_explains_what_and_which_register(self, ):
        """T3: the report explains QUÉ se aplicó y por qué registro."""
        for register in _REGISTER_CLASSES:
            plan = resolve_vocal_treatment(register, 200.0)
            assert register in plan["why"]
            assert _HYPO_TOKEN in plan["why"]
        no_voice = resolve_vocal_treatment(None, None)
        assert "sin tratamiento" in no_voice["why"]


# ── T2: values derived from the measurements, all marked HIPÓTESIS ──────

class TestTreatmentValuesAreHypotheses:
    """No source value exists for these knobs → every one is a marked
    HIPÓTESIS; the continuous ones derive from the measured median f0."""

    @pytest.mark.parametrize("register", _REGISTER_CLASSES)
    def test_every_band_is_marked_hypothesis(self, register):
        plan = resolve_vocal_treatment(register, 200.0)
        assert plan["hypothesis"] is True
        for band in plan["eq_bands"]:
            assert _HYPO_TOKEN in band["source"]
            assert band["q"] > 0.0
            assert band["freq_hz"] > 0.0
            assert abs(band["gain_db"]) <= 6.0  # sane envelope
            assert band["filter"] in {"peak", "low_shelf", "high_shelf"}

    def test_presence_gain_derives_from_measured_f0(self):
        """Deeper measured f0 → larger presence lift (same class), by the
        documented hypothesis formula — never a fixed number."""
        deep = resolve_vocal_treatment("grave", 90.0)
        less_deep = resolve_vocal_treatment("grave", 160.0)
        g_deep = next(
            b["gain_db"] for b in deep["eq_bands"] if b["type"] == "boost"
        )
        g_less = next(
            b["gain_db"] for b in less_deep["eq_bands"] if b["type"] == "boost"
        )
        assert g_deep > g_less

    def test_lp_corner_derives_from_measured_f0(self):
        """Agudo LP corner tracks the measured median f0 (clamped)."""
        low_agudo = resolve_vocal_treatment("agudo", 260.0)["lp_hz"]
        high_agudo = resolve_vocal_treatment("agudo", 400.0)["lp_hz"]
        assert low_agudo is not None and high_agudo is not None
        assert low_agudo < high_agudo
        assert high_agudo <= 15000.0  # clamp holds

    def test_f0_none_falls_back_to_class_base(self):
        """Defensive: register without f0 keeps class bases (no crash)."""
        plan = resolve_vocal_treatment("grave", None)
        assert plan["status"] == "applied"
        assert plan["lp_hz"] is None
        gains = [b["gain_db"] for b in plan["eq_bands"] if b["type"] == "boost"]
        assert gains and all(np.isfinite(gains))


# ── T1/T3: apply — engaged path measurable, neutral path bit-exact ─────

class TestApplyVocalTreatment:
    """EQ (+ LP) stage on the vocal stem with an honest neutral bypass."""

    def test_no_voice_returns_same_object(self):
        """Bypass = neutral honest: no credible voice → same array object."""
        audio = _tone(1000.0)
        plan = resolve_vocal_treatment(None, None)
        out, report = apply_vocal_treatment(audio, _SR, plan)
        assert out is audio
        assert report["applied"] is False
        assert report["register"] is None

    def test_engaged_preserves_shape_dtype_and_is_finite(self):
        audio = _tone(1000.0)
        plan = resolve_vocal_treatment("medio", 200.0)
        out, report = apply_vocal_treatment(audio, _SR, plan)
        assert out is not audio
        assert out.shape == audio.shape
        assert out.dtype == audio.dtype
        assert np.all(np.isfinite(out))
        assert report["applied"] is True

    def test_grave_presence_boost_lifts_the_presence_band(self):
        """Measurable: the derived presence boost really moves the band."""
        audio = _tone(3500.0, duration=0.5)
        plan = resolve_vocal_treatment("grave", 110.0)
        out, report = apply_vocal_treatment(audio, _SR, plan)
        dry = _band_rms(audio, 3000.0, 4000.0)
        wet = _band_rms(out, 3000.0, 4000.0)
        assert wet > 1.1 * dry
        assert report["eq_bands"]

    def test_agudo_lp_rolls_off_the_air(self):
        """Measurable: the agudo LP (derived from f0) attenuates content
        above its corner."""
        audio = _tone(15500.0, duration=0.5)
        plan = resolve_vocal_treatment("agudo", 260.0)  # LP = 13520 Hz
        assert plan["lp_hz"] is not None
        out, _ = apply_vocal_treatment(audio, _SR, plan)
        dry = _band_rms(audio, 14000.0, 17000.0)
        wet = _band_rms(out, 14000.0, 17000.0)
        assert wet < 0.85 * dry

    def test_report_carries_register_f0_and_hypothesis(self):
        plan = resolve_vocal_treatment("medio", 210.0)
        _, report = apply_vocal_treatment(_tone(1000.0), _SR, plan)
        assert report["register"] == "medio"
        assert report["median_f0_hz"] == 210.0
        assert report["hypothesis"] is True
        assert "medio" in report["why"]
        assert _HYPO_TOKEN in report["why"]


# ── T4: register refinement stays inside the engine ranges ─────────────

class TestApplyRegisterDimension:
    """The optional reverb refinement adjusts ONLY the vocal knobs,
    AFTER the genre scaling, never leaving the validated ranges."""

    def test_medio_adjustment_preserves_the_base_profile(self):
        """Base preserved (hypothesis table: medio carries no shift)."""
        base = DIMENSION_PROFILES["vocals"]
        adjusted = apply_register_dimension(
            base, REGISTER_DIMENSION_ADJUSTMENTS["medio"]
        )
        assert adjusted == base

    def test_grave_shortens_and_darkens_the_reverb(self):
        plan = resolve_vocal_treatment("grave", 110.0)
        adjusted = apply_register_dimension(
            DIMENSION_PROFILES["vocals"], plan["dimension_adjustment"]
        )
        reverb = adjusted["reverb"]
        assert reverb["size"] < DIMENSION_PROFILES["vocals"]["reverb"]["size"]
        assert reverb["mix"] < DIMENSION_PROFILES["vocals"]["reverb"]["mix"]
        assert reverb["pre_delay_ms"] < 40.0
        assert reverb["return_eq"] == "dark"

    def test_agudo_separates_and_tames_the_wet_layer(self):
        plan = resolve_vocal_treatment("agudo", 300.0)
        adjusted = apply_register_dimension(
            DIMENSION_PROFILES["vocals"], plan["dimension_adjustment"]
        )
        reverb = adjusted["reverb"]
        assert reverb["pre_delay_ms"] == pytest.approx(35.0)
        assert 0.0 < reverb["pre_delay_ms"] < 40.0  # Swedien budget
        assert reverb["return_eq"] == "dark"

    @pytest.mark.parametrize("register", _REGISTER_CLASSES)
    def test_never_leaves_engine_ranges(self, register):
        """Acceptance: for every measured class the adjusted profile stays
        inside ``reverb.py`` validation ranges and the < 40 ms budget."""
        plan = resolve_vocal_treatment(register, 200.0)
        adjusted = apply_register_dimension(
            DIMENSION_PROFILES["vocals"], plan["dimension_adjustment"]
        )
        reverb = adjusted["reverb"]
        assert 0.0 <= reverb["mix"] <= 1.0
        assert 0.1 <= reverb["size"] <= 1.0
        assert 0.0 < reverb["pre_delay_ms"] < 40.0
        assert reverb["return_eq"] in {"bright", "dark", "neutral"}

    def test_clamps_hold_at_the_extremes(self):
        """Out-of-range adjustments clamp instead of saturating; an
        unknown voicing keeps the profile's own value (never crash)."""
        hot = {
            "reverb": {
                "size": 1.0, "mix": 1.0, "pre_delay_ms": 39.0,
                "return_eq": "bright",
            },
            "delay": dict(DIMENSION_PROFILES["vocals"]["delay"]),
        }
        adjusted = apply_register_dimension(
            hot,
            {"size_mult": 9.0, "mix_mult": 9.0, "pre_delay_ms": 120.0,
             "return_eq": "wet"},
        )
        reverb = adjusted["reverb"]
        assert reverb["size"] <= 1.0
        assert reverb["mix"] <= 1.0
        assert reverb["pre_delay_ms"] < 40.0
        assert reverb["return_eq"] == "bright"  # unknown → keep base

    def test_delay_knobs_never_move(self):
        """Register tunes the REVERB knobs only — the tempo delay stays
        the Paso 04 value (genre owns the delay direction)."""
        for register in _REGISTER_CLASSES:
            plan = resolve_vocal_treatment(register, 200.0)
            adjusted = apply_register_dimension(
                DIMENSION_PROFILES["vocals"], plan["dimension_adjustment"]
            )
            assert adjusted["delay"] == DIMENSION_PROFILES["vocals"]["delay"]


# ── T3/T4: build_mix integration + transparency report ─────────────────

class TestBuildMixVocalTreatment:
    """``build_mix(vocal_treatment=...)``: default off = exact previous
    routing; opt-in consumes the motor-B measurement and reports."""

    def test_default_has_no_report_key_and_previous_keys_intact(
        self, tmp_path, monkeypatch,
    ):
        """T4 (master-safe / bypass = neutral): without opting in nothing
        changes — no ``vocal_treatment_report``, Paso 01–07 keys intact."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), pan_profiles={}
        )
        assert "vocal_treatment_report" not in result
        assert "dimension_report" in result
        assert "compressor_report" in result
        assert "emphasis_report" in result
        assert "qc_report" in result
        assert result["eq_profiles_applied"] == {
            name: bands for name, bands in
            __import__(
                "audiomind.processing.magic_frequencies", fromlist=["MAGIC_PROFILES"]
            ).MAGIC_PROFILES.items()
        }
        assert set(result["analysis"]) == set(STEM_NAMES)

    def test_explicit_false_is_also_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, vocal_treatment=False,
        )
        assert "vocal_treatment_report" not in result

    def test_opt_in_consumes_measured_register_and_reports(
        self, tmp_path, monkeypatch,
    ):
        """T1 + T3: a real measured grave voice (110 Hz, pyin) drives the
        chain; the report carries register, f0, the EQ bands actually
        requested, the dimension refinement and the honest ``why``."""
        monkeypatch.setattr(
            mix_engine, "split_audio",
            _split_with_vocals(_harmonic_vocal(110.0)),
        )
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _p: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, vocal_treatment=True, with_versions=False,
            genre="pop", genre_confidence=0.9,
        )
        report = result["vocal_treatment_report"]
        assert report["status"] == "applied"
        assert report["register"] == "grave"
        assert report["median_f0_hz"] is not None
        assert 95.0 <= report["median_f0_hz"] <= 125.0
        assert report["applied"] is True
        assert report["eq_bands"]
        assert report["hypothesis"] is True
        assert "grave" in report["why"]
        assert _HYPO_TOKEN in report["why"]

        # The register refinement REALLY reached the dimension stage —
        # AFTER the genre scaling (pop: mix 0.25→0.35, size 0.85→0.918)
        # and inside the engine ranges.
        assert report["dimension_adjusted"] is True
        assert report["dimension_adjustment"] == REGISTER_DIMENSION_ADJUSTMENTS[
            "grave"
        ]
        reverb = result["dimension_report"]["stems"]["vocals"]["reverb"]
        assert reverb["mix"] == pytest.approx(0.35 * 0.9)
        assert reverb["size"] == pytest.approx(0.85 * 1.08 * 0.8)
        assert reverb["pre_delay_ms"] == pytest.approx(25.0)
        assert reverb["return_eq"] == "dark"
        # Paso 01–07 keys stay intact next to the new key.
        assert "compressor_report" in result
        assert set(result["analysis"]) == set(STEM_NAMES)

    def test_no_credible_voice_stays_neutral(
        self, tmp_path, monkeypatch,
    ):
        """T3: silence in the vocal stem → no invented treatment: neutral
        plan reported, the base dimension voicing untouched."""
        monkeypatch.setattr(
            mix_engine, "split_audio",
            _split_with_vocals(np.zeros(int(_SR * 3.0))),
        )
        monkeypatch.setattr(mix_engine, "_measure_input_bpm", lambda _p: 120.0)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, vocal_treatment=True, with_versions=False,
        )
        report = result["vocal_treatment_report"]
        assert report["status"] == "no_voice"
        assert report["register"] is None
        assert report["applied"] is False
        assert report["eq_bands"] == []
        assert report["dimension_adjusted"] is False
        reverb = result["dimension_report"]["stems"]["vocals"]["reverb"]
        assert reverb["return_eq"] == "bright"   # base preserved
        assert reverb["pre_delay_ms"] == pytest.approx(30.0)

    def test_dimension_disabled_keeps_eq_and_says_so(
        self, tmp_path, monkeypatch,
    ):
        """T3 honest: EQ still applies; the reverb refinement cannot run
        with the dimension stage off and the ``why`` says exactly that."""
        monkeypatch.setattr(
            mix_engine, "split_audio",
            _split_with_vocals(_harmonic_vocal(110.0)),
        )
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"),
            pan_profiles={}, dimension_profiles={}, vocal_treatment=True,
            with_versions=False,
        )
        report = result["vocal_treatment_report"]
        assert report["status"] == "applied"
        assert report["applied"] is True
        assert report["eq_bands"]
        assert report["dimension_adjusted"] is False
        assert "dimensión" in report["why"]
        assert "dimension_report" not in result  # Paso 03 contract intact


def test_api_mix_accepts_the_opt_in(tmp_path, monkeypatch):
    """T3 reachability: POST /mix carries ``vocal_treatment`` through to
    the report (default off keeps the previous payload)."""
    from fastapi.testclient import TestClient

    from audiomind.api.upload import sessions
    from audiomind.main import app
    from audiomind.models.audio import ProcessingStatus, SessionData

    monkeypatch.setattr(
        mix_engine, "split_audio",
        _split_with_vocals(_harmonic_vocal(110.0)),
    )
    client = TestClient(app)
    session_id = str(uuid.uuid4())
    input_path = tmp_path / "input.wav"
    t = np.linspace(0.0, 1.0, _SR, endpoint=False)
    sf.write(str(input_path), 0.25 * np.sin(2.0 * np.pi * 220.0 * t), _SR)
    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(input_path),
        original_filename=input_path.name,
    )

    import json as _json

    resp = client.post(
        f"/api/session/{session_id}/mix", json={"vocal_treatment": True}
    )
    assert resp.status_code == 200, resp.text
    payload = _json.loads(resp.headers["x-mix-result"])
    assert "vocal_treatment_report" in payload
    assert payload["vocal_treatment_report"]["register"] == "grave"
