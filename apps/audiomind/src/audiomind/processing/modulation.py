"""Fractional delay line, and the LFO effects built on it (wow, flutter, chorus).

A tape machine does not hold its speed. The pitch drifts slowly (wow) and shivers
quickly (flutter), and the character that makes a pad sound like a recording
rather than a patch comes from that drift. This module produces it by moving the
delay tap instead of modulating a pitch shifter: the signal is read from a
slightly different place in its own past, which is what the physical process
actually does.

THE NEUTRAL INVARIANT
---------------------
``depth_ms == 0`` returns a copy of the input, bit-identical, for both effects.
This is the repo's ``Neutral = bypass`` rule, and it is worth spelling out why it
is not simply "a delay of zero": an engaged wow/flutter stage adds
``base_delay_ms`` of latency, because that is the tape's head spacing. A caller
who sets the depth to zero is asking for the effect OFF, not for a delay they did
not request. On a stem processor an unengaged stage that still shifted its stem by
2 ms would smear the mix against its neighbours while reporting itself as neutral.

The chorus is neutral at ``depth_ms == 0`` **or** ``mix == 0``. A static delay
summed with dry is a comb filter, not a chorus, and shipping a comb nobody asked
for is the same defect as shipping a shift.

INTERPOLATION, and what it costs
--------------------------------
The tap is fractional, so it is interpolated. Cubic (4-point Catmull-Rom) is the
default: at 1 kHz with a 3.3-sample delay it loses 0.0024 dB against linear's
0.0757 dB, and the suite pins that gap so the assertion cannot pass for the wrong
interpolator.

Measured and disclosed: the interpolator droops at the top of the band. At 8 kHz
with a 0.3-sample delay, linear loses 5.134 dB and cubic 2.549 dB. This is a
character stage, not a transparent one, and the honest way to ship a droop is to
write it down rather than let someone discover it on a hi-hat.

Exactness is structural, not arithmetic. A zero delay and every all-integer delay
take a direct-index path, so the interpolator never runs on a signal it does not
have to move. Relying on ``t=0`` arithmetic to be exact would have been a bet on
float rounding, and bets like that fail silently on one machine in a thousand.

WHY FLUTTER IS WEIGHTED BY FREQUENCY
------------------------------------
Instantaneous pitch deviation is proportional to depth **times rate**, not to
depth. With a raw depth share of 0.3, flutter at 7.5 Hz against wow at 0.8 Hz
measured a deviation 2.8 times wow's — the fast shiver dominating the slow drift,
which is the opposite of what the names mean. The flutter contribution is
therefore weighted by ``wow_hz/flutter_hz``, which makes ``flutter_share`` mean
exactly "flutter's share of the pitch deviation", and the suite pins the resulting
ratio at 0.3000 and 0.5000.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

#: Depth ceiling for wow/flutter. Tape wow is a fraction of a percent of speed,
#: so this is generous; past it the effect stops being drift and becomes vibrato.
MAX_DEPTH_MS: Final[float] = 2.0
#: Ceiling on any base delay. Keeps the delay line's memory proportional to a
#: musical pre-delay instead of to whatever a caller typed.
MAX_BASE_DELAY_MS: Final[float] = 20.0
#: Wow: one slow drift per this many seconds. Flutter: the fast shiver.
WOW_HZ: Final[float] = 0.8
FLUTTER_HZ: Final[float] = 7.5
#: Flutter's share of the PITCH DEVIATION. See the module docstring.
FLUTTER_SHARE: Final[float] = 0.3
#: Default head spacing when the stage is engaged.
BASE_DELAY_MS: Final[float] = 2.0
#: Chorus: a longer static offset (that is the doubling) with a shorter swing.
CHORUS_MAX_DEPTH_MS: Final[float] = 8.0
CHORUS_BASE_DELAY_MS: Final[float] = 15.0
CHORUS_RATE_HZ: Final[float] = 0.6


def _gather(channels: np.ndarray, indices: np.ndarray, n_samples: int) -> np.ndarray:
    """Read ``channels`` at integer ``indices``, zero where outside the buffer.

    Silence is the only honest value for material that is not there. Clamping an
    out-of-range tap onto the first or last sample would fold program material
    into a place it never occurred.
    """
    valid = (indices >= 0) & (indices < n_samples)
    out = np.zeros((channels.shape[0], n_samples), dtype=np.float64)
    if valid.any():
        out[:, valid] = channels[:, indices[valid]]
    return out


def fractional_delay(
    audio: np.ndarray,
    delays_samples: np.ndarray,
    *,
    cubic: bool = True,
) -> np.ndarray:
    """Read ``audio`` at a per-sample, fractional delay.

    ``delays_samples[n]`` is the delay applied to output sample ``n``, in samples
    and ``>= 0``: values are read from the past, so a delay of ``d`` at sample
    ``n`` reads the input around ``n - d``.

    Zero delays and all-integer delays take a direct-index path, so those calls
    never run the interpolator and cannot introduce a rounding error into a signal
    that was not moved. Only a genuinely fractional tap is interpolated.

    Accepts ``(n,)`` or ``(channels, n)`` and returns the same shape, cast back to
    the input dtype. A negative delay and a delay/audio length mismatch raise.
    """
    arr = np.asarray(audio)
    delays = np.asarray(delays_samples, dtype=np.float64)
    if delays.ndim != 1:
        raise ValueError(f"delays_samples must be 1-D, got shape {delays.shape}")

    mono = arr.ndim == 1
    channels = arr[np.newaxis, :] if mono else arr
    n_samples = channels.shape[-1]
    if delays.size != n_samples:
        raise ValueError(
            f"delays_samples length {delays.size} does not match audio length "
            f"{n_samples}"
        )
    if n_samples == 0:
        return arr.copy()
    if float(np.min(delays)) < 0.0:
        raise ValueError(
            "delays_samples must be >= 0 (a negative delay reads the future), got "
            f"min={float(np.min(delays))}"
        )

    work = channels.astype(np.float64)
    positions = np.arange(n_samples, dtype=np.float64) - delays

    if bool(np.all(delays == np.round(delays))):
        taps = _gather(work, positions.astype(np.int64), n_samples)
    else:
        base = np.floor(positions).astype(np.int64)
        fraction = positions - base
        if cubic:
            p0 = _gather(work, base - 1, n_samples)
            p1 = _gather(work, base, n_samples)
            p2 = _gather(work, base + 1, n_samples)
            p3 = _gather(work, base + 2, n_samples)
            taps = 0.5 * (
                2.0 * p1
                + (-p0 + p2) * fraction
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * fraction**2
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * fraction**3
            )
        else:
            taps = (1.0 - fraction) * _gather(
                work, base, n_samples
            ) + fraction * _gather(work, base + 1, n_samples)

    out = taps.astype(arr.dtype)
    return out[0] if mono else out


def _validate_depth_and_base(
    depth_ms: float, base_delay_ms: float, max_depth_ms: float
) -> None:
    """The tap bound first, then the two ceilings.

    ``base_delay_ms >= depth_ms`` is checked before the ranges because it is the
    bound that keeps the tap inside the buffer: at 5 ms of depth on a 4 ms base
    the tap measured -22.03 samples, which reads as silence, which reads as
    dropouts the caller never asked for.
    """
    if not (
        np.isfinite(base_delay_ms)
        and np.isfinite(depth_ms)
        and base_delay_ms >= depth_ms
    ):
        raise ValueError(
            "base_delay_ms must be finite and >= depth_ms, got "
            f"base_delay_ms={base_delay_ms}, depth_ms={depth_ms}"
        )
    if not (0.0 <= depth_ms <= max_depth_ms):
        raise ValueError(
            f"depth_ms must be in [0, {max_depth_ms}], got depth_ms={depth_ms}"
        )
    if not (0.0 <= base_delay_ms <= MAX_BASE_DELAY_MS):
        raise ValueError(
            f"base_delay_ms must be in [0, {MAX_BASE_DELAY_MS}], got "
            f"base_delay_ms={base_delay_ms}"
        )


@dataclass(frozen=True)
class WowFlutterParams:
    """Wow/flutter settings.

    The defaults are NEUTRAL: ``depth_ms == 0.0`` makes the stage a bit-exact
    no-op regardless of ``base_delay_ms``, so moving the head spacing alone never
    shifts the signal.
    """

    depth_ms: float = 0.0
    base_delay_ms: float = BASE_DELAY_MS
    wow_hz: float = WOW_HZ
    flutter_hz: float = FLUTTER_HZ
    flutter_share: float = FLUTTER_SHARE

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op.

        ``depth_ms == 0.0`` means the transport is steady, so there is no drift
        to apply and no reason to hold the signal back by the head spacing.
        """
        return self.depth_ms == 0.0


