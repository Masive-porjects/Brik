"""Schroeder reverb (Sprint 10 — 4 comb + 2 allpass, opt-in insert).

The classic Schroeder reverberator models a room as a bank of parallel
feedback delay lines (the "comb" filters, which create the distinct early
echo density of a reflective space) followed by two cascaded all-pass
filters (which smear those echoes into a dense, colorless tail). Both
building blocks are feedback delay lines over the same circular-buffer
primitive the delay/echo modules use:

    comb(x, d, g)[n]  = Σ_k g^(k−1) · x[n − k·d]          (delayed tail)
    allpass(x, d, g)  = −g·x[n] + (1 − g²) · Σ_k g^(k−1)·x[n − k·d]

The all-pass keeps the magnitude response flat while dispersing phase, so
the tail loses the metallic "ring" of the combs alone. ``reverb_size``
scales the comb feedback ``g`` linearly from 0.45 (small room, short
decay) to 0.9 (huge hall, ~1.7 s tail at 30 ms comb delays):

    g = 0.4 + 0.5 · size        (size ∈ [0.1, 1.0])

The four combs use the classic Freeverb tuning (25.3 / 26.9 / 29.0 / 30.7
ms, scaled by the sample rate) and are summed and normalized (× (1−g)/4)
so the comb bus has unity DC gain; the two all-passes (12.6 ms then 10.0
ms, gain 0.5) run in series. The wet/dry balance is set by ``mix``:

    y[n] = dry·(1 − mix) + wet[n]·mix

The tap series of every comb/all-pass is truncated below ``TAP_GAIN_FLOOR``
(−60 dB of the first tap), which is inaudible and bounds the cost on long
masters.

Neutral mode: ``mix == 0.0`` is a bit-exact no-op (the pass is skipped and
the input returned untouched). The engine inserts this stage gated by
``params.reverb_enabled`` with mix-0.0 defaults, so existing masters pass
through unchanged unless the mix moves — even with the stage enabled,
moving ``reverb_size`` alone (mix still 0.0) leaves the signal
bit-identical.

Processing is float64, per-channel (identical channels stay identical),
with input shape and dtype preserved; mono (1-D) and stereo (channels,
samples) are handled like the tape module.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Comb-filter delay times in ms (Freeverb tuning: 1116/1188/1277/1356
#: samples at 44.1 kHz), scaled by the sample rate. Distinct prime-ish
#: values keep the comb resonances spaced so they do not stack.
COMB_DELAYS_MS = (25.3, 26.9, 29.0, 30.7)
#: All-pass delay times in ms (Freeverb tuning: 556/441 samples at
#: 44.1 kHz), scaled by the sample rate.
ALLPASS_DELAYS_MS = (12.6, 10.0)
#: All-pass feedback gain (Schroeder's classic 0.5, magnitude-flat).
ALLPASS_GAIN = 0.5
#: Comb feedback at ``size == 0.1`` (small room, short decay).
COMB_GAIN_MIN = 0.4
#: Comb feedback slope per unit ``size``: ``g = COMB_GAIN_MIN + SPAN·size``
#: reaches 0.9 at ``size == 1.0`` (huge hall, ~1.7 s tail).
COMB_GAIN_SPAN = 0.5
#: Tap-gain floor: series terms below −60 dB of the first tap are dropped
#: (musically inaudible and bounded, independent of the audio length).
TAP_GAIN_FLOOR = 1e-3
#: Hard cap on the accumulated taps (safety bound on the geometric tail;
#: reached only for feedback ~0.97+ at the −60 dB floor).
MAX_TAPS = 128


@dataclass(frozen=True)
class ReverbParams:
    """Schroeder reverb settings.

    The defaults are NEUTRAL: ``mix == 0.0`` makes the stage a bit-exact
    no-op regardless of ``size``, so moving the room-size knob alone never
    changes the signal.
    """

    mix: float = 0.0
    size: float = 0.5

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (``mix == 0.0``: the
        wet path contributes nothing, so the blend is exactly the input)."""
        return self.mix == 0.0


def reverb_is_neutral(params: ReverbParams) -> bool:
    """Module-level convenience: true when ``params`` is the neutral no-op."""
    return params.is_neutral()


