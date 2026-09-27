"""Role-based panorama + positional validation (Mix Engine Paso 03).

Per-stem DAW chain (Owsinski ch. 4, ``VIABILIDAD_MOTOR_DE_MEZCLA.md``
línea 214): *fader → pan → EQ → compresor → sends*. This step inserts the
PAN *before* the Paso 02 EQ and adds the positional validation that turns
the panorama into a measurable, self-correcting stage.

Roles (book ch. 4, págs. 20–24): vocals / bass / drums → CENTER
(``|balance_db| ≤ 3`` dB); other (accompaniment) → INSIDE THE EXTREMES
(``|balance_db| ≤ 12`` dB — roughly 10:00 / 1:30–4:00, never hard L/R).
``drums`` is the FULL kit stem (kick + snare + hats together): its balance
role is CENTER (kick centered); the stereo width comes from the percussion
content, not from panning the kit.

Measurement (spec §2, always on the stem BEFORE correcting):
``balance_db = 10·log10(E_R / E_L)`` (0 = centered, + = right), Pearson
correlation L↔R (1 = mono/identical, ~0 = decorrelated/wide, < 0 =
anti-phase) and ``side_to_mid_db = 10·log10(E_side / E_mid)`` with
``S = (L−R)/2``, ``M = (L+R)/2``. Mono stems (``(N,)`` or ``(1, N)``) are
centered by definition.

Correction (spec §4, gross violations only): constant −3 dB
(equal-power) DAW pan law — ``θ = (pan+1)·π/4``, ``L = cos θ``,
``R = sin θ``; ``pan=0`` → −3 dB both channels, ``pan=±1`` → one channel
0 dB, the other ≈ 0. The corrective pan pulls ``|balance_db|`` toward the
role target (center → 0 dB; wide → the 12 dB EXTREME, not the center),
HARD-CLAMPED to ``max_correction_db`` (6 dB) of reduction. If the clamp
cannot reach the envelope the stem is left at the clamped position and
flagged ``human_review`` — never forced further. Anti-phase (correlation
< ``CORRELATION_SAFETY_FLOOR`` = −0.1, reused from ``stereo_imaging.py``)
is NEVER corrected: reported to ``human_decision``. Wide stems with
correlation > ``PSEUDO_STEREO_CORRELATION`` (0.98) get the
"sin ancho/pseudo-estéreo" note — creating their own stereo is a later
step, so they are not touched.

Mono check (spec §5): the corrected stem-sum bus collapsed to mono —
``loss_db = 10·log10(E_mono / ((E_L+E_R)/2))``; compatible when
``loss_db ≥ MONO_COMPAT_MIN_DB`` (−3 dB; fully anti-phase content gives
−∞ in theory, clamped to the JSON-safe ``_MONO_LOSS_FLOOR_DB`` so the
``X-Mix-Result`` header stays valid JSON).

Neutrality contract (spec 08): a stem inside its envelope passes through
THE SAME array object — bit-exact, the backend equivalent of a bypass.
A corrected stem is a new array with the pan gains applied; the input is
never mutated.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from audiomind.processing.stereo_imaging import CORRELATION_SAFETY_FLOOR

#: Role targets (Owsinski ch. 4): center role = |balance| ≤ 3 dB; wide role
#: = inside the extremes |balance| ≤ 12 dB. ``max_correction_db`` caps how
#: far an automatic correction may pull a gross violation (spec §4 — beyond
#: the clamp is human judgment).
PAN_ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "drums": {
        "role": "center",
        "target_max_abs_balance_db": 3.0,
        "max_correction_db": 6.0,
    },
    "bass": {
        "role": "center",
        "target_max_abs_balance_db": 3.0,
        "max_correction_db": 6.0,
    },
    "other": {
        "role": "wide",
        "target_max_abs_balance_db": 12.0,
        "max_correction_db": 6.0,
    },
    "vocals": {
        "role": "center",
        "target_max_abs_balance_db": 3.0,
        "max_correction_db": 6.0,
    },
}

#: Pearson correlation above this on a WIDE stem means it carries no real
#: stereo width (identical/near-identical channels) — flagged for human
#: review, never corrected (own-stereo creation is a later step).
PSEUDO_STEREO_CORRELATION = 0.98
#: Mono-compatibility criterion (spec §5): loss ≥ −3 dB is acceptable.
MONO_COMPAT_MIN_DB = -3.0

#: Clamp for dBs that are ±∞ in pathological cases (a silent channel,
#: all-side content): the report must stay JSON-safe (``json.dumps`` emits
#: ``Infinity``/``NaN`` for non-finite floats — the payload rides the
#: ``X-Mix-Result`` header).
_ENERGY_DB_CLAMP = 30.0
#: JSON-safe floor for the mono loss instead of −∞ (true value for a fully
#: anti-phase bus). Lands far below ``MONO_COMPAT_MIN_DB``.
_MONO_LOSS_FLOOR_DB = -60.0


def measure_stereo_position(audio: np.ndarray) -> dict[str, float]:
    """Measure the M/S position of a stereo stem (no mutation).

    Args:
        audio: ``(2, N)`` float32 stereo. Mono ``(N,)`` or ``(1, N)``
            stems are centered by definition.

    Returns:
        ``{"balance_db": float, "correlation": float, "side_to_mid_db":
        float}`` where ``balance_db = 10·log10(E_R/E_L)`` (0 centered,
        + right), ``correlation`` is Pearson L↔R (1 mono, ~0 wide, < 0
        anti-phase) and ``side_to_mid_db = 10·log10(E_side/E_mid)`` with
        S=(L−R)/2, M=(L+R)/2. Energy dBs are clamped to ±30 so the dict
        is always JSON-safe.

    Raises:
        ValueError: When the audio is not mono or ``(2, N)`` stereo.
    """
    x = np.asarray(audio)
    if x.ndim == 1 or (x.ndim == 2 and x.shape[0] == 1):
        return {
            "balance_db": 0.0,
            "correlation": 1.0,
            "side_to_mid_db": -_ENERGY_DB_CLAMP,
        }
    if x.ndim != 2 or x.shape[0] != 2:
        raise ValueError(
            f"measure_stereo_position expects (2, N) stereo or mono; got {x.shape}"
        )

    left = x[0]
    right = x[1]
    e_left = float(np.dot(left, left))
    e_right = float(np.dot(right, right))

    if e_left <= 0.0 and e_right <= 0.0:
        balance_db = 0.0
        correlation = 1.0
    else:
        if e_left <= 0.0:
            balance_db = _ENERGY_DB_CLAMP
        elif e_right <= 0.0:
            balance_db = -_ENERGY_DB_CLAMP
        else:
            balance_db = max(
                -_ENERGY_DB_CLAMP,
                min(_ENERGY_DB_CLAMP, float(10.0 * np.log10(e_right / e_left))),
            )
        denom = float(np.sqrt(e_left * e_right))
        correlation = max(-1.0, min(1.0, float(np.dot(left, right) / denom)))

    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    e_mid = float(np.dot(mid, mid))
    e_side = float(np.dot(side, side))
    if e_mid <= 0.0 and e_side <= 0.0:
        side_to_mid_db = -_ENERGY_DB_CLAMP
    elif e_mid <= 0.0:
        side_to_mid_db = _ENERGY_DB_CLAMP
    elif e_side <= 0.0:
        side_to_mid_db = -_ENERGY_DB_CLAMP
    else:
        side_to_mid_db = max(
            -_ENERGY_DB_CLAMP,
            min(_ENERGY_DB_CLAMP, float(10.0 * np.log10(e_side / e_mid))),
        )

    return {
        "balance_db": balance_db,
        "correlation": correlation,
        "side_to_mid_db": side_to_mid_db,
    }


def pan_law_gains(pan: float) -> tuple[float, float]:
    """Constant −3 dB (equal-power) DAW pan law gains.

    ``θ = (pan+1)·π/4``, ``L_gain = cos θ``, ``R_gain = sin θ`` with
    ``pan`` clamped to [−1, 1]. ``pan=0`` → √2/2 on both channels
    (−3.01 dB each, total power constant), ``pan=+1`` → (0, 1) — right
    at 0 dB, ``pan=−1`` → (1, 0) — left at 0 dB. The equal-power
    convention keeps the perceived loudness of the stem constant while
    it moves across the field (standard DAW behaviour).

    Returns:
        ``(left_gain, right_gain)`` linear gains.
    """
    pan_clamped = max(-1.0, min(1.0, float(pan)))
    theta = (pan_clamped + 1.0) * (np.pi / 4.0)
    return float(np.cos(theta)), float(np.sin(theta))


def _balance_correction_pan(balance_db: float, reduce_db: float) -> float:
    """Pan that reduces ``|balance_db|`` by exactly ``reduce_db`` dB.

    Applying gains ``(g_L, g_R)`` shifts the position by
    ``20·log10(g_R/g_L)`` dB. With the −3 dB law ``g_R/g_L = tan θ``, so a
    target ratio ``k = 10^(-reduce_db/20)`` maps to a unique pan:
    right-heavy (balance ≥ 0) pulls left (``g_R/g_L = k``), left-heavy
    mirrors it (``g_R/g_L = 1/k``). ``reduce_db`` is expected to already be
    clamped to ``max_correction_db``.
    """
    k = 10.0 ** (-reduce_db / 20.0)
    if balance_db >= 0.0:
        theta = np.arctan(k)
    else:
        theta = np.arctan(1.0 / k)
    return float((4.0 / np.pi) * theta - 1.0)


def apply_role_pan(
    audio: np.ndarray,
    role_profile: dict[str, Any],
    measured: dict[str, float],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply at most ONE corrective pan according to the stem role.

    Args:
        audio: ``(2, N)`` float32 stem (measured BEFORE any correction).
        role_profile: One entry of ``PAN_ROLE_PROFILES``
            (``{"role", "target_max_abs_balance_db", "max_correction_db"}``).
        measured: Position from ``measure_stereo_position(audio)``.

    Returns:
        ``(audio_or_corrected, entry)``. Inside the envelope the input
        array is returned untouched (bit-exact — the same object); gross
        violations return a NEW array with the clamped pan gains applied.
        ``entry`` is the ``pan_report["stems"][stem]`` dict: ``role`` /
        ``position`` (as measured) / ``status`` / optional ``correction``
        ``{"pan", "applied_db"}`` / ``notes``.

        ``status``: ``"within_envelope"`` (untouched), ``"corrected"``
        (reached the envelope within the clamp) or ``"human_review"``
        (anti-phase, pseudo-stereo wide stem, or clamp could not reach
        the target — corrected only in the last case).
    """
    role = str(role_profile.get("role", "center"))
    target = float(role_profile.get("target_max_abs_balance_db", 3.0))
    max_correction = float(role_profile.get("max_correction_db", 6.0))
    balance_db = float(measured["balance_db"])
    correlation = float(measured["correlation"])

    notes: list[str] = []
    entry: dict[str, Any] = {
        "role": role,
        "position": dict(measured),
        "status": "",
        "notes": notes,
    }

    # Anti-phase can cancel the mono downmix — never corrected here; phase
    # repair is out of this step's scope (human decision).
    if correlation < CORRELATION_SAFETY_FLOOR:
        entry["status"] = "human_review"
        notes.append(
            f"anti-phase (correlation {correlation:.3f} < "
            f"{CORRELATION_SAFETY_FLOOR}): no correction applied"
        )
        return audio, entry

    # Wide stems with near-identical channels carry no real width — noted
    # for human review (own-stereo creation is a later step), not corrected.
    pseudo_stereo = role == "wide" and correlation > PSEUDO_STEREO_CORRELATION
    if pseudo_stereo:
        notes.append(
            "sin ancho/pseudo-estéreo (correlation > "
            f"{PSEUDO_STEREO_CORRELATION}): se aborda en pasos posteriores"
        )

    if abs(balance_db) <= target:
        entry["status"] = "human_review" if pseudo_stereo else "within_envelope"
        return audio, entry

    if audio.ndim != 2 or audio.shape[0] != 2:
        raise ValueError(
            "role pan correction requires stereo (2, N) audio; got "
            f"{audio.shape}"
        )

    # Reduction needed vs the clamp: pull toward the role target, never
    # more than max_correction_db.
    excess_db = abs(balance_db) - target
    reduce_db = min(excess_db, max_correction)
    pan = _balance_correction_pan(balance_db, reduce_db)
    left_gain, right_gain = pan_law_gains(pan)
    gains = np.array(
        [[np.float32(left_gain)], [np.float32(right_gain)]], dtype=np.float32
    )
    corrected = audio * gains  # new float32 array; input untouched

    entry["correction"] = {"pan": round(pan, 6), "applied_db": round(reduce_db, 6)}
    if abs(balance_db) - reduce_db <= target:
        entry["status"] = "human_review" if pseudo_stereo else "corrected"
    else:
        entry["status"] = "human_review"
        notes.append(
            f"clamp limit: correction left balance at "
            f"{abs(balance_db) - reduce_db:.1f} dB, beyond the {target:g} dB "
            "envelope — human review"
        )
    return corrected, entry


