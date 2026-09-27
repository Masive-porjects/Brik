"""Real tape saturation model (Sprint 7 — hysteresis + level-dependent HF roll-off).

A real tape recorder is NOT a tanh. The Sprint 7 roadmap calls out the three
properties the normalized-tanh stage (``_apply_saturation(..., "tape")``) is
missing: MAGNETIC MEMORY (the reproduced output depends on its own recent
history), LEVEL-DEPENDENT HIGH-FREQUENCY LOSS (short wavelengths saturate on
the tape before long ones do, so loud highs are compressed without turning
harsh) and GENTLE ASYMMETRY (the bias current offsets the operating point,
so even harmonics mix with the tanh's odd ones). This module implements all
three around the roadmap's recursive state shaper.

Shaper — the roadmap hysteresis recursion (soft saturation with memory):

    y[n] = tanh(drive·x[n] + bias + k·y[n−1]·(1 − |y[n−1]|))

where ``drive = 10**(drive_db/20)`` pushes the biased input into the tanh.
The ``k·y[n−1]·(1 − |y[n−1]|)`` term is the hysteretic feedback: it is
strongest mid-swing (|y| = 0.5 gives y·(1−|y|) = 0.25) and vanishes at the
rails (|y| → 1), so the tape "remembers" the recent excursion exactly where
it matters. The feedback is bounded by k/4, the tanh clips it, and the
output is therefore bounded by ±1 for every input — the recursion cannot
blow up. ``hysteresis == 0.0`` disables the recursive term and the shaper
reduces to a plain soft clip.

Asymmetry — the DC ``bias`` (≤ 0.2, "gentle") offsets the operating point
into the tanh, so positive and negative half-cycles compress unequally and
even harmonics (2nd, 4th, …) are added to the tanh's odd set. With
``bias == 0.0`` the shaper is exactly odd (tanh(0) = 0), which is the
roadmap's "pre-emphasis + bias": the HF pre-emphasis of a real tape deck is
deliberately OMITTED here because the level-dependent roll-off below already
covers the HF behavior more directly, and a static pre-emphasis would color
the drive-only path (breaking its "pure drive" identity).

Level-dependent HF roll-off — after the shaper, a static 2nd-order
Butterworth low-pass at ``hf_shelf_hz`` (the roadmap's "progressive
roll-off") is mixed in proportion to a smoothed pre-shaping level:

    level = one-pole peak envelope of |drive·x + bias|          (dB)
    blend = rolloff_amount · clip((level_db − LOW)/(HIGH − LOW), 0, 1)²
    y     = y_sat·(1 − blend) + lowpass(y_sat)·blend

The level is measured on the PRE-shaping flux (drive · input), so a higher
drive means a higher detected level means MORE high-frequency roll-off —
monotonic, level-dependent HF reduction (brightness without harshness).
Below the blend knee the stage is transparent; ``rolloff_amount == 0.0``
disables the mixing entirely.

Neutral mode: with ``drive_db == 0.0``, ``hysteresis == 0.0``,
``bias == 0.0`` and ``rolloff_amount == 0.0`` the stage is a bit-exact no-op
(the recursive shaper can never reproduce the input, so the pass is
skipped). The engine inserts this stage gated by ``params.tape_enabled``
with these defaults, so existing masters pass through unchanged and the
legacy tanh path stays active until the model is engaged.

Acceptance mapping (roadmap): sine spectral analysis → BOTH even (bias
asymmetry) and odd (tanh) harmonics present; frequency response with high
drive shows progressive, monotonic, level-dependent HF roll-off; bypass
null test → bit-exact.

Processing is float64 with per-channel stateful recursion (identical
channels initialize their state identically and stay identical); the input
shape and dtype are preserved. NOTE: the shaper recursion is sample-by-
sample Python (like the legacy ``_apply_saturation``), which is exact but
not fast; a vectorized/Cython pass is a possible follow-up.
"""

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt, sosfreqz

from audiomind.processing.multiband import detect_envelope

