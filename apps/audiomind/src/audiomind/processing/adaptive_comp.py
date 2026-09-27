"""Adaptive (program-dependent) compressor (Sprint 8 — threshold tracks RMS,
crest-adaptive timing, sidechain + makeup for the first time).

The fixed −16 dB threshold of the legacy master stage fails on varied
material: a loud, dense master sees little action while a sparse acoustic
performance gets squashed. The Sprint 8 roadmap replaces that static rule
with a PROGRAM-DEPENDENT compressor that adapts three things:

Program-dependent threshold:
    T(t) = RMS_program(t) − offset

  where ``RMS_program`` is a causal sliding-window RMS (the "windowed
  program loudness") and ``offset`` is the calibrated margin BELOW that
  loudness (the legacy proportional compressor's
  ``threshold_db = input_rms_db − 8/ratio`` rule was replaced by this).
  The threshold therefore tracks
  the real dynamics of the material instead of a fixed number, and the
  resulting threshold is clamped to ``[threshold_min_db, threshold_max_db]``
  (roadmap clamp [−30, −4] dB FS). A quiet passage lowers the threshold with
  it, so a soft section is compressed gently while a loud section still gets
  controlled.

Adaptive attack/release (crest-adaptive timing):
    C(t) = 20·log10(peak_env(t) / rms_env(t))
    attack_ms(t)  = clip(base_attack  · (crest_ref / max(C, floor))^exp, ...)
    release_ms(t) = clip(base_release · (crest_ref / max(C, floor))^exp, ...)

  The crest factor is measured on the same detector paths used everywhere in
  this family: a fast one-pole PEAK envelope (``detect_envelope`` from the
  multiband module, 5 ms attack) over a causal sliding-window RMS of
  ``crest_window_ms``. HIGH crest (percussion, drums) maps to a SHORT attack
  so the transient is caught immediately; LOW crest (tails, pads) maps to a
  LONG attack and release so the compressor "breathes" without pumping.

Sidechain + makeup:
  The detector may be fed an external ``sidechain`` signal (optional
  argument); the gain curve is then applied to the PROGRAM audio while the
  detector follows the sidechain — the first sidechain in the chain. The
  engine currently passes the program itself (internal sidechain mode), but
  the module accepts any external signal. ``makeup_db`` (also a first) is
  applied as a constant linear gain ONLY on the active path, so it can never
  break the null test.

Gain computer — standard downward compression:
    G(t) = min(0, (1 − 1/ratio)·(level_db(t) − T(t)))
  where ``level_db`` is the FAST peak-ish detector and ``T(t)`` the slow
  program-adaptive threshold: a transient that peaks far above the
  program's own RMS-based threshold (i.e. high crest) generates more gain
  reduction — GR matches the program crest. The raw GR is smoothed
  sample-by-sample with the adaptive attack/release one-pole (asymmetric:
  falling GR uses the attack coefficient, recovering GR uses release).

Neutral mode: with ``ratio == 1.0`` the stage is a bit-exact no-op (the
input is returned untouched — the adaptive timing and threshold are never
computed). The engine inserts this stage gated by
``params.adaptive_comp_enabled`` with ratio-1.0 defaults, so existing
masters pass through the fixed compressor unchanged until the adaptive
module is engaged.

Acceptance mapping (roadmap): threshold tracks input RMS (diagnostics
``threshold_db`` follows the program loudness); GR matches program crest
(high-crest material reaches its gain reduction faster and further);
bypass null test → bit-exact.

Processing is float64; stereo uses a joint (L+R)/2 detector so both
channels receive the same per-frame gain and the image is preserved
(identical channels stay identical). Input shape and dtype are preserved.
"""

import math
from dataclasses import dataclass

import numpy as np
from typing import Any

from audiomind.processing.multiband import detect_envelope

#: Typical crest factor (dB) of mastered music; used as the reference in the
#: crest→timing mapping (crest above this → faster, below → slower).
CREST_REF_DB = 12.0
#: Exponent of the crest→timing law (1.0 = inversely proportional to crest).
CREST_EXP = 1.0
#: Crest floor (dB) so silence never produces a huge ratio or a divide-by-zero.
CREST_FLOOR_DB = 1.0
#: Clamp factors for the adaptive attack time (multiples of the base attack).
ATTACK_MIN_FACTOR = 0.25
ATTACK_MAX_FACTOR = 4.0
#: Clamp factors for the adaptive release time (multiples of the base release).
RELEASE_MIN_FACTOR = 0.25
RELEASE_MAX_FACTOR = 2.0
#: Peak-detector time constants (ms) for the fast crest/level envelope.
PEAK_ATTACK_MS = 5.0
#: Level floor (dB) so silence never produces -inf in the dB conversions.
LEVEL_FLOOR_DB = -120.0
#: Small absolute floor for the RMS window so silence never divides by zero.
RMS_FLOOR = 1e-12


