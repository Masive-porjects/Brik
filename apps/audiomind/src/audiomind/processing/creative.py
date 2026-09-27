"""Creative exploration mode (Mix Engine Paso 08) — bounded random variants.

The plan maestro (``odd/tasks/plan-motor-de-mezcla.md``, paso 08) turns the
book's "envelope of ranges" into a ``MODO CREATIVO``: the engine draws N
variants of the mix sampling values INSIDE the standard's ranges (EQ gain/Q,
compressor ratios/timing, dimension sends, pan envelopes, bus recipe, stem
faders) with a per-variant reproducible seed, a ``creativity`` slider in
[0, 1] scaling the deviation from the strict standard, and a safety net —
rejection sampling against the Paso 03 positional validation and the Paso 07
QC report ("red de seguridad": a variant that violates an objective check is
rejected and re-sampled, never delivered). A deliberate out-of-envelope
choice (``manual``) is MARKED ``non_standard`` in the report, never blocked.

The space is CONTINUOUS by user requirement (2026-09-18: "espacio de
variantes CONTINUO/INFINITO, no presets finitos"): every param is a real
``(min, max)`` envelope of floats derived from the engine's own constants
(``magic_frequencies`` / ``dynamics`` / ``dimension`` / ``panorama`` /
``render_versions``), the standard value is the routing's base value, and
``draw_variant`` samples a gaussian centered on the standard whose sigma is
``creativity × (max − min) / 2`` — clamped to the envelope (the proposal's
"rejection sampling / clamp": the sample is clamped, the RENDER is
rejected via the QC/positional gate). ``creativity == 0`` returns the
standards verbatim: the variant routing is bit-identical to the strict
standard.

The envelope rule is documented per param: the book's explicit range where
the book defines one (Q 1.0–1.4 on cuts / 0.5–0.8 on boosts — pág. 32;
guitar 8:1–10:1 — págs. 56–57; bus 2–3 dB GR band — págs. 53–56; pre-delay
< 40 ms — Swedien pág. 39; reverb size 0.1–1.0 — ``reverb.py``; stem
trims ±6 dB — Mix Stem Balance T1 (product 2026-09-23; the vocals ±1 dB
band of the plan paso 07 alternative versions is NOT the fader limit),
otherwise a documented calibration around the
standard (multiplicative ±50 % for ratios/gains, ±100 % for timing),
clamped to the engine's own hard limits.

Module responsibilities (SRP): the space + draw + apply + validate + batch
loop live HERE; ``mix_engine.build_mix`` supplies the render/save closures
(the actual DSP chain) — dependency inversion toward the contract, so this
module stays importable and unit-testable without touching the engine.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable
from typing import Any

from audiomind.processing.dimension import DIMENSION_PROFILES
from audiomind.processing.dynamics import (
    BUS_COMPRESSOR_PROFILE,
    STEM_COMPRESSOR_PROFILES,
)
from audiomind.processing.magic_frequencies import MAGIC_PROFILES
from audiomind.processing.panorama import PAN_ROLE_PROFILES

#: Re-sampling attempts per variant (rejection sampling cap — the batch
#: never spins forever; a variant that exhausts it is marked ``rejected``).
MAX_CREATIVE_ATTEMPTS = 5
#: Seed stride between variant indices: ``attempt_seed = seed +
#: index*1000 + attempt`` — one deterministic stream per variant.
CREATIVE_ATTEMPT_SEED_STRIDE = 1000

#: The informational contract, spelled out in every report.
_CREATIVE_NOTE = (
    "creative mode: N variants sampled INSIDE the standard envelope, "
    "reproducible by seed; a variant violating the positional/QC checks is "
    "rejected (rejection sampling) and the batch never blocks; manual "
    "out-of-envelope choices are marked non_standard, never blocked"
)

#: Docmented calibration for EQ gain deviation (±1.5 dB around the book
#: value — the book's applied boosts are 0.5–1 dB; the sweep finds 8–10).
_EQ_GAIN_SWEEP_DB = 1.5
#: Book golden rule (Owsinski pág. 32–33): narrow Q on cuts, wide on boosts.
_EQ_Q_CUT_RANGE = (1.0, 1.4)
_EQ_Q_BOOST_RANGE = (0.5, 0.8)
#: Book recipe band for the ``other`` (guitar) ratio (págs. 56–57: 8:1–10:1).
_OTHER_RATIO_RANGE = (8.0, 10.0)
#: Jerry Finn bus ratio window (págs. 53–56): 1.5:1–4:1 — always engaged
#: (ratio 1:1 would silently bypass the glue).
_BUS_RATIO_RANGE = (1.5, 4.0)
#: Auto-correction clamp window around the 6 dB standard (documented
#: calibration; the plan fixes the clamp at 6 dB).
_PAN_CORRECTION_RANGE = (4.0, 8.0)
#: Stem balance fader band (Mix Stem Balance feature, T1): every stem
#: gets a ±6 dB trim envelope — wide enough to close a real vocal v.
#: drums gap (measured ~7 dB on the producer session) while keeping the
#: 0.0 dB neutral standard.
_TRIM_STEM_RANGE = (-6.0, 6.0)
#: Multiplicative band around the standard for sampled ratios/gains.
_MULT_RATIO = 0.5
#: Multiplicative band around the standard for sampled timings.
_MULT_TIME = 2.0


def _envelope(standard: float, lo: float, hi: float) -> tuple[float, float]:
    """(min, max) guaranteed to contain ``standard``.

    Guards the invariant that every param's standard sits inside its own
    envelope (the strict-standard routing must always be reachable):
    ``lo = min(lo, standard)``, ``hi = max(hi, standard)``.
    """
    return min(lo, standard), max(hi, standard)


def _mult_envelope(
    standard: float, factor: float, lo_clip: float, hi_clip: float,
) -> tuple[float, float]:
    """Multiplicative envelope ``standard × [1−factor/2... 1+...]`` clipped
    to the engine's hard limits; always contains ``standard``."""
    lo = max(standard * (1.0 - factor / 2.0), lo_clip)
    hi = min(standard * (1.0 + factor / 2.0), hi_clip)
    return _envelope(standard, lo, hi)