#: Upper bound on ``drive_db`` (matches the ``tape_drive_db``
#: MasteringParameters field).
MAX_DRIVE_DB = 24.0
#: Upper bound on the gentle asymmetry ``bias`` (0.0..~0.2 per roadmap).
MAX_BIAS = 0.2
#: Pre-shaping level (dB FS) at which the level-dependent HF roll-off
#: starts engaging (below it the stage is transparent).
ROLLOFF_KNEE_LOW_DB = -2.0
#: Pre-shaping level (dB FS) at which the roll-off blend reaches its full
#: value (above it the blend equals ``rolloff_amount``).
ROLLOFF_KNEE_HIGH_DB = 10.0
#: Exponent sharpening the level-dependence of the roll-off blend: the
#: blend grows quadratically with the detected level, so the difference
#: between a quiet and a loud passage is emphasized (like real tape).
ROLLOFF_POWER = 2.0
#: Order of the static HF low-pass (2nd-order Butterworth = 12 dB/oct —
#: gentle, phase-friendly; a steeper shelf would audibly "ring").
HF_FILTER_ORDER = 2
#: Reference frequency (Hz) for the ``hf_rolloff_db`` diagnostic.
HF_REFERENCE_HZ = 10000.0
#: Detector time constants (ms) for the roll-off level envelope — fast
#: attack so a loud transient engages the HF loss immediately, slow release
#: so the tape "un-magnetizes" back at the signal's own rate.
ROLLOFF_ATTACK_MS = 5.0
ROLLOFF_RELEASE_MS = 200.0
#: Level floor (dB) so silence never produces -inf in the blend mapping.
LEVEL_FLOOR_DB = -120.0


