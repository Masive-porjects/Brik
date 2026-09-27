"""License validation endpoints and middleware dependency."""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from audiomind.config import settings

router = APIRouter()

# ── Models ──────────────────────────────────────────────


class LicenseStatus(BaseModel):
    licensed: bool
    message: str


class ActivationRequest(BaseModel):
    key: str


class ActivationResponse(BaseModel):
    success: bool
    message: str


# ── Dependency ──────────────────────────────────────────


def require_license(
    x_license_key: str | None = Header(None),
) -> None:
    """FastAPI dependency that blocks unlicensed processing.

    When AUDIOMIND_LICENSE_KEY is set (production), every protected
    endpoint requires the X-License-Key header to match the configured
    value.  In development (no key configured) all requests pass through.
    """
    if not settings.license_key:
        return  # Development mode — allow all

    if not x_license_key or x_license_key.strip() != settings.license_key:
        raise HTTPException(
            status_code=403,
            detail="Clave de licencia inválida o no proporcionada. "
            "Incluí el header X-License-Key con tu clave de activación.",
        )


# ── Endpoints ───────────────────────────────────────────


@router.get("/license/status", response_model=LicenseStatus)
async def license_status() -> LicenseStatus:
    """Return whether the system is licensed.

    In development (no AUDIOMIND_LICENSE_KEY set), the system reports
    licensed=True so the frontend doesn't show a lock screen.

    When the key IS set (production), the frontend must call /activate
    first — this endpoint returns licensed=False until then.
    """
    if not settings.license_key:
        return LicenseStatus(
            licensed=True,
            message="Modo desarrollo — sin licencia requerida",
        )

    # Key configured → frontend must activate first
    return LicenseStatus(
        licensed=False,
        message="Se requiere licencia para usar AudioMind Studio",
    )


@router.post("/license/activate", response_model=ActivationResponse)
async def activate_license(req: ActivationRequest) -> ActivationResponse:
    """Validate and activate a license key.

    The key must match the AUDIOMIND_LICENSE_KEY environment variable.
    Returns success/failure — the frontend stores the result locally.
    """
    if not settings.license_key:
        return ActivationResponse(
            success=True,
            message="Modo desarrollo — sin licencia requerida",
        )

    if req.key.strip() == settings.license_key:
        return ActivationResponse(
            success=True,
            message="Licencia activada correctamente. ¡Bienvenido a AudioMind Studio!",
        )

    raise HTTPException(
        status_code=403,
        detail="Clave de licencia inválida. Verificá que el código ingresado sea correcto.",
    )
