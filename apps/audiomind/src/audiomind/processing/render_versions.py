"""Alternative mix versions (Mix Engine Paso 07) — vocals-trim re-sums.

The plan maestro's deliverable: the standard mix plus vocal
up/down ±0.5–1 dB, an instrumental and a TV mix (sin vocal). Every
version shares the SAME processed stems — the full per-stem chain
(pan → EQ → compressor → dimension) runs ONCE; this module re-sums the
already-shaped stems with a vocals-only trim and returns the five
PRE-bus-compression buses.

Contract (criteria of acceptance, ``plan-motor-de-mezcla.md`` paso 07):
* ``principal`` — trim 0.0 dB: the plain 1:1 pad sum, numerically
  identical to ``build_mix``'s own sum loop (same stem order, same
  float32 adds) — the byte-exact identity the principal path relies on.
* ``vocal_up`` / ``vocal_down`` — fixed documented trims ±0.75 dB
  (inside the ±0.5–1 dB plan band), applied to the vocals stem ONLY,
  AFTER its full processing, BEFORE the bus sum.
* ``instrumental`` — vocals stem silenced (multiplier 0.0; the stem is
  skipped in the sum, giving exact zeros — the deliverable keeps the
  same padded duration).
* ``tv_mix`` — no vocals, exactly like instrumental FOR THIS ENGINE:
  the TV/instrumental distinction is a DELIVERY distinction, not an
  audio one (both are the no-vocals render).

The returned buses are exact linear combinations of the processed
stems; the mix-bus compressor (the 2-bus, Paso 05) is applied by
``build_mix`` to each version's bus afterwards — DAW-real, the glue
reacts to the fader move the same way it reacts to the main fader.
"""

from __future__ import annotations

import numpy as np

from audiomind.processing.splitter import STEM_NAMES

#: The vocals stem every version trims (the only element that differs).
VOCALS_STEM = "vocals"

#: Per-version vocals trim in dB (``None`` = silenced; documented fixed
#: values — ±0.75 dB sits inside the plan's ±0.5–1 dB band).
VERSION_TRIMS_DB: dict[str, float | None] = {
    "principal": 0.0,
    "vocal_up": 0.75,
    "vocal_down": -0.75,
    "instrumental": None,
    "tv_mix": None,
}

#: Human-readable description of every version (delivery contract).
VERSION_DESCRIPTIONS: dict[str, str] = {
    "principal": (
        "Standard mix — the full pipeline result (identical to the /mix body)"
    ),
    "vocal_up": (
        "Vocals stem +0.75 dB post-processing trim; all other stems identical"
    ),
    "vocal_down": (
        "Vocals stem -0.75 dB post-processing trim; all other stems identical"
    ),
    "instrumental": (
        "Vocals stem silenced (0.0 multiplier); all other stems identical"
    ),
    "tv_mix": (
        "No-vocals deliverable — same render as instrumental for this engine "
        "(TV/instrumental is a delivery distinction)"
    ),
}

#: Linear gain of a trim in dB (``None`` → 0.0, the silenced vocals).
def version_trim_gain(trim_db: float | None) -> float:
    """Linear multiplier for a vocals trim in dB.

    ``0.0`` → exactly ``1.0`` (the identity the principal path relies
    on); ``None`` → ``0.0`` (silenced stem).
    """
    if trim_db is None:
        return 0.0
    return float(10.0 ** (trim_db / 20.0))


def _sum_stems_with_vocal_trim(
    processed_stems: dict[str, np.ndarray], trim_db: float | None,
) -> np.ndarray:
    """1:1 pad sum of the processed stems with a vocals-only trim.

    Mirrors ``build_mix``'s own summing loop (float32 zeros → per-stem
    ``+=`` in ``STEM_NAMES`` order) so trim 0.0 reproduces the principal
    bus exactly. A ``None`` trim skips the vocals stem entirely (exact
    zeros in its region — the silenced deliverable); the bus still pads
    to the full duration.
    """
    if not processed_stems:
        raise ValueError("processed_stems is empty — nothing to render")
    max_len = max(audio.shape[1] for audio in processed_stems.values())
    bus = np.zeros((2, max_len), dtype=np.float32)
    gain = version_trim_gain(trim_db)
    for name in STEM_NAMES:
        audio = processed_stems[name]
        if name == VOCALS_STEM:
            if gain == 0.0:
                continue
            if gain != 1.0:
                audio = audio * np.float32(gain)
        bus[:, : audio.shape[1]] += audio
    return bus


def render_version_buses(
    processed_stems: dict[str, np.ndarray],
    trims: dict[str, float | None] | None = None,
) -> dict[str, np.ndarray]:
    """Render the five version buses from the same processed stems.

    Args:
        processed_stems: The per-stem outputs of the full processing
            chain (pan → EQ → compressor → dimension) keyed by stem
            name — ``(channels, samples)`` float32 or mono. MUST include
            ``vocals`` (the element every version trims).
        trims: Per-version vocals trims; ``None`` ⇒ ``VERSION_TRIMS_DB``.

    Returns:
        ``{name: bus}`` for every version — ``(2, N)`` float32
        PRE-bus-compression sums. ``principal`` is the trim-0 re-sum of
        ``build_mix``'s own bus (same order, same bits); the other
        versions differ ONLY in the vocals region.

    Raises:
        ValueError: When ``processed_stems`` is empty or lacks the
            vocals stem.
    """
    if VOCALS_STEM not in processed_stems:
        raise ValueError(
            f"processed_stems must include '{VOCALS_STEM}' to render versions; "
            f"got {sorted(processed_stems)}"
        )
    trims = VERSION_TRIMS_DB if trims is None else trims
    return {
        name: _sum_stems_with_vocal_trim(processed_stems, trim)
        for name, trim in trims.items()
    }