@dataclass(frozen=True)
class TapeParams:
    """Real-tape saturation settings.

    The defaults are NEUTRAL: ``drive_db == 0.0``, ``hysteresis == 0.0``,
    ``bias == 0.0``, ``rolloff_amount == 0.0`` → the stage is a bit-exact
    no-op unless engaged.
    """

    drive_db: float = 0.0
    hysteresis: float = 0.0
    bias: float = 0.0
    rolloff_amount: float = 0.0
    hf_shelf_hz: float = 8000.0

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (all parameters at their
        neutral defaults: no drive, no hysteresis, no bias, no roll-off)."""
        return (
            self.drive_db == 0.0
            and self.hysteresis == 0.0
            and self.bias == 0.0
            and self.rolloff_amount == 0.0
        )


def tape_is_neutral(params: TapeParams) -> bool:
    """Module-level convenience: true when ``params`` is the neutral no-op."""
    return params.is_neutral()


class TapeSaturation:
    """Real tape model: bias → hysteresis shaper → level-dependent HF roll-off.

    Per-channel stateful processing: each channel runs its own recursion and
    level envelope (identical channels initialize their state identically and
    stay identical). In the neutral configuration the input is returned
    untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: TapeParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else TapeParams()
        self._validate()
        self._drive = 10.0 ** (self.params.drive_db / 20.0)
        self._lp_sos = butter(
            HF_FILTER_ORDER,
            self.params.hf_shelf_hz / (self.sr / 2.0),
            btype="lowpass",
            output="sos",
        )
        ref_hz = min(HF_REFERENCE_HZ, 0.9 * self.sr / 2.0)
        _, h = sosfreqz(self._lp_sos, worN=[ref_hz], fs=self.sr)
        self._hf_reference_gain = float(np.abs(h[0]))

    def _validate(self) -> None:
        p = self.params
        if not (np.isfinite(p.drive_db) and 0.0 <= p.drive_db <= MAX_DRIVE_DB):
            raise ValueError(
                f"drive_db must be finite and in [0, {MAX_DRIVE_DB}], got "
                f"drive_db={p.drive_db}"
            )
        if not (0.0 <= p.hysteresis <= 1.0):
            raise ValueError(
                f"hysteresis must be in [0, 1], got hysteresis={p.hysteresis}"
            )
        if not (0.0 <= p.bias <= MAX_BIAS):
            raise ValueError(
                f"bias must be in [0, {MAX_BIAS}], got bias={p.bias}"
            )
        if not (0.0 <= p.rolloff_amount <= 1.0):
            raise ValueError(
                f"rolloff_amount must be in [0, 1], got "
                f"rolloff_amount={p.rolloff_amount}"
            )
        if not (0.0 < p.hf_shelf_hz < self.sr / 2.0):
            raise ValueError(
                f"hf_shelf_hz must satisfy 0 < hf_shelf_hz < sr/2, got "
                f"hf_shelf_hz={p.hf_shelf_hz}, sr={self.sr}"
            )

    def _is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (see ``TapeParams``)."""
        return self.params.is_neutral()

    @staticmethod
    def _shaper_channel(
        x: np.ndarray, drive: float, bias: float, k: float,
    ) -> np.ndarray:
        """Roadmap hysteresis recursion on one channel:
        ``y[n] = tanh(drive·x[n] + bias + k·y[n−1]·(1 − |y[n−1]|))``.

        Runs sample-by-sample so the recursion is exact; the output is
        bounded by ±1 for every input (the tanh clips the feedback too).
        With ``k == 0.0`` the recursive term is structurally absent, so a
        pure-drive stage is exactly ``tanh(drive·x + bias)``.
        """
        y = np.empty_like(x)
        prev = 0.0
        tanh = math.tanh
        if k == 0.0:
            for i in range(x.shape[0]):
                prev = tanh(drive * x[i] + bias)
                y[i] = prev
        else:
            for i in range(x.shape[0]):
                prev = tanh(drive * x[i] + bias + k * prev * (1.0 - abs(prev)))
                y[i] = prev
        return y

    def _rolloff_channel(
        self, y: np.ndarray, pre: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """Level-dependent HF roll-off on one channel.

        The blend grows with the smoothed pre-shaping level (one-pole peak
        envelope of ``|drive·x + bias|``): the louder the tape flux, the more
        the saturated signal is replaced by its low-passed version. Returns
        ``(y, mean_blend)``; with ``rolloff_amount == 0.0`` the mix is
        skipped and ``y`` is returned untouched.
        """
        if self.params.rolloff_amount == 0.0:
            return y, 0.0
        env = detect_envelope(
            np.abs(pre),
            self.sr,
            attack_ms=ROLLOFF_ATTACK_MS,
            release_ms=ROLLOFF_RELEASE_MS,
        )
        level_db = np.maximum(
            20.0 * np.log10(np.maximum(env, 1e-12)), LEVEL_FLOOR_DB
        )
        norm = np.clip(
            (level_db - ROLLOFF_KNEE_LOW_DB)
            / (ROLLOFF_KNEE_HIGH_DB - ROLLOFF_KNEE_LOW_DB),
            0.0,
            1.0,
        )
        blend = self.params.rolloff_amount * norm ** ROLLOFF_POWER
        rolled = sosfilt(self._lp_sos, y, axis=-1)
        return y * (1.0 - blend) + rolled * blend, float(np.mean(blend))

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the tape model, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns stage diagnostics: the
        effective HF roll-off at 10 kHz (dB), the output-peak change (dB,
        positive when drive raises the peak, negative when it is reduced),
        an even-harmonic asymmetry indicator (0 = odd-only symmetric) and
        the mean roll-off blend."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag = {
            "hf_rolloff_db": 0.0,
            "peak_reduction_db": 0.0,
            "asymmetry": 0.0,
            "mean_blend": 0.0,
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # The recursive shaper can never reproduce the input bit-exactly;
            # in the neutral configuration we skip the pass entirely so the
            # neutral path is exactly the input (null test), mirroring the
            # exciter/dyn_eq/multiband shortcut.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)

        outs: list[np.ndarray] = []
        mean_blends: list[float] = []
        asymmetries: list[float] = []
        for ch in range(work.shape[0]):
            y_sat = self._shaper_channel(
                work[ch], self._drive, self.params.bias, self.params.hysteresis
            )
            pre = self._drive * work[ch] + self.params.bias
            out_ch, mean_blend = self._rolloff_channel(y_sat, pre)
            outs.append(out_ch)
            mean_blends.append(mean_blend)
            rms = float(np.sqrt(np.mean(y_sat**2)))
            # |mean|/rms: a symmetric (odd-only) waveform has zero mean, so
            # this is a proxy for the even-harmonic content the bias adds.
            asymmetries.append(
                0.0 if rms == 0.0 else float(np.abs(np.mean(y_sat))) / rms
            )

        out_all = np.stack(outs, axis=0)
        out = out_all.astype(orig_dtype)
        if mono:
            out = out[0]

        peak_in = float(np.max(np.abs(x2)))
        peak_out = float(np.max(np.abs(out_all)))
        peak_reduction_db = (
            0.0
            if peak_in == 0.0
            else float(20.0 * np.log10(peak_out / peak_in))
        )
        mean_blend = float(np.mean(mean_blends))
        # Effective HF gain of the blend: (1−b)·1 + b·|H(f_ref)|, where the
        # dry (unrolled) path has unity HF gain and the rolled path has the
        # low-pass gain at the reference frequency.
        g_hf = (1.0 - mean_blend) + mean_blend * self._hf_reference_gain
        hf_rolloff_db = float(20.0 * np.log10(max(g_hf, 1e-12)))

        diag = {
            "hf_rolloff_db": hf_rolloff_db,
            "peak_reduction_db": peak_reduction_db,
            "asymmetry": float(np.mean(asymmetries)),
            "mean_blend": mean_blend,
        }
        return out, diag


def tape_saturate(
    audio: np.ndarray, sr: int, params: TapeParams | None = None,
) -> np.ndarray:
    """Full real-tape saturation pass (convenience wrapper).

    Neutral by default: with no ``params`` (all neutral defaults) the input
    is returned bit-identical, so the stage is a safe no-op unless engaged.
    """
    return TapeSaturation(sr, params).process(audio)