def _sum_bus(stems: dict[str, np.ndarray]) -> np.ndarray:
    """Pad every stem to the longest and sum onto a stereo bus.

    Mirrors ``build_mix``'s 1:1 summing (mono ``(1, N)`` stems broadcast
    to both channels — the mono-compatible routing contract).
    """
    if not stems:
        return np.zeros((2, 0), dtype=np.float32)
    max_len = max(audio.shape[1] for audio in stems.values())
    bus = np.zeros((2, max_len), dtype=np.float32)
    for audio in stems.values():
        bus[:, : audio.shape[1]] += audio
    return bus


def mono_compat_loss_db(audio: np.ndarray) -> float:
    """Energy loss when the stereo bus collapses to mono (spec §5).

    ``loss_db = 10·log10(E_mono / ((E_L + E_R) / 2))`` with the mono sum
    ``(L+R)/2``. L == R → 0 dB (no loss); fully anti-phase → the JSON-safe
    floor (true value −∞); mono input → 0 (trivially compatible). Compatible
    when ≥ ``MONO_COMPAT_MIN_DB`` (−3 dB).
    """
    x = np.asarray(audio)
    if x.ndim == 1 or x.shape[0] == 1:
        return 0.0
    if x.ndim != 2 or x.shape[0] != 2:
        raise ValueError(
            f"mono_compat_loss_db expects (2, N) stereo; got {x.shape}"
        )

    left = x[0]
    right = x[1]
    mono = (left + right) * 0.5
    e_mono = float(np.dot(mono, mono))
    e_avg = 0.5 * (float(np.dot(left, left)) + float(np.dot(right, right)))
    if e_avg <= 0.0:
        return 0.0
    if e_mono <= 0.0:
        return _MONO_LOSS_FLOOR_DB
    return max(_MONO_LOSS_FLOOR_DB, float(10.0 * np.log10(e_mono / e_avg)))