def wow_flutter_is_neutral(params: WowFlutterParams) -> bool:
    """Module-level convenience: true when ``params`` is the neutral no-op."""
    return params.is_neutral()


def wow_flutter_delays(n_samples: int, sr: int, params: WowFlutterParams) -> np.ndarray:
    """The wow/flutter delay trajectory, in samples, for a render of ``n_samples``.

    Public on purpose. The caller needs it to know the latency it is about to
    align, and the suite needs it to check the tap bound and the flutter weighting
    against the trajectory itself instead of against a private copy of the maths.
    """
    times = np.arange(max(n_samples, 0), dtype=np.float64) / sr
    wow = np.sin(2.0 * np.pi * params.wow_hz * times)
    flutter = np.sin(2.0 * np.pi * params.flutter_hz * times)
    weight = params.flutter_share * (params.wow_hz / params.flutter_hz)
    combined = (wow + weight * flutter) / (1.0 + weight)
    return (params.base_delay_ms + combined * params.depth_ms) * sr / 1000.0


class WowFlutter:
    """Wow and flutter: the pitch drift of a tape transport.

    Engaged, the signal is returned read through a modulated delay and fully wet —
    this is a speed variation of the signal itself, not an effect summed with it.
    In the neutral configuration the input is returned untouched, bit-exactly.

    One note for whoever mixes the result back in: engaged, this stage adds
    ``base_delay_ms`` of latency. That is the head spacing, and it is why the
    neutral state is a bypass rather than a zero-depth delay.
    """

    def __init__(self, sr: int, params: WowFlutterParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else WowFlutterParams()
        self._validate()

    def _validate(self) -> None:
        p = self.params
        _validate_depth_and_base(p.depth_ms, p.base_delay_ms, MAX_DEPTH_MS)
        if not (np.isfinite(p.wow_hz) and p.wow_hz > 0.0):
            raise ValueError(f"wow_hz must be finite and > 0, got wow_hz={p.wow_hz}")
        if not (np.isfinite(p.flutter_hz) and p.flutter_hz > 0.0):
            raise ValueError(
                f"flutter_hz must be finite and > 0, got flutter_hz={p.flutter_hz}"
            )
        if not (np.isfinite(p.flutter_share) and 0.0 <= p.flutter_share <= 1.0):
            raise ValueError(
                "flutter_share must be finite and in [0, 1], got "
                f"flutter_share={p.flutter_share}"
            )

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the wow/flutter, returning audio with input shape and dtype."""
        arr = np.asarray(audio)
        if self.params.is_neutral():
            return arr.copy()
        return fractional_delay(
            arr, wow_flutter_delays(arr.shape[-1], self.sr, self.params)
        )


def wow_flutter_pass(
    audio: np.ndarray, sr: int, params: WowFlutterParams | None = None
) -> np.ndarray:
    """Full wow/flutter pass (convenience wrapper).

    Neutral by default: with no ``params`` the input is returned bit-identical, so
    the stage is a safe no-op unless engaged.
    """
    return WowFlutter(sr, params).process(audio)


@dataclass(frozen=True)
class ChorusParams:
    """Chorus settings.

    The defaults are NEUTRAL: either ``depth_ms == 0.0`` or ``mix == 0.0`` makes
    the stage a bit-exact no-op.
    """

    depth_ms: float = 0.0
    base_delay_ms: float = CHORUS_BASE_DELAY_MS
    rate_hz: float = CHORUS_RATE_HZ
    mix: float = 0.0

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op.

        A static delay summed with dry is a comb filter, not a chorus, so a zero
        depth is neutral even with the mix up.
        """
        return self.depth_ms == 0.0 or self.mix == 0.0


def chorus_is_neutral(params: ChorusParams) -> bool:
    """Module-level convenience: true when ``params`` is the neutral no-op."""
    return params.is_neutral()


def chorus_delays(n_samples: int, sr: int, params: ChorusParams) -> np.ndarray:
    """The chorus delay trajectory, in samples, for a render of ``n_samples``."""
    times = np.arange(max(n_samples, 0), dtype=np.float64) / sr
    lfo = np.sin(2.0 * np.pi * params.rate_hz * times)
    return (params.base_delay_ms + lfo * params.depth_ms) * sr / 1000.0


class Chorus:
    """LFO-modulated delay summed with the dry signal.

    Engaged, this is a doubling whose delay moves, so the comb it forms sweeps
    instead of ringing on one frequency. Note that the mixture cancels as much as
    it adds: at ``mix=0.5`` the output measured 3.4 dB below the input, which is
    the comb doing its job and not a level bug.
    """

    def __init__(self, sr: int, params: ChorusParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else ChorusParams()
        self._validate()

    def _validate(self) -> None:
        p = self.params
        _validate_depth_and_base(p.depth_ms, p.base_delay_ms, CHORUS_MAX_DEPTH_MS)
        if not (np.isfinite(p.rate_hz) and p.rate_hz > 0.0):
            raise ValueError(f"rate_hz must be finite and > 0, got rate_hz={p.rate_hz}")
        if not (np.isfinite(p.mix) and 0.0 <= p.mix <= 1.0):
            raise ValueError(f"mix must be finite and in [0, 1], got mix={p.mix}")

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the chorus, returning audio with input shape and dtype."""
        arr = np.asarray(audio)
        if self.params.is_neutral():
            return arr.copy()
        dry = arr.astype(np.float64)
        wet = fractional_delay(dry, chorus_delays(dry.shape[-1], self.sr, self.params))
        mix = self.params.mix
        return (dry * (1.0 - mix) + wet * mix).astype(arr.dtype)


def chorus_pass(
    audio: np.ndarray, sr: int, params: ChorusParams | None = None
) -> np.ndarray:
    """Full chorus pass (convenience wrapper).

    Neutral by default: with no ``params`` the input is returned bit-identical, so
    the stage is a safe no-op unless engaged.
    """
    return Chorus(sr, params).process(audio)
