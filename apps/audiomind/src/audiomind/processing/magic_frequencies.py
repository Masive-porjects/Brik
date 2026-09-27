"""Magic EQ frequencies per stem (Mix Engine Paso 02).

Per-stem EQ profiles built from the verified magic-frequencies table of
Bob Owsinski, *The Mixing Engineer's Handbook* (p. 32, Fig. 5), captured in
``docs/proposals/VIABILIDAD_MOTOR_DE_MEZCLA.md`` (líneas 78-92).

Golden rules applied (p. 33):
* CUT to make it sound BETTER, BOOST to make it sound DIFFERENT.
* Narrow Q on cuts (1.0–1.4), wide Q on boosts (0.5–0.8) — the wide Q on
  boosts avoids bad phase.
* All cuts come FIRST, boosts after (boosts add phase shift → coloration).
* Never boost what is not there; every instrument lives in its own band
  (*frequency juggling*).

Granularity decision (Paso 02): Demucs splits into 4 stems (drums, bass,
other, vocals), so the whole kit (kick + snare + hats + toms) shares ONE
``drums`` stem — its profile is the COMBINED kit profile over the whole
stem. Per-segment multiband dynamics separation arrives in Paso 05; here
the EQ applies to the entire stem. ``other`` is a conservative
accompaniment profile (guitars / keyboards / percussion); a measured
adjustment arrives in later steps. The gains are the conservative start
of the book's range envelope — boosted only where the content is
expected (p. 33: "no boostear lo que no está").
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: One band: ``{"type": "cut"|"boost", "freq_hz", "gain_db", "q",
#: "source", "filter": "peak"|"low_shelf"|"high_shelf"}``. ``filter`` is
#: optional and defaults to ``"peak"``; shelves are used for bottom
#: (LowShelf) and air (HighShelf) roles.
MAGIC_PROFILES: dict[str, list[dict[str, Any]]] = {
    # ── Drums: COMBINED kit profile (kick + snare + hats + toms share the
    #    one Demucs stem; multiband per-segment separation is Paso 05).
    "drums": [
        # Cuts first (narrow Q 1.0–1.4).
        {
            "type": "cut",
            "freq_hz": 200.0,
            "gain_db": -2.0,
            "q": 1.2,
            "filter": "peak",
            "source": "Owsinski pág. 32 — hi-hat/cymbal clang 200",
        },
        {
            "type": "cut",
            "freq_hz": 400.0,
            "gain_db": -2.0,
            "q": 1.2,
            "filter": "peak",
            "source": "Owsinski pág. 32 — kick holowness 400",
        },
        {
            "type": "cut",
            "freq_hz": 900.0,
            "gain_db": -2.0,
            "q": 1.4,
            "filter": "peak",
            "source": "Owsinski pág. 32 — snare boing 900",
        },
        # Boosts after (wide Q 0.5–0.8). Snap (peak, transient) and
        # sparkle (shelf, cymbal tail) share the 10 kHz region on purpose.
        {
            "type": "boost",
            "freq_hz": 90.0,
            "gain_db": 1.0,
            "q": 0.7,
            "filter": "low_shelf",
            "source": "Owsinski pág. 32 — kick bottom 80–100",
        },
        {
            "type": "boost",
            "freq_hz": 180.0,
            "gain_db": 0.5,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — snare body/fatness 120–240",
        },
        {
            "type": "boost",
            "freq_hz": 4000.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — kick point 3–5k",
        },
        {
            "type": "boost",
            "freq_hz": 5000.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — snare crisp 5k",
        },
        {
            "type": "boost",
            "freq_hz": 10000.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — snare snap 10k",
        },
        {
            "type": "boost",
            "freq_hz": 10000.0,
            "gain_db": 0.5,
            "q": 0.7,
            "filter": "high_shelf",
            "source": "Owsinski pág. 32 — hi-hat/cymbal sparkle 8–10k",
        },
    ],
    # ── Bass: the book lists bottom / presence / snap — no cut column,
    #    so all bands are boosts (envelope start only).
    "bass": [
        {
            "type": "boost",
            "freq_hz": 65.0,
            "gain_db": 1.0,
            "q": 0.7,
            "filter": "low_shelf",
            "source": "Owsinski pág. 32 — bajo bottom 50–80",
        },
        {
            "type": "boost",
            "freq_hz": 700.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — bajo presence 700",
        },
        {
            "type": "boost",
            "freq_hz": 2500.0,
            "gain_db": 0.5,
            "q": 0.8,
            "filter": "peak",
            "source": "Owsinski pág. 32 — bajo snap 2.5k",
        },
    ],
    # ── Other: conservative accompaniment profile (guitars / keyboards /
    #    percussion). Moderate Q so the shared band does not get dirty;
    #    measured adjustment arrives in later steps.
    "other": [
        # Cuts first.
        {
            "type": "cut",
            "freq_hz": 1000.0,
            "gain_db": -2.5,
            "q": 1.2,
            "filter": "peak",
            "source": "Owsinski pág. 32 — guitarra eléctrica: reducir 1k (gabinete)",
        },
        # Boosts after.
        {
            "type": "boost",
            "freq_hz": 350.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "peak",
            "source": "Owsinski pág. 32 — acompañamiento body 240–500",
        },
        {
            "type": "boost",
            "freq_hz": 2000.0,
            "gain_db": 0.5,
            "q": 0.8,
            "filter": "peak",
            "source": "Owsinski pág. 32 — acompañamiento presence 1.5–2.5k",
        },
    ],
    # ── Vocals: 5k presence is SOFT (+1 dB) on purpose — the table's
    #    "sibilancia 5k" extra is NOT an aggressive cut here; sibilance
    #    handling belongs to the existing de-esser in the mastering chain.
    "vocals": [
        # Cuts first.
        {
            "type": "cut",
            "freq_hz": 240.0,
            "gain_db": -2.0,
            "q": 1.3,
            "filter": "peak",
            "source": "Owsinski pág. 32 — voz boominess 240",
        },
        # Boosts after.
        {
            "type": "boost",
            "freq_hz": 120.0,
            "gain_db": 0.75,
            "q": 0.7,
            "filter": "low_shelf",
            "source": "Owsinski pág. 32 — voz bottom 120",
        },
        {
            "type": "boost",
            "freq_hz": 5000.0,
            "gain_db": 1.0,
            "q": 0.6,
            "filter": "peak",
            "source": "Owsinski pág. 32 — voz presence 5k (suave)",
        },
        {
            "type": "boost",
            "freq_hz": 12000.0,
            "gain_db": 1.0,
            "q": 0.7,
            "filter": "high_shelf",
            "source": "Owsinski pág. 32 — voz aire 10–15k",
        },
    ],
}


def apply_stem_eq(
    audio: np.ndarray, sr: int, bands: list[dict[str, Any]]
) -> np.ndarray:
    """Apply an EQ band list to a stem; bit-exact passthrough when neutral.

    ``audio`` is ``(channels, samples)`` float32 — the exact layout
    pedalboard consumes directly (same call pattern as ``engine.py``:
    ``board(audio, sr)``). Bands are processed in order; profiles keep
    cuts first and boosts after (golden rule — boosts add phase shift →
    coloration).

    Neutrality contract: an empty band list, or a list where every gain
    is 0 dB, returns the input array untouched — no pedalboard is built,
    so the passthrough is bit-exact (the backend equivalent of a bypass).
    """
    if not bands or all(float(band["gain_db"]) == 0.0 for band in bands):
        return audio

    # Pedalboard is heavy — lazy import, same policy as resampling.
    # Pedalboard is referenced module-qualified: pedalboard's __init__
    # re-exports it without __all__ and mypy strict (implicit_reexport=False)
    # therefore rejects a plain from-import of the name.
    import pedalboard
    from pedalboard import (
        HighShelfFilter,
        LowShelfFilter,
        PeakFilter,
    )

    plugins: list[Any] = []
    for band in bands:
        filter_type = band.get("filter", "peak")
        if filter_type == "low_shelf":
            plugin_cls: Any = LowShelfFilter
        elif filter_type == "high_shelf":
            plugin_cls = HighShelfFilter
        else:
            plugin_cls = PeakFilter
        plugins.append(
            plugin_cls(
                cutoff_frequency_hz=float(band["freq_hz"]),
                gain_db=float(band["gain_db"]),
                q=float(band.get("q", 1.0)),
            )
        )
    return pedalboard.Pedalboard(plugins)(audio, sr)