def validate_positions(
    stems: dict[str, np.ndarray],
    profiles: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Validate/correct the positional balance of every stem by role.

    Args:
        stems: Stems keyed by name, ``(2, N)`` float32 (or mono) — the
            RESAMPLED stems, measured before any correction.
        profiles: Per-stem role profiles; ``None`` ⇒ ``PAN_ROLE_PROFILES``.
            Stems without a profile entry pass through untouched and do not
            appear in the report.

    Returns:
        ``(corrected_stems, pan_report)``:

        - ``corrected_stems``: same keys as ``stems``; untouched arrays
          (same objects) for stems inside their envelope, clamped-pan
          copies for corrected ones.
        - ``pan_report``: ``{"roles": {stem: profile}, "stems": {stem:
          entry}, "mono_check": {"bus_loss_db", "mono_compatible",
          "anti_phase_stems"}, "human_decision": [{"stem", "reason"}]}``.
          ``human_decision`` collects clamp-irresolvable violations,
          anti-phase stems and wide pseudo-stereo stems. All floats are
          finite (JSON-safe for ``X-Mix-Result``).
    """
    profiles = PAN_ROLE_PROFILES if profiles is None else profiles
    processed: dict[str, np.ndarray] = {}
    report: dict[str, Any] = {
        "roles": {
            name: dict(profile)
            for name, profile in profiles.items()
            if name in stems
        },
        "stems": {},
        "mono_check": {},
        "human_decision": [],
    }
    anti_phase_stems: list[str] = []

    for name, audio in stems.items():
        profile = profiles.get(name)
        if profile is None:  # no role contract → untouched, unreported
            processed[name] = audio
            continue
        measured = measure_stereo_position(audio)
        corrected, entry = apply_role_pan(audio, profile, measured)
        processed[name] = corrected
        report["stems"][name] = entry
        if entry["status"] == "human_review":
            report["human_decision"].append(
                {"stem": name, "reason": "; ".join(entry["notes"])}
            )
        if measured["correlation"] < CORRELATION_SAFETY_FLOOR:
            anti_phase_stems.append(name)

    bus = _sum_bus(processed)
    loss_db = mono_compat_loss_db(bus)
    report["mono_check"] = {
        "bus_loss_db": loss_db,
        "mono_compatible": loss_db >= MONO_COMPAT_MIN_DB,
        "anti_phase_stems": anti_phase_stems,
    }
    return processed, report