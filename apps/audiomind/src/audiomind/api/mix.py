"""Mix Engine API endpoints (Paso 01 — per-stem routing).

``POST /api/session/{id}/mix`` — split the session audio into 4 stems,
route them at neutral 0 dB gains onto a stereo mono-compatible bus, write
``outputs/{id}_mix.wav`` and serve it. The JSON analysis payload
(per-stem analysis + full-mix ``tempo_bpm`` / ``genre`` /
``genre_confidence`` plus the resulting ``mix_status``) travels in the
``X-Mix-Result`` response header and is mirrored on the session
(``mix_path`` / ``mix_analysis`` / ``mix_status``). The mix is
recorded independently of the mastering pipeline: ``mastered_path`` is
never touched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from audiomind.api.license import require_license
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.splitter import STEM_NAMES
from audiomind.processing.stem_balance import TRIM_STEM_RANGE
from audiomind.services import demo_guard
from audiomind.session_store import save_sessions

router = APIRouter()

#: Claves de fader manual aceptadas por POST /mix — el mismo contrato del
#: mesh creativo (T1) y de los trims del bus (T2): ``{stem}_db``.
_STEM_TRIM_KEYS = tuple(f"{name}_db" for name in STEM_NAMES)


class MixRequest(BaseModel):
    """Optional body of ``POST /session/{id}/mix`` (v6).

    The spatial dimension stage (Paso 04: tempo delay + Schroeder reverb
    per stem) stays ENABLED by default — no body keeps the current
    behaviour. ``dimension_enabled=False`` routes the stems exactly like
    Paso 03 (no ``dimension_report`` in the payload).

    ``vocal_treatment`` opts into the ADAPTIVE vocal treatment by
    measured register (Eje A, ``vocal_adaptive``): default ``False``
    keeps the exact previous routing (no ``vocal_treatment_report`` key);
    ``True`` consumes the register/f0 measured on the vocal stem and
    reports what ran in ``vocal_treatment_report``.

    ``auto_balance`` opts into the STEM AUTO-BALANCE (feature
    ``odd/tasks/mix-stem-balance.md``, T3–T5): default ``False`` keeps
    the exact previous payload (no ``balance_report`` key, bit-identical
    neutral); ``True`` measures integrated LUFS on the processed stems,
    resolves the genre target from the same emphasis weights and
    corrects ONLY the voice toward it (±6 dB fader band of T1),
    reporting what ran in ``balance_report``.

    ``stem_trims`` are the MANUAL stem faders (T5, human decides): an
    optional dict of ``{stem}_db`` gains in the ±6 dB band applied to
    the bus input AFTER the whole chain (T2) and AFTER any auto-balance —
    the engine proposes, the human decides, the manual fader stays
    visible/relative to the engine's result. ``None`` (default) or all
    zeros keep the exact previous payload (no ``trim_report`` key,
    bit-identical neutral). Keys outside ``drums_db | bass_db |
    other_db | vocals_db`` or values outside [-6.0, 6.0] → 422.
    """

    dimension_enabled: bool = True
    vocal_treatment: bool = False
    auto_balance: bool = False
    stem_trims: dict[str, float] | None = None

    @field_validator("stem_trims")
    @classmethod
    def _validate_stem_trims(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        """Faders manuales estrictos: solo las claves ``{stem}_db`` de
        STEM_NAMES, cada una dentro de la banda ±6 dB (T1). Un ``ValueError``
        aquí responde 422 automáticamente (contrato del endpoint)."""
        if value is None:
            return value
        for key, db in value.items():
            if key not in _STEM_TRIM_KEYS:
                raise ValueError(
                    f"stem_trims key {key!r} not allowed; expected one of "
                    f"{', '.join(_STEM_TRIM_KEYS)}"
                )
            if not (TRIM_STEM_RANGE[0] <= db <= TRIM_STEM_RANGE[1]):
                raise ValueError(
                    f"stem_trims[{key}] must be in "
                    f"[{TRIM_STEM_RANGE[0]}, {TRIM_STEM_RANGE[1]}]"
                )
        return value


@router.post("/session/{session_id}/mix")
async def mix_session(
    session_id: str,
    request: MixRequest | None = None,
    _: None = Depends(require_license),
) -> FileResponse:
    """Split a session's audio into stems and serve the mix.

    The heavy pipeline (``build_mix``) runs inside the gated DSP pool, so
    concurrent heavy jobs on a 1 GB demo box stay serialized. The result
    WAV is served with the JSON analysis in the ``X-Mix-Result`` header:
    ``{"analysis": {stem: {...}}, "tempo_bpm": ..., "genre": ...,
    "genre_confidence": ..., "sample_rate": ..., "duration_seconds": ...}``.
    An optional JSON body (``MixRequest``) toggles the spatial dimension
    stage: ``{"dimension_enabled": false}`` disables delay+reverb (Paso 03
    routing); no body or ``true`` keeps the default (dimension ON). The
    same body opts into the adaptive vocal treatment:
    ``{"vocal_treatment": true}`` adds ``vocal_treatment_report`` to the
    payload (default off keeps the previous payload).

    The same body opts into the stem auto-balance:
    ``{"auto_balance": true}`` measures the stems and corrects ONLY the
    voice toward the genre target, adding ``balance_report`` to the
    payload (default off keeps the previous payload, bit-identical).

    The same body also accepts the MANUAL stem faders (T5):
    ``{"stem_trims": {"drums_db": 2.0, "vocals_db": -1.5}}`` applies each
    gain to its stem at the bus input AFTER the chain and AFTER any
    auto-balance, adding ``trim_report`` (gains ≠ 0 + applied) to the
    payload. Validated strictly: only ``drums_db | bass_db | other_db |
    vocals_db`` keys inside ±6 dB, otherwise 422. Absent or all-zero
    trims keep the exact previous payload (no ``trim_report`` key).

    ``session.mix_status`` tracks the run: ``processing`` before the heavy
    pipeline, ``completed`` on success, ``failed`` on error (the previous
    ``mix_path`` / ``mix_analysis`` survive a failure — they describe the
    last delivered mix). It is also exposed in the ``X-Mix-Result`` header
    and by ``GET /session/{id}``, so the client never has to invent it.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    # Defensive demo duration guard, same policy as /process: sessions
    # restored from disk or created outside /api/upload are caught here.
    if demo_guard.duration_over_limit(
        session.analysis.duration_seconds if session.analysis else None
    ):
        raise HTTPException(
            status_code=422,
            detail=demo_guard.demo_duration_message(
                settings.demo_max_duration_seconds
            ),
        )

    def _run_mix() -> dict[str, Any]:
        with demo_guard.gate():
            # v6 — spatial dimension optional: None = enabled (default,
            # DIMENSION_PROFILES), {} = disabled (routing identical to
            # Paso 03, no dimension_report).
            dimension_profiles: dict[str, dict[str, Any]] | None = (
                None
                if (request is None or request.dimension_enabled)
                else {}
            )
            return build_mix(
                session_id,
                str(session.original_path),
                dimension_profiles=dimension_profiles,
                vocal_treatment=bool(
                    request is not None and request.vocal_treatment
                ),
                auto_balance=bool(
                    request is not None and request.auto_balance
                ),
                stem_trims=request.stem_trims if request else None,
            )

    # The pipeline is about to run: publish the state BEFORE the heavy work
    # so a concurrent GET /session/{id} (or the client's own gate) sees
    # "processing" and never mistakes a running mix for a missing one. The
    # guards above are request rejections — they leave the state untouched.
    session.mix_status = "processing"
    save_sessions(sessions)

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            demo_guard.DSP_THREAD_POOL, _run_mix
        )
    except Exception as e:
        # The mix failed: the live state must say so (the previous
        # ``mix_path`` / ``mix_analysis``, if any, stay untouched — they
        # describe the last SUCCESSFUL mix and remain downloadable).
        session.mix_status = "failed"
        save_sessions(sessions)
        raise HTTPException(status_code=500, detail=f"Mix failed: {str(e)}") from e

    # The session payload mirrors the header: analysis + full-mix fields +
    # the state this mix reached. ``mix_path`` stays a separate field (the
    # file pointer) and ``mix_status`` is ALSO a first-class session field,
    # so the live state survives a later failed re-mix: the stored
    # ``mix_analysis`` is the snapshot of the last DELIVERED mix.
    payload = {
        **{key: value for key, value in result.items() if key != "mix_path"},
        "mix_status": "completed",
    }
    # Persist mix_metadata for adaptive mastering (Mix→Master handshake)
    session.mix_metadata = result.get("mix_metadata")
    session.mix_path = result["mix_path"]
    session.mix_analysis = payload
    session.mix_status = "completed"
    demo_guard.touch(session_id)
    save_sessions(sessions)

    return FileResponse(
        result["mix_path"],
        media_type="audio/wav",
        filename=f"{session_id}_mix.wav",
        headers={"X-Mix-Result": json.dumps(payload, ensure_ascii=True)},
    )


@router.get("/session/{session_id}/audio/mix")
async def get_mix_audio(
    session_id: str,
    _: None = Depends(require_license),
) -> FileResponse:
    """Serve the persisted mix WAV (stable URL for player + download).

    The mix survives backend restarts like any persisted session: this
    GET reads ``session.mix_path`` directly instead of re-running
    ``build_mix``, so the frontend player/download can use a stable URL
    even after a page reload. ``X-Mix-Status`` reports the live mix state
    so a player can tell a delivered mix from a failed one without a
    second request to ``GET /session/{id}``.
    """
    session = sessions.get(session_id)
    if not session or not session.mix_path or not Path(session.mix_path).exists():
        raise HTTPException(status_code=404, detail="Mix not found for this session")
    return FileResponse(
        session.mix_path,
        media_type="audio/wav",
        filename=f"{session_id}_mix.wav",
        headers={"X-Mix-Status": session.mix_status},
    )