def _band_envelope(
    standard: float, lo: float, hi: float, lo_clip: float, hi_clip: float,
) -> tuple[float, float]:
    """Absolute band ``[lo, hi]`` clipped to hard limits, standards-safe."""
    return _envelope(standard, max(lo, lo_clip), min(hi, hi_clip))


def _eq_entry(stem: str, idx: int, band: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """One EQ band contributes its gain and Q envelopes (the magic
    FREQUENCIES themselves are fixed points of the book's table — sampling
    them would break the standard; only gain/Q move inside the envelope)."""
    gain = float(band["gain_db"])
    q = float(band.get("q", 1.0))
    q_lo, q_hi = (
        _EQ_Q_CUT_RANGE if band.get("type") == "cut" else _EQ_Q_BOOST_RANGE
    )
    source = str(band.get("source", "Owsinski pág. 32 — tabla mágica"))
    return (
        {
            "key": f"eq.{stem}.{idx}.gain_db",
            "stage": "eq",
            "stem": stem,
            "path": (stem, idx, "gain_db"),
            "min": gain - _EQ_GAIN_SWEEP_DB,
            "max": gain + _EQ_GAIN_SWEEP_DB,
            "standard": gain,
            "source": source,
            "apply": "set",
        },
        {
            "key": f"eq.{stem}.{idx}.q",
            "stage": "eq",
            "stem": stem,
            "path": (stem, idx, "q"),
            "min": min(q, q_lo),
            "max": max(q, q_hi),
            "standard": q,
            "source": "Owsinski pág. 32–33 — Q angosto al cortar (1.0–1.4), "
            "ancho al boostear (0.5–0.8)",
            "apply": "set",
        },
    )


def _comp_entries(
    stem: str, profile: dict[str, Any], root: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Compressor recipe entries: ratio, threshold offset, attack, release.

    ``root`` locates the param dict (the plain profile or the drums
    ``band_compressor`` sub-dict); ``path`` prefixes keep it unambiguous.
    """
    prefix: tuple[Any, ...] = (stem,) if "band" not in profile else (
        stem, "band_compressor",
    )
    # Report keys mirror the path (``stem`` or ``stem.band_compressor``)
    # so an entry's key uniquely locates its root: drums land at
    # ``comp.drums.band_compressor.*``, the plain roles at ``comp.*.*``.
    stem_key = ".".join(str(part) for part in prefix)
    if stem == "other" and "band" not in profile:
        lo, hi = _band_envelope(
            float(root["ratio"]), *_OTHER_RATIO_RANGE, 1.05, 30.0,
        )
        ratio_source = "Owsinski págs. 56–57 — 8:1–10:1 (ataque/liberación a tempo)"
    else:
        lo, hi = _mult_envelope(float(root["ratio"]), _MULT_RATIO, 1.05, 30.0)
        ratio_source = "Owsinski págs. 56–57 — receta del rol (±50 % del estándar)"
    offset = float(root.get("threshold_offset_db", 4.0))
    attack = float(root.get("attack_ms", 10.0))
    release = float(root.get("release_ms", 60.0))
    return (
        {
            "key": f"comp.{stem_key}.ratio",
            "stage": "comp",
            "stem": stem,
            "path": (*prefix, "ratio"),
            "min": lo,
            "max": hi,
            "standard": float(root["ratio"]),
            "source": ratio_source,
            "apply": "set",
        },
        {
            "key": f"comp.{stem_key}.threshold_offset_db",
            "stage": "comp",
            "stem": stem,
            "path": (*prefix, "threshold_offset_db"),
            "min": max(offset * (1.0 - _MULT_RATIO), 0.05),
            "max": min(offset * (1.0 + _MULT_RATIO), 30.0),
            "standard": offset,
            "source": "adaptive_comp — umbral program-dependent (±50 % del estándar)",
            "apply": "set",
        },
        {
            "key": f"comp.{stem_key}.attack_ms",
            "stage": "comp",
            "stem": stem,
            "path": (*prefix, "attack_ms"),
            "min": max(attack * (1.0 - _MULT_TIME / 2.0), 1.0),
            "max": min(attack * (1.0 + _MULT_TIME / 2.0), 10000.0),
            "standard": attack,
            "source": "págs. 56–57 — ataque del rol (±100 % del estándar)",
            "apply": "set",
        },
        {
            "key": f"comp.{stem_key}.release_ms",
            "stage": "comp",
            "stem": stem,
            "path": (*prefix, "release_ms"),
            "min": max(release * (1.0 - _MULT_TIME / 2.0), 1.0),
            "max": min(release * (1.0 + _MULT_TIME / 2.0), 10000.0),
            "standard": release,
            "source": "págs. 56–57 — liberación del rol (±100 % del estándar)",
            "apply": "set",
        },
    )


def _dimension_entries(
    stem: str, profile: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Dimension send envelopes (send params the standard actively sets
    only — a deliberately-absent send (mix 0.0 / subdivision None) is not
    jazzed back in: that would leave the standard's envelope)."""
    reverb = profile.get("reverb") or {}
    delay = profile.get("delay") or {}
    size = float(reverb.get("size", 0.5))
    mix = float(reverb.get("mix", 0.0))
    pre_delay = float(reverb.get("pre_delay_ms", 20.0))
    hp_hz = reverb.get("hp_hz")
    delay_mix = float(delay.get("mix", 0.0))
    feedback = float(delay.get("feedback", 0.0))
    entries: list[dict[str, Any]] = [
        {
            "key": f"dimension.{stem}.reverb.size",
            "stage": "dimension",
            "stem": stem,
            "path": (stem, "reverb", "size"),
            "min": max(size * (1.0 - _MULT_RATIO), 0.1),
            "max": min(size * (1.0 + _MULT_RATIO), 1.0),
            "standard": size,
            "source": "reverb.py — size ∈ [0.1, 1.0] (small room → huge hall)",
            "apply": "set",
        },
    ]
    if mix > 0.0:
        entries.append({
            "key": f"dimension.{stem}.reverb.mix",
            "stage": "dimension",
            "stem": stem,
            "path": (stem, "reverb", "mix"),
            "min": max(mix * (1.0 - _MULT_RATIO), 0.0),
            "max": min(mix * (1.0 + _MULT_RATIO), 1.0),
            "standard": mix,
            "source": "págs. 36–39 — envío reverb por rol",
            "apply": "set",
        })
    entries.append({
        "key": f"dimension.{stem}.reverb.pre_delay_ms",
        "stage": "dimension",
        "stem": stem,
        "path": (stem, "reverb", "pre_delay_ms"),
        "min": max(pre_delay * (1.0 - _MULT_RATIO), 5.0),
        "max": min(pre_delay * (1.0 + _MULT_RATIO), 40.0),
        "standard": pre_delay,
        "source": "Swedien pág. 39 — early reflections < 40 ms",
        "apply": "set",
    })
    if hp_hz is not None:
        hp = float(hp_hz)
        entries.append({
            "key": f"dimension.{stem}.reverb.hp_hz",
            "stage": "dimension",
            "stem": stem,
            "path": (stem, "reverb", "hp_hz"),
            "min": max(hp * (1.0 - _MULT_RATIO), 40.0),
            "max": min(hp * (1.0 + _MULT_RATIO), 800.0),
            "standard": hp,
            "source": "págs. 37–38 — cortar graves del retorno (HP del efecto)",
            "apply": "set",
        })
    if delay_mix > 0.0:
        entries.append({
            "key": f"dimension.{stem}.delay.mix",
            "stage": "dimension",
            "stem": stem,
            "path": (stem, "delay", "mix"),
            "min": max(delay_mix * (1.0 - _MULT_RATIO), 0.0),
            "max": min(delay_mix * (1.0 + _MULT_RATIO), 1.0),
            "standard": delay_mix,
            "source": "págs. 39–40 — envío delay a tempo por rol",
            "apply": "set",
        })
        entries.append({
            "key": f"dimension.{stem}.delay.feedback",
            "stage": "dimension",
            "stem": stem,
            "path": (stem, "delay", "feedback"),
            "min": max(feedback * (1.0 - _MULT_RATIO), 0.0),
            "max": min(feedback * (1.0 + _MULT_RATIO), 1.0),
            "standard": feedback,
            "source": "págs. 39–40 — feedback del delay a tempo",
            "apply": "set",
        })
    return tuple(entries)


def _pan_entries(stem: str, profile: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Pan envelope params: the role balance target and the correction
    clamp (both continuous — how tight/loose the positional contract is)."""
    target = float(profile.get("target_max_abs_balance_db", 3.0))
    correction = float(profile.get("max_correction_db", 6.0))
    return (
        {
            "key": f"pan.{stem}.target_max_abs_balance_db",
            "stage": "pan",
            "stem": stem,
            "path": (stem, "target_max_abs_balance_db"),
            "min": max(target * (1.0 - _MULT_RATIO), 1.0),
            "max": min(target * (1.0 + _MULT_RATIO), 18.0),
            "standard": target,
            "source": "Owsinski ch. 4, págs. 20–24 — rol center ≤ 3 dB / "
            "wide ≤ 12 dB (±50 % del estándar)",
            "apply": "set",
        },
        {
            "key": f"pan.{stem}.max_correction_db",
            "stage": "pan",
            "stem": stem,
            "path": (stem, "max_correction_db"),
            "min": min(_PAN_CORRECTION_RANGE[0], correction),
            "max": max(_PAN_CORRECTION_RANGE[1], correction),
            "standard": correction,
            "source": "spec §4 — corrección automática sin pasar el clamp (4–8 dB)",
            "apply": "set",
        },
    )


def _bus_entries() -> tuple[dict[str, Any], ...]:
    """Mix-bus (Jerry Finn) envelopes: ratio + GR-driving threshold offset."""
    ratio = float(BUS_COMPRESSOR_PROFILE["ratio"])
    offset = float(BUS_COMPRESSOR_PROFILE["threshold_offset_db"])
    return (
        {
            "key": "bus.ratio",
            "stage": "bus",
            "stem": None,
            "path": ("ratio",),
            "min": min(_BUS_RATIO_RANGE[0], ratio),
            "max": max(_BUS_RATIO_RANGE[1], ratio),
            "standard": ratio,
            "source": "Owsinski págs. 53–56 — glue 2:1 dentro de 1.5:1–4:1",
            "apply": "set",
        },
        {
            "key": "bus.threshold_offset_db",
            "stage": "bus",
            "stem": None,
            "path": ("threshold_offset_db",),
            "min": max(offset * (1.0 - _MULT_RATIO), 0.05),
            "max": min(offset * (1.0 + _MULT_RATIO), 30.0),
            "standard": offset,
            "source": "págs. 53–56 — GR 2–3 dB totales (±50 % del estándar)",
            "apply": "set",
        },
    )


def _trim_entries() -> tuple[dict[str, Any], ...]:
    """Stem balance faders (Mix Stem Balance, T1): every stem gets a
    ±6 dB trim (drums/bass/other/vocals), applied at the bus input after
    the chain — the creative-mode "mixer fader board". The vocals entry
    keeps the plan paso 07 meaning (vocal fader); the ±1 dB band of the
    alternative versions is NOT the fader limit — the product decision
    (2026-09-23) widens the faders to ±6 dB and keeps 0.0 dB neutral."""
    return tuple(
        {
            "key": f"trim.{stem}_db",
            "stage": "trim",
            "stem": stem,
            "path": (f"{stem}_db",),
            "min": _TRIM_STEM_RANGE[0],
            "max": _TRIM_STEM_RANGE[1],
            "standard": 0.0,
            "source": "Mix Stem Balance T1 — stem fader ±6 dB (product 2026-09-23)",
            "apply": "set",
        }
        for stem in ("drums", "bass", "other", "vocals")
    )


def build_param_space() -> list[dict[str, Any]]:
    """The CONTINUOUS variant space, derived from the engine's constants.

    One entry per mutable parameter (every entry carries ``key`` / ``stage``
    / ``path`` / ``min`` / ``max`` / ``standard`` / ``source``) — pure
    function of the modules' own profiles: the standard values ARE the
    strict-standard routing, so a ``creativity=0`` variant reproduces the
    base mix bit-for-bit.
    """
    params: list[dict[str, Any]] = []
    for stem, bands in MAGIC_PROFILES.items():
        for idx, band in enumerate(bands):
            params.extend(_eq_entry(stem, idx, band))
    for stem, profile in STEM_COMPRESSOR_PROFILES.items():
        root = profile if "band" not in profile else profile["band_compressor"]
        params.extend(_comp_entries(stem, profile, root))
    for stem, profile in DIMENSION_PROFILES.items():
        params.extend(_dimension_entries(stem, profile))
    for stem, profile in PAN_ROLE_PROFILES.items():
        params.extend(_pan_entries(stem, profile))
    params.extend(_bus_entries())
    params.extend(_trim_entries())
    return params


#: The space (computed once at import — pure data, no randomness).
CREATIVE_PARAM_SPACE: list[dict[str, Any]] = build_param_space()

#: Key → entry lookup (the apply walker and the report use it).
_SPACE_BY_KEY: dict[str, dict[str, Any]] = {
    entry["key"]: entry for entry in CREATIVE_PARAM_SPACE
}


def draw_variant(seed: int, creativity: float = 1.0) -> dict[str, float]:
    """Draw one variant: every param sampled inside its envelope.

    ``random.Random(seed)`` guarantees reproducibility across runs
    (honest A/B contract: same seed → same variant). Sampling centers on
    the standard with ``sigma = creativity × (max − min) / 2`` (so at
    creativity 1 the whole envelope is within ±1 sigma) and clamps to the
    envelope — the proposal's "rejection sampling / clamp". ``creativity
    0`` returns the standards verbatim: the strict-standard routing.
    Values are rounded to 6 decimals (continuous floats, never a preset
    grid).

    Args:
        seed: Variant seed (any int; the caller owns the stride).
        creativity: Deviation slider in [0, 1] (clamped defensively).

    Returns:
        ``{param_key: float}`` — one value per ``CREATIVE_PARAM_SPACE``
        entry, always inside ``[min, max]``.
    """
    creativity = max(0.0, min(1.0, float(creativity)))
    rng = random.Random(int(seed))
    if creativity <= 0.0:
        return {entry["key"]: entry["standard"] for entry in CREATIVE_PARAM_SPACE}
    variant: dict[str, float] = {}
    for entry in CREATIVE_PARAM_SPACE:
        lo = entry["min"]
        hi = entry["max"]
        sigma = creativity * (hi - lo) / 2.0
        value = rng.gauss(entry["standard"], sigma)
        # Round FIRST, clamp LAST: a rounded boundary sample can exceed
        # the float envelope by 1 ulp (clamp-then-round let 0.525 escape
        # [0.175, 0.5249999999999999]); clamping after rounding makes
        # ``[min, max]`` a hard, measured guarantee.
        value = round(float(value), 6)
        variant[entry["key"]] = max(lo, min(hi, value))
    return variant


def _set_path(node: Any, path: tuple[Any, ...], value: float) -> None:
    """Descend ``path`` (dict keys and list indices mixed) and set the
    leaf to ``value`` — the apply walker of the param paths."""
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def apply_variant_to_profiles(
    variant: dict[str, float] | None,
) -> tuple[dict[str, Any], ...]:
    """Map a variant (or ``None``) onto SIX fresh routing roots.

    Roots, in return order:
    ``(profiles[EQ], pan_profiles, dimension_profiles, compressor_profiles,
    bus_profile, trims)``. The bases are the engine's own constants
    (``MAGIC_PROFILES`` / ``PAN_ROLE_PROFILES`` / ``DIMENSION_PROFILES`` /
    ``STEM_COMPRESSOR_PROFILES`` / ``BUS_COMPRESSOR_PROFILE`` and the
    ``{"vocals_db": 0.0}`` trim root); each is deep-copied so the shared
    module constants are NEVER mutated (a variant render is a private
    mix). A partial variant dict applies only the keys it carries; an
    empty/``None`` variant returns the exact standard values on every
    root — the strict-standard routing the ``creativity=0`` contract
    relies on.

    Args:
        variant: ``{param_key: value}`` — keys must belong to
            ``CREATIVE_PARAM_SPACE`` (unknown keys raise ``KeyError``).

    Returns:
        The six roots ordered as documented above.
    """
    bases: dict[str, Any] = {
        "eq": MAGIC_PROFILES,
        "pan": PAN_ROLE_PROFILES,
        "dimension": DIMENSION_PROFILES,
        "comp": STEM_COMPRESSOR_PROFILES,
        "bus": BUS_COMPRESSOR_PROFILE,
        "trim": {"drums_db": 0.0, "bass_db": 0.0, "other_db": 0.0, "vocals_db": 0.0},
    }
    roots = {stage: copy.deepcopy(base) for stage, base in bases.items()}
    if variant:
        for key, value in variant.items():
            entry = _SPACE_BY_KEY.get(key)
            if entry is None:
                raise KeyError(
                    f"unknown creative param {key!r}; expected one of the "
                    f"{len(CREATIVE_PARAM_SPACE)} space keys"
                )
            _set_path(roots[entry["stage"]], entry["path"], float(value))
    return (
        roots["eq"],
        roots["pan"],
        roots["dimension"],
        roots["comp"],
        roots["bus"],
        roots["trim"],
    )


def _check_results(
    validation_result: dict[str, Any], qc_result: dict[str, Any],
) -> tuple[bool, bool]:
    """(positional_ok, qc_ok) of a rendered variant.

    ``positional_ok``: the pan-stage mono check passes (mono-compatible
    bus AND no anti-phase stems — ``panorama.validate_positions``).
    ``qc_ok``: the Paso 07 report summary says ``all_ok``. Both stay
    informational on manual mode (reported, never blocking).
    """
    mono = validation_result.get("mono_check") or {}
    positional_ok = bool(mono.get("mono_compatible", False)) and not bool(
        mono.get("anti_phase_stems")
    )
    qc_ok = bool((qc_result.get("summary") or {}).get("all_ok", False))
    return positional_ok, qc_ok


def variant_is_valid(
    validation_result: dict[str, Any],
    qc_result: dict[str, Any],
    manual: bool = False,
) -> bool:
    """Rejection-sampling gate: is a rendered variant deliverable?

    A variant is valid when BOTH the positional validation (Paso 03:
    mono-compatible sum, no anti-phase stems) and the QC report (Paso 07:
    ``summary.all_ok``) pass. ``manual=True`` (the producer's deliberate
    out-of-envelope choice) NEVER rejects — the variant is marked
    ``non_standard`` by the caller instead, per the proposal's "salida
    no-estándar se marca, no se bloquea".
    """
    if manual:
        return True
    positional_ok, qc_ok = _check_results(validation_result, qc_result)
    return positional_ok and qc_ok


def run_creative_mode(
    seed: int,
    creativity: float,
    variants_count: int,
    render: Callable[[int, dict[str, float]], dict[str, Any]],
    save: Callable[[int, int, Any], str],
    manual: bool = False,
    max_attempts: int = MAX_CREATIVE_ATTEMPTS,
) -> dict[str, Any]:
    """Run the creative batch: N variants, rejection sampling, no blocking.

    For every variant index the loop draws at most ``max_attempts``
    candidates on the documented seed stride (``seed + index*1000 +
    attempt``), renders each through the caller's ``render`` closure and
    accepts the first one that passes the positional/QC gate. Accepted
    variants are persisted through ``save`` (producing the WAV path);
    rejected candidates are marked ``rejected`` with no file. Every
    variant yields exactly ONE report entry — the batch never blocks and
    never spins forever.

    Args:
        seed: Base seed of the batch (per-variant streams derive from it).
        creativity: Deviation slider in [0, 1] handed to ``draw_variant``.
        variants_count: Number of variants to render.
        render: ``(attempt_seed, params) -> {"validation": pan_report,
            "qc": qc_report, "bus": np.ndarray}`` — the caller runs the
            DSP chain and returns the two safety-net reports plus the
            candidate bus.
        save: ``(index, attempt_seed, bus) -> path`` — persists an
            ACCEPTED variant's WAV; only called on acceptance.
        manual: Mark every accepted variant ``non_standard`` and never
            reject on failing checks (the producer's deliberate choice).
        max_attempts: Re-sampling attempts per variant (default 5).

    Returns:
        ``{
          "seed": int, "creativity": float, "manual": bool,
          "status": "active",
          "variants": [{"index", "seed", "status": "ok"|"rejected",
                        "params", "qc_ok", "positional_ok",
                        "non_standard", "path"}],
          "rejected_count": int, "note": str
        }`` — reproducible: same seed → the identical report.
    """
    max_attempts = max(1, int(max_attempts))
    variants: list[dict[str, Any]] = []
    for index in range(int(variants_count)):
        rejected: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            attempt_seed = int(seed) + index * CREATIVE_ATTEMPT_SEED_STRIDE + attempt
            params = draw_variant(attempt_seed, creativity)
            result = render(attempt_seed, params)
            positional_ok, qc_ok = _check_results(
                result["validation"], result["qc"]
            )
            accepted = variant_is_valid(
                result["validation"], result["qc"], manual=manual
            )
            if accepted:
                path = save(index, attempt_seed, result["bus"])
                variants.append({
                    "index": index,
                    "seed": attempt_seed,
                    "status": "ok",
                    "params": params,
                    "qc_ok": qc_ok,
                    "positional_ok": positional_ok,
                    "non_standard": manual,
                    "path": str(path),
                })
                break
            rejected = {
                "index": index,
                "seed": attempt_seed,
                "status": "rejected",
                "params": params,
                "qc_ok": qc_ok,
                "positional_ok": positional_ok,
                "non_standard": manual,
                "path": None,
            }
        if rejected is not None and len(variants) <= index:
            variants.append(rejected)
    return {
        "seed": int(seed),
        "creativity": float(creativity),
        "manual": bool(manual),
        "status": "active",
        "variants": variants,
        "rejected_count": sum(
            1 for entry in variants if entry["status"] == "rejected"
        ),
        "note": _CREATIVE_NOTE,
    }