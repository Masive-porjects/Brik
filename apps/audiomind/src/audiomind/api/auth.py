"""User authentication for multi-tenant endpoints.

The backend historically authenticated nothing but a license key, so every
anonymous request shared one in-memory session pool. The Moises-style
migration keys every project row by its owner, which means an endpoint must
first know *who* is asking. That is what this module provides.

How a request is identified
---------------------------
The Studio browser holds a Supabase access token (it already signs the user
in). It sends it as ``Authorization: Bearer <token>``. This dependency
validates that token against Supabase and returns the user's UUID, which the
endpoint then uses both as the ``user_id`` column value and (through the
token-scoped Supabase client) as the RLS predicate ``auth.uid() = user_id``.

Development / test fallback
---------------------------
``get_supabase_client`` is the single factory every consumer uses, and the
test harness seals it to return ``None``. When the client is unavailable
(local dev with no Supabase, or the sealed test suite) there is no auth
backend to validate against, so the request is attributed to a fixed dev
identity. Production always has Supabase configured, so that branch is
unreachable there — the same "dev mode" escape hatch ``require_license``
already uses for its key check.

Note the factory is read via the MODULE (``supabase_client.get_supabase_client``)
rather than a bound ``from ... import get_supabase_client``. A bound import
would capture the real function at import time and silently bypass the
harness's per-test seal, which is exactly the leak ``conftest.py`` exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from audiomind.services import supabase_client

#: Identity used only when Supabase is unavailable (local dev + the sealed test
#: suite). Stable so a dev's rows are consistent across restarts. Production
#: always has Supabase, so this never becomes a real user there.
DEV_USER_ID = "00000000-0000-0000-0000-000000000000"

_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class UserContext:
    """The authenticated caller: their id plus the raw token.

    ``token`` is what a token-scoped Supabase client needs so RLS enforces
    ownership on every row the endpoint touches. It is ``None`` only in the
    dev fallback, where there is no real client to scope anyway.
    """

    user_id: str
    token: str | None


def _extract_bearer(authorization: str | None) -> str:
    """Pull the access token out of an ``Authorization: Bearer <t>`` header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Falta el header Authorization. Enviá "
                "'Authorization: Bearer <token>'."
            ),
            headers=_WWW_AUTH,
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.strip().lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Header Authorization mal formado. Se espera "
                "'Bearer <token>'."
            ),
            headers=_WWW_AUTH,
        )
    return token.strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado.",
        headers=_WWW_AUTH,
    )


def get_user_context(
    authorization: str | None = Header(None),
) -> UserContext:
    """Resolve the caller to a :class:`UserContext`, or reject the request.

    Raises 401 when the header is missing, malformed, or the token does not
    resolve to a Supabase user. Returns the dev identity when Supabase is not
    configured (dev/test).
    """
    token = _extract_bearer(authorization)

    client = supabase_client.get_supabase_client(token)
    if client is None:
        # Supabase unavailable (local dev or the sealed test suite). Attribute
        # the request to the fixed dev identity; production never lands here.
        return UserContext(user_id=DEV_USER_ID, token=None)

    try:
        user = client.auth.get_user(token)
    except Exception:
        # Any failure to resolve the token is an auth failure, not a 500: the
        # caller presented a token we cannot trust.
        raise _unauthorized() from None

    resolved = getattr(user, "user", None)
    if resolved is None or getattr(resolved, "id", None) is None:
        raise _unauthorized()

    return UserContext(user_id=str(resolved.id), token=token)


def require_user(ctx: Annotated[UserContext, Depends(get_user_context)]) -> str:
    """FastAPI dependency returning just the user id.

    For endpoints that only need *who* is asking and do not themselves open a
    token-scoped client. Endpoints that write rows depend on
    ``get_user_context`` directly so they also carry the token for RLS.
    """
    return ctx.user_id