class Reverb:
    """Schroeder reverb: 4 parallel combs → 2 cascaded all-passes → mix.

    Each channel runs its own filter bank (identical channels stay
    identical). In the neutral configuration (``mix == 0.0``) the input is
    returned untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: ReverbParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else ReverbParams()
        self._validate()

    def _validate(self) -> None:
        p = self.params
        if not (np.isfinite(p.mix) and 0.0 <= p.mix <= 1.0):
            raise ValueError(
                f"mix must be finite and in [0, 1], got mix={p.mix}"
            )
        if not (np.isfinite(p.size) and 0.1 <= p.size <= 1.0):
            raise ValueError(
                f"size must be finite and in [0.1, 1.0], got size={p.size}"
            )

    def _is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (see ``ReverbParams``)."""
        return self.params.is_neutral()

    @staticmethod
    def _feedback_tail(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
        """Delayed tail of one feedback delay line (circular-buffer
        recursion, closed form): ``tail[n] = Σ_k g^(k−1)·x[n − k·d]``.

        This is the shared primitive of the comb filters and the all-pass
        dispersion stage. The series is truncated when the tap gain drops
        below ``TAP_GAIN_FLOOR``.
        """
        n = x.shape[0]
        tail = np.zeros_like(x)
        if delay <= 0 or delay >= n:
            return tail
        tap_gain = 1.0
        for k in range(1, MAX_TAPS + 1):
            start = k * delay
            if start >= n:
                break
            tail[start:] += tap_gain * x[: n - start]
            tap_gain *= gain
            if tap_gain < TAP_GAIN_FLOOR:
                break
        return tail

    @classmethod
    def _allpass(
        cls, x: np.ndarray, delay: int, gain: float,
    ) -> np.ndarray:
        """Magnitude-flat all-pass: ``y = −g·x + (1 − g²)·tail(x, d, g)``.

        The cascade of two of these disperses the comb echoes into a dense,
        colorless tail while preserving the spectral balance.
        """
        return -gain * x + (1.0 - gain * gain) * cls._feedback_tail(
            x, delay, gain
        )

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the reverb, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns stage diagnostics: the wet
        RMS, the effective comb feedback gain and the engaged size."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag = {
            "wet_rms": 0.0,
            "comb_gain": 0.0,
            "size": 0.0,
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # The reverb blend can never reproduce the input bit-exactly
            # (the dry path is scaled by (1−mix)); in the neutral
            # configuration we skip the pass entirely so the mix-0.0 path is
            # exactly the input (null test), mirroring the other modules.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)

        comb_gain = COMB_GAIN_MIN + COMB_GAIN_SPAN * self.params.size
        comb_delays = tuple(
            max(1, int(round(self.sr * ms / 1000.0))) for ms in COMB_DELAYS_MS
        )
        ap_delays = tuple(
            max(1, int(round(self.sr * ms / 1000.0))) for ms in ALLPASS_DELAYS_MS
        )
        mix = self.params.mix

        outs: list[np.ndarray] = []
        for ch in range(work.shape[0]):
            # Sum of the 4 parallel combs, normalized so the comb bus has
            # unity DC gain (each comb's tail has DC gain 1/(1−g), so
            # × (1−g)/4 makes the average combs sum to unity). The combs
            # set the echo density; the all-passes smear them into a tail.
            comb = np.zeros_like(work[ch])
            for d in comb_delays:
                comb += (
                    self._feedback_tail(work[ch], d, comb_gain)
                    * (1.0 - comb_gain)
                    / 4.0
                )
            ap1 = self._allpass(comb, ap_delays[0], ALLPASS_GAIN)
            wet = self._allpass(ap1, ap_delays[1], ALLPASS_GAIN)
            outs.append(work[ch] * (1.0 - mix) + wet * mix)

        out_all = np.stack(outs, axis=0)
        out = out_all.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "wet_rms": float(np.sqrt(np.mean(out_all**2))),
            "comb_gain": comb_gain,
            "size": self.params.size,
        }
        return out, diag


def reverb_pass(
    audio: np.ndarray, sr: int, params: ReverbParams | None = None,
) -> np.ndarray:
    """Full Schroeder-reverb pass (convenience wrapper).

    Neutral by default: with no ``params`` (``mix == 0.0``) the input is
    returned bit-identical, so the stage is a safe no-op unless engaged.
    """
    return Reverb(sr, params).process(audio)