@dataclass(frozen=True)
class AdaptiveCompParams:
    """Program-dependent compressor settings.

    ``threshold_offset_db`` is the margin BELOW the program's windowed RMS at
    which the threshold sits (dead-code semantics: the original used
    ``input_rms_db − 8/ratio``), so a positive offset means the threshold
    follows ``rms_db − offset``. The defaults are NEUTRAL: ``ratio == 1.0``
    makes the stage a bit-exact no-op regardless of the other knobs.
    """

    threshold_offset_db: float = 6.0
    threshold_min_db: float = -30.0
    threshold_max_db: float = -4.0
    ratio: float = 1.0
    attack_ms: float = 10.0
    release_ms: float = 200.0
    crest_window_ms: float = 100.0
    makeup_db: float = 0.0

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (ratio 1:1)."""
        return self.ratio <= 1.0


class AdaptiveCompressor:
    """Program-dependent compressor: windowed-RMS threshold + crest timing.

    The detector runs on the joint (L+R)/2 mix (or on the sidechain when one
    is supplied) so both channels share the same gain trajectory. In the
    neutral configuration (ratio 1.0) the input is returned untouched,
    bit-exactly.
    """

    def __init__(self, sr: int, params: AdaptiveCompParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else AdaptiveCompParams()
        self._validate()
        self._window = max(1, int(self.params.crest_window_ms * self.sr / 1000.0))

    def _validate(self) -> None:
        p = self.params
        if p.ratio < 1.0:
            raise ValueError(f"ratio must be >= 1.0, got ratio={p.ratio}")
        if not (p.attack_ms > 0.0):
            raise ValueError(f"attack_ms must be > 0, got attack_ms={p.attack_ms}")
        if not (p.release_ms > 0.0):
            raise ValueError(f"release_ms must be > 0, got release_ms={p.release_ms}")
        if not (p.crest_window_ms > 0.0):
            raise ValueError(
                f"crest_window_ms must be > 0, got crest_window_ms={p.crest_window_ms}"
            )
        if not (np.isfinite(p.threshold_offset_db) and p.threshold_offset_db > 0.0):
            raise ValueError(
                f"threshold_offset_db must be finite and > 0, got "
                f"threshold_offset_db={p.threshold_offset_db}"
            )
        if not (p.threshold_min_db < p.threshold_max_db):
            raise ValueError(
                f"threshold_min_db must be < threshold_max_db, got "
                f"min={p.threshold_min_db}, max={p.threshold_max_db}"
            )
        if not (np.isfinite(p.makeup_db) and p.makeup_db >= 0.0):
            raise ValueError(
                f"makeup_db must be finite and >= 0, got makeup_db={p.makeup_db}"
            )

    def _is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (see ``AdaptiveCompParams``)."""
        return self.params.is_neutral()

    @staticmethod
    def _windowed_rms_db(x: np.ndarray, window: int, sr: int) -> np.ndarray:
        """Causal sliding-window RMS (dB) of one channel.

        ``rms[n] = sqrt(mean(x[i]² for i in max(0, n−w+1)..n))`` via a
        cumulative sum — exact, vectorized, and causal (no lookahead), so the
        threshold can only react to what the compressor has already heard.
        """
        n = x.shape[0]
        x2 = x.astype(np.float64) ** 2
        cum = np.concatenate([[0.0], np.cumsum(x2)])
        idx = np.arange(1, n + 1)
        sums = cum[idx] - cum[np.maximum(idx - window, 0)]
        denom = np.minimum(idx, window)
        rms = np.sqrt(np.maximum(sums / denom, RMS_FLOOR))
        return np.asarray(np.maximum(20.0 * np.log10(rms), LEVEL_FLOOR_DB))

    def _detector_paths(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute (rms_db, peak_env_db, crest_db) for the detector signal.

        ``rms_db`` is the causal windowed RMS (program loudness → threshold).
        ``peak_env_db`` is the fast one-pole peak envelope (transient level →
        gain computer). ``crest_db`` is ``20·log10(peak/rms)`` (→ adaptive
        attack/release).
        """
        rms_db = self._windowed_rms_db(x, self._window, self.sr)
        peak_env = detect_envelope(
            np.abs(x),
            self.sr,
            attack_ms=PEAK_ATTACK_MS,
            release_ms=self.params.crest_window_ms,
        )
        peak_env_db = np.maximum(
            20.0 * np.log10(np.maximum(peak_env, 1e-12)), LEVEL_FLOOR_DB
        )
        crest_db = np.maximum(peak_env_db - rms_db, CREST_FLOOR_DB)
        return rms_db, peak_env_db, crest_db

    def _timing_from_crest(self, crest_db: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Map the crest factor onto per-frame attack/release times (ms)."""
        c = np.maximum(crest_db, CREST_FLOOR_DB)
        k = (CREST_REF_DB / c) ** CREST_EXP
        p = self.params
        attack = np.clip(
            p.attack_ms * k,
            p.attack_ms * ATTACK_MIN_FACTOR,
            p.attack_ms * ATTACK_MAX_FACTOR,
        )
        release = np.clip(
            p.release_ms * k,
            p.release_ms * RELEASE_MIN_FACTOR,
            p.release_ms * RELEASE_MAX_FACTOR,
        )
        return attack, release

    @staticmethod
    def _smooth_gr(
        gr_raw: np.ndarray, attack_ms: np.ndarray, release_ms: np.ndarray, sr: int,
    ) -> np.ndarray:
        """Sample-by-sample asymmetric one-pole smoothing of the gain reduction.

        Falling GR (more reduction) uses the (adaptive) attack coefficient;
        recovering GR uses the release coefficient — the classic compressor
        ballistics, with time constants that follow the program crest.
        """
        tau_a = np.maximum(attack_ms, 0.0) / 1000.0
        tau_r = np.maximum(release_ms, 0.0) / 1000.0
        alpha_a = np.exp(-1.0 / np.maximum(tau_a * float(sr), 1e-9))
        alpha_r = np.exp(-1.0 / np.maximum(tau_r * float(sr), 1e-9))
        gr = np.empty_like(gr_raw)
        prev = 0.0
        for i in range(gr_raw.shape[0]):
            alpha = alpha_a[i] if gr_raw[i] < prev else alpha_r[i]
            prev = alpha * prev + (1.0 - alpha) * gr_raw[i]
            gr[i] = prev
        return gr

    def process(
        self, audio: np.ndarray, sidechain: np.ndarray | None = None,
    ) -> np.ndarray:
        """Apply the adaptive compressor, returning audio with input shape/dtype."""
        out, _ = self._process(audio, sidechain)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray, sidechain: np.ndarray | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns per-frame diagnostics:
        ``gr_db`` (smoothed gain reduction), ``threshold_db``, ``crest_db``,
        ``attack_ms``/``release_ms`` trajectories and their scalar summaries."""
        return self._process(audio, sidechain)

    def _process(
        self, audio: np.ndarray, sidechain: np.ndarray | None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag = {
            "gr_db": np.zeros(0),
            "mean_gr_db": 0.0,
            "max_gr_db": 0.0,
            "threshold_db": np.zeros(0),
            "mean_threshold_db": 0.0,
            "min_threshold_db": 0.0,
            "max_threshold_db": 0.0,
            "crest_db": np.zeros(0),
            "mean_crest_db": 0.0,
            "attack_ms": np.zeros(0),
            "release_ms": np.zeros(0),
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # The compressor gain path can never reproduce the input
            # bit-exactly; in the neutral configuration we skip it entirely
            # so the ratio-1.0 path is exactly the input (null test).
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)

        # Detector: program or external sidechain, collapsed to joint (L+R)/2.
        det_src = work if sidechain is None else np.asarray(sidechain)
        if det_src.ndim == 1:
            det = det_src
        else:
            det = det_src.mean(axis=0)
        det = det.astype(np.float64)

        rms_db, peak_db, crest_db = self._detector_paths(det)
        threshold_db = np.clip(
            rms_db - self.params.threshold_offset_db,
            self.params.threshold_min_db,
            self.params.threshold_max_db,
        )

        # Gain computer: GR = min(0, (1 − 1/ratio)·(T − level)).  When the
        # fast peak level sits ABOVE the program-adaptive threshold the
        # compressor reduces gain; the deeper the peak crosses the threshold
        # (high crest), the more reduction — GR matches the program crest.
        gr_raw = np.minimum(
            0.0, (1.0 - 1.0 / self.params.ratio) * (threshold_db - peak_db)
        )
        attack, release = self._timing_from_crest(crest_db)
        gr_db = self._smooth_gr(gr_raw, attack, release, self.sr)

        gain = 10.0 ** ((gr_db + self.params.makeup_db) / 20.0)
        y = work * gain[np.newaxis, :]
        out = y.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "gr_db": gr_db,
            "mean_gr_db": float(np.mean(gr_db)),
            "max_gr_db": float(np.min(gr_db)),
            "threshold_db": threshold_db,
            "mean_threshold_db": float(np.mean(threshold_db)),
            "min_threshold_db": float(np.min(threshold_db)),
            "max_threshold_db": float(np.max(threshold_db)),
            "crest_db": crest_db,
            "mean_crest_db": float(np.mean(crest_db)),
            "attack_ms": attack,
            "release_ms": release,
        }
        return out, diag


def adaptive_compress(
    audio: np.ndarray, sr: int, params: AdaptiveCompParams | None = None,
    sidechain: np.ndarray | None = None,
) -> np.ndarray:
    """Full adaptive-compression pass (convenience wrapper).

    Neutral by default: with no ``params`` (ratio 1.0) the input is returned
    bit-identical, so the stage is a safe no-op unless engaged. Pass
    ``sidechain`` to drive the detector from another signal.
    """
    return AdaptiveCompressor(sr, params).process(audio, sidechain)
