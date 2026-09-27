"""Echo (Sprint 10 — cascading repeats that fade, opt-in insert).

The echo is the "musical" sibling of the delay module: the same feedback
delay line, but tuned for cascading repeats that decay into the distance —
a longer default time (400 ms) and a higher feedback ceiling (0.9) so a
full echo tail can ring out (vs. the 250 ms / 0.8 of the tighter delay).
The engine keeps them as separate opt-in modules so each can be engaged
and trimmed independently.

    y[n] = dry·(1 − mix) + wet[n]·mix
    wet[n] = x[n − d] + fb·wet[n − d]        (feedback delay line)

where ``d = round(sr · echo_time_ms / 1000)`` samples. Expanding the
recursion, the wet signal is the geometric series over the delay line's
own history:

    wet[n] = Σ_k fb^(k−1) · x[n − k·d]

As in the delay module, the line is implemented as a CIRCULAR BUFFER in
closed form: each pass through the buffer (lag ``k·d``) is accumulated
directly from the input with weight ``fb^(k−1)``. With ``fb == 0.0`` the
series has exactly one term (single repeat); the tail is truncated once
the repeat gain falls below ``TAP_GAIN_FLOOR`` (−60 dB of the first
repeat), which is inaudible and bounds the cost on long masters.

Neutral mode: ``mix == 0.0`` is a bit-exact no-op (the pass is skipped
and the input returned untouched). The engine inserts this stage gated by
``params.echo_enabled`` with mix-0.0 defaults, so existing masters pass
through unchanged unless the mix moves — even with the stage enabled,
moving ``echo_time_ms``/``echo_feedback`` alone (mix still 0.0) leaves the
signal bit-identical.

Processing is float64, per-channel (identical channels initialize
identical delay lines and stay identical), with input shape and dtype
preserved; mono (1-D) and stereo (channels, samples) are handled like the
tape module.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Lower bound on ``time_ms`` (matches the ``echo_time_ms``
#: MasteringParameters field).
MIN_ECHO_MS = 50.0
#: Upper bound on ``time_ms``.
MAX_ECHO_MS = 2000.0
#: Upper bound on ``feedback`` (matches the ``echo_feedback`` field — the
#: echo's higher ceiling, 0.9 vs the delay's 0.8, allows long fading tails).
MAX_FEEDBACK = 0.9
#: Repeat-gain floor: taps below −60 dB of the first repeat are dropped
#: (musically inaudible and bounded, independent of the audio length).
TAP_GAIN_FLOOR = 1e-3
#: Hard cap on the accumulated taps (safety bound on the geometric tail;
#: reached only for feedback ~0.97+ at the −60 dB floor).
MAX_TAPS = 128


@dataclass(frozen=True)
class EchoParams:
    """Echo settings (cascading repeats).

    The defaults are NEUTRAL: ``mix == 0.0`` makes the stage a bit-exact
    no-op regardless of ``time_ms``/``feedback``, so moving the timing knobs
    alone never changes the signal.
    """

    time_ms: float = 400.0
    mix: float = 0.0
    feedback: float = 0.0

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (``mix == 0.0``: the
        wet path contributes nothing, so the blend is exactly the input)."""
        return self.mix == 0.0


def echo_is_neutral(params: EchoParams) -> bool:
    """Module-level convenience: true when ``params`` is the neutral no-op."""
    return params.is_neutral()


class Echo:
    """Circular-buffer feedback echo with dry/wet mix.

    Each channel runs its own delay line (identical channels initialize
    identical lines and stay identical). In the neutral configuration
    (``mix == 0.0``) the input is returned untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: EchoParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else EchoParams()
        self._validate()

    def _validate(self) -> None:
        p = self.params
        if not (np.isfinite(p.time_ms) and MIN_ECHO_MS <= p.time_ms <= MAX_ECHO_MS):
            raise ValueError(
                f"time_ms must be finite and in [{MIN_ECHO_MS}, "
                f"{MAX_ECHO_MS}], got time_ms={p.time_ms}"
            )
        if not (np.isfinite(p.mix) and 0.0 <= p.mix <= 1.0):
            raise ValueError(
                f"mix must be finite and in [0, 1], got mix={p.mix}"
            )
        if not (np.isfinite(p.feedback) and 0.0 <= p.feedback <= MAX_FEEDBACK):
            raise ValueError(
                f"feedback must be finite and in [0, {MAX_FEEDBACK}], got "
                f"feedback={p.feedback}"
            )

    def _is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (see ``EchoParams``)."""
        return self.params.is_neutral()

    @staticmethod
    def _echo_tail(x: np.ndarray, delay: int, feedback: float) -> np.ndarray:
        """Wet signal of one echo line (circular-buffer recursion, closed
        form): ``wet[n] = Σ_k fb^(k−1)·x[n − k·d]``.

        Each iteration adds one pass through the circular buffer (lag
        ``k·d``) weighted by the accumulated feedback. With ``feedback ==
        0.0`` exactly one tap is added (single repeat); the series is
        truncated when the tap gain drops below ``TAP_GAIN_FLOOR``.
        """
        n = x.shape[0]
        wet = np.zeros_like(x)
        if delay <= 0 or delay >= n:
            return wet
        gain = 1.0
        for k in range(1, MAX_TAPS + 1):
            start = k * delay
            if start >= n:
                break
            wet[start:] += gain * x[: n - start]
            gain *= feedback
            if gain < TAP_GAIN_FLOOR:
                break
        return wet

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the echo, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns stage diagnostics: the wet
        RMS, the effective delay (samples) and the engaged parameters."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag = {
            "wet_rms": 0.0,
            "delay_samples": 0,
            "mix": 0.0,
            "feedback": 0.0,
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # The echo blend can never reproduce the input bit-exactly (the
            # dry path is scaled by (1−mix)); in the neutral configuration
            # we skip the pass entirely so the mix-0.0 path is exactly the
            # input (null test), mirroring the other modules.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)

        delay = max(1, int(round(self.sr * self.params.time_ms / 1000.0)))
        mix = self.params.mix
        feedback = self.params.feedback

        outs: list[np.ndarray] = []
        for ch in range(work.shape[0]):
            wet = self._echo_tail(work[ch], delay, feedback)
            outs.append(work[ch] * (1.0 - mix) + wet * mix)

        out_all = np.stack(outs, axis=0)
        out = out_all.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "wet_rms": float(np.sqrt(np.mean(out_all**2))),
            "delay_samples": delay,
            "mix": mix,
            "feedback": feedback,
        }
        return out, diag


def echo_pass(
    audio: np.ndarray, sr: int, params: EchoParams | None = None,
) -> np.ndarray:
    """Full echo pass (convenience wrapper).

    Neutral by default: with no ``params`` (``mix == 0.0``) the input is
    returned bit-identical, so the stage is a safe no-op unless engaged.
    """
    return Echo(sr, params).process(audio)