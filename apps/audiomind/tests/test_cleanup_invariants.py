"""Regression lock for the backend cleanup (95a90c8 -> 211b9fb).

Pins the structural invariants that cleanup established so the same defects
cannot silently return:

* only ``api/upload.py`` declares the two session endpoints (S1/S2),
* both routers operate on the very same session store,
* ``processing.engine`` keeps its public surface and keeps no statement after a
  ``return`` (S4),
* the ``models`` barrel still re-exports every public name (S5).

The behavioural half of the same cleanup — the served session contract and the
absence of duplicate OpenAPI operation IDs — lives in
``tests/test_session_routes.py``.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, "src")

import audiomind.api.mastering as mastering
import audiomind.api.upload as upload
import audiomind.models as models
import audiomind.processing.engine as engine

SESSION_PATHS = ("/session/new", "/session/{session_id}")

ENGINE_PUBLIC_SURFACE = (
    "process_audio",
    "target_lufs",
    "CLIPPER_HEADROOM_DB",
    "InputQcError",
    "BASE_MODULE_INTENSITY",
    "_user_limiter_ceiling",
    "measure_lufs",
    "true_peak_limit",
    "true_peak_db",
)


def _declared_session_paths(router: object) -> set[str]:
    return {
        route.path
        for route in router.routes  # type: ignore[attr-defined]
        if getattr(route, "path", None) in SESSION_PATHS
    }


def test_only_upload_router_declares_the_session_endpoints() -> None:
    assert _declared_session_paths(upload.router) == set(SESSION_PATHS)
    assert _declared_session_paths(mastering.router) == set()
    # The shadowed handlers must stay deleted, not merely unregistered: a new
    # copy in this module would be unreachable and would re-emit duplicate
    # operation IDs.
    assert not hasattr(mastering, "create_session")
    assert not hasattr(mastering, "get_session")


def test_both_routers_share_one_session_store() -> None:
    assert mastering.sessions is upload.sessions


def test_engine_keeps_its_surface_and_has_no_dead_code_after_return() -> None:
    for name in ENGINE_PUBLIC_SURFACE:
        assert hasattr(engine, name), name
    assert not hasattr(engine, "generate_report")

    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "generate_report" not in {function.name for function in functions}
    for function in functions:
        for index, statement in enumerate(function.body):
            if isinstance(statement, ast.Return):
                assert index == len(function.body) - 1, (
                    f"{function.name} has unreachable code after its return"
                )


def test_models_barrel_keeps_every_public_reexport() -> None:
    for name in ("MasterResultMetrics", "MasteringReport", "SessionData"):
        assert hasattr(models, name), name
