"""Stereo imaging per band (Sprint 9 — LR4 crossovers + constant-power M/S width).

Replaces the broadband M/S width (non-constant-power, correlation-risky) with
per-band width control:

- The Sprint 4 ``LinkwitzRiley4`` crossover splits the signal into three bands
  (low/mid/high); each band gets its own M/S width gain.
- Constant-power width: ``mid' = mid·sqrt(2/(1+w))`` and
  ``side' = side·sqrt(2w/(1+w))``. This preserves the perceived energy when
  widening — the sqrt2 normalization avoids the "center hole" that a plain
  mid cut creates.
- Lows mono is forced below ``mono_below_hz`` (default 120 Hz) inside the low
  band only, monitored by phase correlation with a safety against phase
  cancellation in mono downmix.

NEUTRAL configuration (all widths 1.0, ``mono_below_hz=0.0``) is a bit-exact
bypass — the same contract every DSP stage in this project follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt

from audiomind.processing.multiband import LinkwitzRiley4

#: Safety floor for stereo phase correlation after processing. Below this the
#: side content is attenuated toward a safe mono-compatible image.
CORRELATION_SAFETY_FLOOR = -0.1
#: How aggressively the safety attenuates side on each pass.
SAFETY_SIDE_GAIN = 0.7


@dataclass(frozen=True)
class StereoImagingParams:
    """Per-band stereo width and mono-lows configuration."""

    crossover_low_hz: float = 150.0
    crossover_high_hz: float = 3000.0
    low_width: float = 1.0
    mid_width: float = 1.0
    high_width: float = 1.0
    mono_below_hz: float = 0.0

    def is_neutral(self) -> bool:
        """True when every band keeps its original width and mono lows is off.

        With these settings the stage must be a bit-exact no-op.
        """
        return (
            self.low_width == 1.0
            and self.mid_width == 1.0
            and self.high_width == 1.0
            and self.mono_below_hz == 0.0
        )


def _constant_power_gains(width: float) -> tuple[float, float]:
    """Return (mid_gain, side_gain) for a constant-power width ``w``.

    ``mid' = mid·sqrt(2/(1+w))``, ``side' = side·sqrt(2w/(1+w))``. At ``w=1``
    both gains are exactly 1.0 — the identity the bit-exact bypass relies on.
    """
    denom = 1.0 + width
    return float(np.sqrt(2.0 / denom)), float(np.sqrt(2.0 * width / denom))


def _mid_side_encode(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mid = (left + right) / np.sqrt(2.0)
    side = (left - right) / np.sqrt(2.0)
    return mid, side


def _mid_side_decode(mid: np.ndarray, side: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    left = (mid + side) / np.sqrt(2.0)
    right = (mid - side) / np.sqrt(2.0)
    return left, right


class StereoImaging:
    """Per-band M/S width with constant-power gains + mono lows safety.

    Input may be ``(samples,)`` mono (returned untouched — this stage is
    stereo-only) or ``(channels, samples)`` stereo ``(2, N)``.
    """

    def __init__(self, sr: int, params: StereoImagingParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else StereoImagingParams()
        self._validate()
        self.crossover = LinkwitzRiley4(
            self.sr, self.params.crossover_low_hz, self.params.crossover_high_hz
        )
        self._mono_sos: np.ndarray | None = None
        if self.params.mono_below_hz > 0.0:
            self._mono_sos = butter(
                4, self.params.mono_below_hz / (self.sr / 2.0), btype="low", output="sos"
            )

    def _validate(self) -> None:
        p = self.params
        for name, value in (
            ("crossover_low_hz", p.crossover_low_hz),
            ("crossover_high_hz", p.crossover_high_hz),
            ("low_width", p.low_width),
            ("mid_width", p.mid_width),
            ("high_width", p.high_width),
            ("mono_below_hz", p.mono_below_hz),
        ):
            if not (0.0 < value < (self.sr / 2.0)) and name in (
                "crossover_low_hz",
                "crossover_high_hz",
            ):
                raise ValueError(
                    f"Crossover frequencies must be 0 < f < sr/2; got {name}={value}"
                )
            if name.endswith("width") and not (0.0 <= value <= 2.0):
                raise ValueError(f"{name} must be in [0.0, 2.0]; got {value}")
            if name == "mono_below_hz" and not (0.0 <= value < (self.sr / 2.0)):
                raise ValueError(
                    f"mono_below_hz must be in [0.0, sr/2); got {value}"
                )
        if not (0.0 < p.crossover_low_hz < p.crossover_high_hz < (self.sr / 2.0)):
            raise ValueError(
                f"Crossovers must satisfy 0 < low < high < sr/2, got "
                f"low={p.crossover_low_hz}, high={p.crossover_high_hz}"
            )

    def process(self, audio: np.ndarray) -> np.ndarray:
        processed, _ = self._process(audio)
        return processed

    def process_with_diagnostics(
        self, audio: np.ndarray
    ) -> tuple[np.ndarray, dict[str, Any]]:
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        if x.ndim == 1:
            return x, {"neutral": True, "mono_input": True, "correlation_in": 1.0,
                       "correlation_out": 1.0}
        if x.ndim != 2 or x.shape[0] != 2:
            raise ValueError(
                f"Stereo imaging expects (2, N) stereo or (N,) mono; got {x.shape}"
            )

        diag: dict[str, Any] = {
            "neutral": False,
            "mono_input": False,
            "correlation_in": self._correlation(x),
        }

        if self.params.is_neutral():
            diag["neutral"] = True
            diag["correlation_out"] = diag["correlation_in"]
            diag["mono_below_hz"] = self.params.mono_below_hz
            return x, diag

        left, right = x[0], x[1]
        widths = (self.params.low_width, self.params.mid_width, self.params.high_width)

        if all(w == 1.0 for w in widths):
            # Mono-only fast path: no per-band width to apply, so the LR4
            # split/recombine is skipped entirely. The mono collapse runs on
            # the full signal exactly like the legacy enforce_mono_compatibility
            # — the mono downmix stays bit-identical (null test).
            effected = self._collapse_mono(np.stack([left, right]))
        else:
            # 1. Split both channels into the same three LR4 bands.
            left_bands = self.crossover.split(left)
            right_bands = self.crossover.split(right)

            # 2. Per-band constant-power M/S width.
            left_out = np.zeros_like(left)
            right_out = np.zeros_like(right)
            for band, width in zip(range(3), widths):
                if width == 1.0:
                    left_out += left_bands[band]
                    right_out += right_bands[band]
                    continue
                mid_gain, side_gain = _constant_power_gains(width)
                mid, side = _mid_side_encode(left_bands[band], right_bands[band])
                new_left, new_right = _mid_side_decode(mid * mid_gain, side * side_gain)
                left_out += new_left
                right_out += new_right

            # 3. Lows mono: collapse below mono_below_hz in the recombined
            #    signal (the low band is what carries that content).
            effected = self._collapse_mono(np.stack([left_out, right_out]))

        # 4. Correlation safety: protect mono downmix from phase cancellation.
        out_corr = self._correlation(effected)
        if out_corr < CORRELATION_SAFETY_FLOOR:
            effected = self._safety(effected)

        diag["correlation_out"] = self._correlation(effected)
        diag["band_widths_used"] = list(widths)
        diag["mono_below_hz"] = self.params.mono_below_hz
        return effected, diag

    def _collapse_mono(self, stereo: np.ndarray) -> np.ndarray:
        """Force the sub-``mono_below_hz`` region to mono center.

        Reuses the exact legacy reconstruction (mono lows + stereo highs) so
        the mono downmix of the result equals the mono downmix of the input.
        """
        if self._mono_sos is None or self.params.mono_below_hz <= 0.0:
            return stereo
        left, right = stereo[0], stereo[1]
        mono_low = sosfilt(self._mono_sos, (left + right) / 2.0)
        left_low = sosfilt(self._mono_sos, left)
        right_low = sosfilt(self._mono_sos, right)
        return np.stack([
            mono_low + (left - left_low),
            mono_low + (right - right_low),
        ])

    @staticmethod
    def _correlation(audio: np.ndarray) -> float:
        left = audio[0]
        right = audio[1]
        norm = np.linalg.norm(left) * np.linalg.norm(right) + 1e-10
        return float(np.dot(left, right) / norm)

    def _safety(self, audio: np.ndarray) -> np.ndarray:
        """Attenuate side (toward mono) until correlation >= the floor.

        Iteratively reduces side energy; if that cannot restore correlation
        (e.g. mid ≈ 0), blends toward a mono copy of the left channel.
        """
        left, right = audio[0], audio[1]
        mid, side = _mid_side_encode(left, right)

        side_gain = 1.0
        for _ in range(8):
            new_left, new_right = _mid_side_decode(mid, side * side_gain)
            candidate = np.stack([new_left, new_right])
            if self._correlation(candidate) >= CORRELATION_SAFETY_FLOOR:
                return candidate
            side_gain *= SAFETY_SIDE_GAIN

        # Edge case: mid ≈ 0 — blend toward a mono copy of left.
        best = np.stack(_mid_side_decode(mid, side * side_gain))
        mono_left = np.stack([best[0], best[0]])
        for blend in np.arange(0.1, 1.05, 0.1):
            candidate = best * (1.0 - blend) + mono_left * blend
            if self._correlation(candidate) >= CORRELATION_SAFETY_FLOOR:
                return candidate
        return mono_left


def apply_stereo_imaging(
    audio: np.ndarray,
    sr: int,
    params: StereoImagingParams | None = None,
) -> np.ndarray:
    """Apply the per-band stereo imaging stage (Sprint 9).

    Neutral configuration (all widths 1.0, mono lows off) is a bit-exact no-op.
    """
    return StereoImaging(sr, params).process(audio)
