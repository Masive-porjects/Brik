"""Harmonic exciter (Sprint 6 — parallel harmonic generation, Ozone style).

Restores the perceived "air" and "body" that lossy dynamics processing
(compression, limiting) removes: after the multiband and dynamic-EQ stages
the harmonics that once carried the top-end sparkle are gone, and raising
the level does not bring them back. The exciter regenerates them from the
signal itself and mixes them back in parallel — the component that "most
shows in a blind Ozone A/B" (roadmap).

Harmonic generation — two complementary curves, one per harmonic family:

  Even (warmth, "fat") — full-wave rectifier. ``|sin(ωt)|`` has the Fourier
  series ``2/π − Σ_n (4/(π(4n²−1)))·cos(2nωt)``: only even harmonics, with
  amplitude ``4/(π(4n²−1))`` of the input fundamental (H2 ≈ 0.42). The DC
  term that rectification adds is removed by the per-band high-pass on the
  excited content.

  Odd (presence, "edge") — tanh soft-clip with a drive control,
  ``tanh(x·10^(drive_db/20))``: an exactly odd, smooth function, so it
  produces only odd harmonics whose level grows with drive.

  Mix — ``(1−blend)·even + blend·odd``, so both families coexist with the
  balance set by ``harmonic_blend``.

Topology — parallel mix. Each band generates its excited signal from the
input, high-passes it (``scipy.signal.butter`` high-pass, order 4 = 24 dB/
oct) so the harmonics do not fatten the bass, then adds it back in
parallel:

    y = x + Σ_b amount_b · excited_b

Four Ozone-style bands: bass (even, 100 Hz), tube (even, 200 Hz), tape
(odd, 200 Hz), air (odd, 800 Hz). ``amount`` is the dry/wet mix of each
band's excited content; 0.0 is a transparent band.

Neutral mode: when every band has amount 0.0 the stage is a bit-exact no-op
(the generation/filtering pass is skipped and the input returned
untouched). The engine inserts this stage gated by
``params.exciter_enabled`` with amount-0.0 defaults, so existing masters
pass through unchanged.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt

#: Valid harmonic-curve modes (band ``mode``).
VALID_MODES = ("even", "odd", "mix")
#: High-pass order on the EXCITED content (4th-order Butterworth = 24 dB/oct
#: below the corner: enough to genuinely protect the sub-bass, and the same
#: 4th-order convention as the Sprint 4 Linkwitz-Riley crossovers). Higher
#: orders would reject the bass harder but lengthen the transient response.
DEFAULT_HPF_ORDER = 4
#: Upper bound on ``drive_db`` (matches the ``exciter_band<N>_drive_db``
#: MasteringParameters field).
MAX_DRIVE_DB = 24.0
#: Default even/odd balance for the "mix" mode (0.5 = 50/50).
DEFAULT_HARMONIC_BLEND = 0.5


@dataclass(frozen=True)
class ExciterBandParams:
    """Per-band exciter settings.

    ``amount == 0.0`` makes the band transparent (it injects no excited
    content, part of the stage's bit-exact neutral path). ``mode`` selects
    the harmonic curve: ``"even"`` (full-wave rectifier, warmth), ``"odd"``
    (tanh soft-clip, presence) or ``"mix"`` (both, balanced by
    ``harmonic_blend``).
    """

    amount: float = 0.0
    drive_db: float = 0.0
    low_cut_hz: float = 200.0
    mode: str = "even"
    harmonic_blend: float = DEFAULT_HARMONIC_BLEND


@dataclass(frozen=True)
class ExciterParams:
    """Full exciter stage configuration (up to 4 Ozone-style bands).

    The defaults are NEUTRAL: all bands at amount 0.0, so the stage is a
    bit-exact bypass unless engaged.
    """

    bands: tuple[ExciterBandParams, ...] = field(
        default_factory=lambda: (
            ExciterBandParams(mode="even", low_cut_hz=100.0),  # bass
            ExciterBandParams(mode="even", low_cut_hz=200.0),  # tube
            ExciterBandParams(mode="odd", low_cut_hz=200.0),   # tape
            ExciterBandParams(mode="odd", low_cut_hz=800.0),   # air
        )
    )


def _build_hp_sos(
    sr: int, low_cut_hz: float, order: int = DEFAULT_HPF_ORDER,
) -> np.ndarray:
    """Butterworth high-pass on the excited content (sos form).

    Applied to the EXCITED content only, never to the dry path, so a band's
    low-cut removes rectifier DC and low harmonics without touching the
    original bass. Butterworth high-pass: 24 dB/oct below the corner (order
    4), unity gain well above it — a sine's harmonics far above
    ``low_cut_hz`` pass unaltered, which keeps the harmonic amplitudes
    measurable.
    """
    nyquist = float(sr) / 2.0
    return np.asarray(butter(order, low_cut_hz / nyquist, btype="highpass", output="sos"))


class Exciter:
    """Orchestrates per-band harmonic generation -> high-pass -> parallel mix.

    Each band generates an "excited" signal from the input (rectifier for
    even harmonics, tanh for odd, a blend for mix), high-passes it so the
    bass is not fattened, then mixes ``x + amount·excited`` in parallel. In
    the neutral configuration (all amounts 0.0) the input is returned
    untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: ExciterParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else ExciterParams()
        self._hp_sos: list[np.ndarray] = []
        for band in self.params.bands:
            self._validate_band(band)
            self._hp_sos.append(_build_hp_sos(self.sr, band.low_cut_hz))

    def _validate_band(self, band: ExciterBandParams) -> None:
        if band.mode not in VALID_MODES:
            raise ValueError(
                f"Band mode must be one of {VALID_MODES}, got mode={band.mode!r}"
            )
        if not (0.0 <= band.amount <= 1.0):
            raise ValueError(
                f"Band amount must be in [0, 1], got amount={band.amount}"
            )
        if not (0.0 <= band.drive_db <= MAX_DRIVE_DB):
            raise ValueError(
                f"Band drive_db must be in [0, {MAX_DRIVE_DB}], got "
                f"drive_db={band.drive_db}"
            )
        if not (0.0 < band.low_cut_hz < self.sr / 2.0):
            raise ValueError(
                f"Band low_cut_hz must satisfy 0 < low_cut_hz < sr/2, got "
                f"low_cut_hz={band.low_cut_hz}, sr={self.sr}"
            )
        if not (0.0 <= band.harmonic_blend <= 1.0):
            raise ValueError(
                f"Band harmonic_blend must be in [0, 1], got "
                f"harmonic_blend={band.harmonic_blend}"
            )

    def _is_neutral(self) -> bool:
        """True when every band is transparent (amount 0.0)."""
        return all(b.amount == 0.0 for b in self.params.bands)

    def _generate_excited(
        self, x: np.ndarray, band: ExciterBandParams,
    ) -> np.ndarray:
        """Generate a band's excited signal from the input (pre-filter)."""
        if band.mode == "even":
            return np.abs(x)
        drive = 10.0 ** (band.drive_db / 20.0)
        odd = np.tanh(x * drive)
        if band.mode == "odd":
            return np.asarray(odd)
        even = np.abs(x)
        return np.asarray((1.0 - band.harmonic_blend) * even + band.harmonic_blend * odd)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the exciter, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns per-band excited RMS and the
        harmonic-injection ratio (used by the Sprint 6 spectral
        verification)."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag: dict[str, Any] = {
            "excited_rms": [],
            "thd": [],
            "band_mode": [],
            "amount": [],
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # With all amounts 0.0 the parallel mix is exactly the input;
            # skip the generation/filtering pass so the neutral path is
            # bit-exact (null test), mirroring the multiband/dyn_eq shortcut.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)
        y = work.copy()  # parallel mix: y = x + Σ amount_b · excited_b

        input_rms = float(np.sqrt(np.mean(work**2)))
        excited_rms: list[float] = []
        thd: list[float] = []
        for band, sos in zip(self.params.bands, self._hp_sos, strict=True):
            excited = self._generate_excited(work, band)
            excited = sosfilt(sos, excited, axis=-1)
            rms = float(np.sqrt(np.mean(excited**2)))
            excited_rms.append(rms)
            # Harmonic-injection ratio of the band's excited content: the
            # added RMS relative to the input RMS. For the even rectifier
            # (|x| has no fundamental) this IS the THD of the added content;
            # for the odd path it counts the (compressed) fundamental too.
            thd.append(0.0 if input_rms == 0.0 else rms / input_rms)
            # amount == 0.0 adds exactly ±0.0 below the shortcut: the mix
            # stays bit-identical to the same stage without the band.
            y += band.amount * excited

        out = y.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "excited_rms": excited_rms,
            "thd": thd,
            "band_mode": [b.mode for b in self.params.bands],
            "amount": [b.amount for b in self.params.bands],
        }
        return out, diag


def excite(
    audio: np.ndarray, sr: int, params: ExciterParams | None = None,
) -> np.ndarray:
    """Full harmonic-exciter pass (convenience wrapper).

    Neutral by default: with no ``params`` (all amounts 0.0) the input is
    returned bit-identical, so the stage is a safe no-op unless configured.
    """
    return Exciter(sr, params).process(audio)
