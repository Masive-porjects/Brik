#!/usr/bin/env python3
"""Prueba de fuego funcional del bucle agéntico: audio real + Gemini real.

No es un test de pytest: necesita red, ``GEMINI_API_KEY`` y Demucs. Vive en
``scripts/`` justamente porque ``pytest`` sólo mira ``tests/``. Sin key sale
con código 2 y lo dice — nunca inventa un resultado.

Qué valida:

1. ``send_to_master`` cierra de verdad contra ``engine.process_audio`` y deja
   un WAV masterizado en disco.
2. El bucle corre con el transporte Gemini real, y se ve su razonamiento.
3. **Demucs se paga una sola vez por sesión.** La Fase 2 separa y deja los
   stems en ``settings.output_dir/<session_id>/stems``; cada ``render_mix``
   posterior los reusa desde el manifiesto de ``splitter``. El script cuenta
   las corridas reales en el borde del módulo, así que la evidencia no depende
   de cómo se lea un log.

Uso:

  apps/audiomind/.venv/Scripts/python.exe apps/audiomind/scripts/test_live_loop.py \
      --audio "C:/Users/yo/Music/tema.wav" --max-seconds 15
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from audiomind.config import settings
from audiomind.processing import agentic_loop as al
from audiomind.processing import splitter
from audiomind.processing.gemini_transport import (
    GeminiTransport,
    GeminiUnavailableError,
)

#: La consola de Windows suele venir en cp1252, donde los acentos y los glifos
#: de caja no encodifican: sin esto el script muere con UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_INSTRUCTION = (
    "Haz que la voz principal destaque más y dale un toque más cálido"
)

RULE = "=" * 78


# ══════════════════════════════════════════════════════════════════════════
# Snippet de 10-15 s
# ══════════════════════════════════════════════════════════════════════════


def prepare_snippet(source: Path, max_seconds: float) -> Path:
    """Un WAV de a lo sumo ``max_seconds``, recortado desde el principio."""
    info = sf.info(str(source))
    print(
        f"  fuente : {source.name}  {info.duration:.2f}s  "
        f"{info.samplerate} Hz  {info.channels} ch"
    )
    if info.duration <= max_seconds:
        print("  ya entra en el límite: no se recorta")
        return source

    frames = int(max_seconds * info.samplerate)
    data, rate = sf.read(str(source), frames=frames, dtype="float32")
    out_dir = settings.output_dir / "_live_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    snippet = out_dir / f"{source.stem}_{int(max_seconds)}s.wav"
    sf.write(str(snippet), data, rate, subtype="PCM_16")
    print(f"  recortado a {max_seconds:.0f}s -> {snippet}")
    return snippet


# ══════════════════════════════════════════════════════════════════════════
# Instrumentación
# ══════════════════════════════════════════════════════════════════════════


class DemucsCounter:
    """Cuenta las corridas reales de Demucs, en el borde del módulo.

    ``split_audio`` llama a estos dos por nombre del namespace de ``splitter``,
    así que reemplazarlos acá cubre a TODOS los llamadores — ``build_mix``
    incluido, que es el que separa dentro de ``render_mix``.
    """

    def __init__(self) -> None:
        self.seconds: list[float] = []

    def install(self) -> None:
        for name in ("_split_audio_isolated", "_split_audio_in_process"):
            original = getattr(splitter, name)

            def wrapper(input_path, output_dir, model, _original=original, _name=name):
                print(
                    f"  >>> DEMUCS EJECUTÁNDOSE ({_name}) "
                    f"input={Path(input_path).name}",
                    flush=True,
                )
                started = time.perf_counter()
                result = _original(input_path, output_dir, model)
                elapsed = time.perf_counter() - started
                self.seconds.append(elapsed)
                print(f"  >>> DEMUCS TERMINÓ en {elapsed:.2f}s", flush=True)
                return result

            setattr(splitter, name, wrapper)

    @property
    def count(self) -> int:
        return len(self.seconds)


class TimedTools:
    """Envuelve ``TOOL_IMPLS`` para cronometrar, narrar y retener los envelopes.

    ``dispatch`` resuelve por ``TOOL_IMPLS`` en tiempo de llamada, así que
    reemplazar sus entradas alcanza para instrumentar todas las herramientas.
    """

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.calls: dict[str, int] = {}
        self.results: list[Any] = []

    def install(self) -> None:
        for name, impl in list(al.TOOL_IMPLS.items()):

            def wrapper(state, args, _impl=impl, _name=name):
                started = time.perf_counter()
                result = _impl(state, args)
                elapsed = time.perf_counter() - started
                self.seconds[_name] = self.seconds.get(_name, 0.0) + elapsed
                self.calls[_name] = self.calls.get(_name, 0) + 1
                self.results.append(result)
                print(
                    f"    [{'ok  ' if result.ok else 'FALLA'}] "
                    f"{_name}  {elapsed:6.2f}s  {result.detail}",
                    flush=True,
                )
                return result

            al.TOOL_IMPLS[name] = wrapper

    def payload_of(self, tool: str) -> dict[str, Any]:
        for result in reversed(self.results):
            if result.tool == tool and result.ok:
                return dict(result.payload)
        return {}


class NarratedTransport:
    """Muestra la fase, el razonamiento del modelo y lo que pide."""

    def __init__(self, inner: Any, *, show_reasoning: bool = True) -> None:
        self.inner = inner
        self.show_reasoning = show_reasoning
        self.seconds: list[tuple[str, float]] = []

    def turn(self, *, phase, system, transcript, tools):
        offered = ", ".join(t["name"] for t in tools) or "(ninguna)"
        print(f"\n  -- {phase} | herramientas ofrecidas: {offered} --")
        started = time.perf_counter()
        turn = self.inner.turn(
            phase=phase, system=system, transcript=transcript, tools=tools
        )
        elapsed = time.perf_counter() - started
        self.seconds.append((phase, elapsed))
        print(f"  [gemini] {elapsed:.2f}s")
        if turn.text and self.show_reasoning:
            print(f"  [razonamiento] {turn.text}")
        for call in turn.tool_calls:
            print(f"  [pide] {call.name}  args={call.args}")
        return turn

    @property
    def total_seconds(self) -> float:
        return sum(secs for _, secs in self.seconds)


class ScriptedTransport:
    """Guion fijo: mismas fases y mismas herramientas, sin LLM.

    Sirve para ejercer el pipeline REAL (Demucs, ``build_mix``,
    ``engine.process_audio``) cuando no hay key. NO reemplaza la prueba con
    Gemini: acá no hay razonamiento del agente, sólo su secuencia.
    """

    def __init__(self, script: list[al.ModelTurn]) -> None:
        self.script = list(script)
        self.models: tuple[str, ...] = ("scripted",)

    def turn(self, *, phase, system, transcript, tools):
        if phase == "phase4":
            # La fase de cierre siempre empuja el bus: es lo que el guion haría.
            return al.ModelTurn(
                tool_calls=[al.ToolCall(name="send_to_master", args={"source": "mix"})]
            )
        if not self.script:
            raise RuntimeError(f"el guion se quedó sin turnos en {phase}")
        return self.script.pop(0)


def _scripted_transport() -> ScriptedTransport:
    """La secuencia que el prompt le pide al agente, escrita a mano."""
    from audiomind.models.intent_profile import IntentProfile

    intent = IntentProfile(vocal_focus=0.8, warmth=0.7)
    return ScriptedTransport(
        [
            al.ModelTurn(
                text=(
                    "La voz queda tapada y el balance es filoso: la subo al "
                    "frente y le doy cuerpo con un toque cálido."
                )
            ),
            al.ModelTurn(
                tool_calls=[
                    al.ToolCall(
                        name="adjust_stem_parameters",
                        args={
                            "intent": intent.model_dump(),
                            "rationale": "voz al frente y más cálido",
                        },
                    )
                ]
            ),
            al.ModelTurn(tool_calls=[al.ToolCall(name="render_mix", args={})]),
            al.ModelTurn(tool_calls=[al.ToolCall(name="analyze_mix_bus", args={})]),
        ]
    )


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueba de fuego funcional del bucle agéntico."
    )
    parser.add_argument("--audio", required=True, help="Ruta de un audio real.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=15.0,
        help="Máximo del snippet (spec: 10-15 s).",
    )
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    parser.add_argument("--session", default="live-loop")
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="No borrar la sesión previa (deja la caché de stems caliente).",
    )
    parser.add_argument(
        "--transport",
        choices=("gemini", "scripted"),
        default="gemini",
        help=(
            "gemini = prueba real (necesita GEMINI_API_KEY). "
            "scripted = dry-run del pipeline con herramientas REALES y un guion "
            "fijo, para validar el cableado sin key. No reemplaza a gemini."
        ),
    )
    parser.add_argument(
        "--quiet-reasoning",
        action="store_true",
        help="No imprimir el texto del modelo.",
    )
    parser.add_argument("--verbose", action="store_true", help="Logging DEBUG.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s :: %(message)s",
        stream=sys.stdout,
        force=True,
    )

    print(RULE)
    print("PRUEBA DE FUEGO · bucle agéntico de mezcla y master")
    print(RULE)

    source = Path(args.audio)
    if not source.is_file():
        print(f"\nERROR: el audio no existe: {source}")
        return 2

    if args.transport == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        print(
            "\nERROR: falta GEMINI_API_KEY en el entorno, así que el bucle no"
            " puede correr.\n"
            "  PowerShell : $env:GEMINI_API_KEY = 'tu-key'\n"
            "  bash       : export GEMINI_API_KEY='tu-key'\n\n"
            "El transporte levanta GeminiUnavailableError en vez de inventar un"
            " diagnóstico, y este script no fabrica logs.\n"
            "Para validar el cableado sin key: --transport scripted."
        )
        return 2

    print("\n  -- 1 | PREPARACIÓN --")
    snippet = prepare_snippet(source, args.max_seconds)

    session_dir = settings.output_dir / args.session
    if session_dir.exists() and not args.keep_cache:
        shutil.rmtree(session_dir)
        print(f"  sesión borrada: {session_dir}")
        print("  la caché de stems arranca vacía -> la primera separación DEBE correr")
    elif session_dir.exists():
        print(f"  --keep-cache: se conserva {session_dir} (puede haber caché caliente)")
    print(f"  sesión  : {args.session}")
    print(f"  stems   : {session_dir / 'stems'}")
    print(f"  instrucción: {args.instruction!r}")

    counter = DemucsCounter()
    counter.install()
    timed = TimedTools()
    timed.install()

    inner: Any = (
        GeminiTransport() if args.transport == "gemini" else _scripted_transport()
    )
    transport = NarratedTransport(inner, show_reasoning=not args.quiet_reasoning)
    print(f"  transporte: {args.transport}")
    print(f"  modelos : {' -> '.join(inner.models)}")
    if args.transport == "scripted":
        print(
            "  AVISO: guion fijo. Se ejercen Demucs, build_mix y "
            "engine.process_audio,\n"
            "         pero NO hay razonamiento del agente ni llamadas a Gemini."
        )

    print("\n  -- 2 | BUCLE --")
    overall_started = time.perf_counter()
    try:
        state = al.run(
            session_id=args.session,
            input_path=snippet,
            transport=transport,
        )
    except GeminiUnavailableError as exc:
        elapsed = time.perf_counter() - overall_started
        print(f"\n{RULE}")
        print(f"EL TRANSPORTE GEMINI FALLÓ tras {elapsed:.2f}s")
        print(RULE)
        print(str(exc))
        print(
            "\nLa cadena de modelos se agotó. Revisá el nombre del modelo o el"
            " estado del servicio; el bucle no siguió a ciegas."
        )
        return 3
    overall_elapsed = time.perf_counter() - overall_started

    # ── Sonda: un render MÁS, a mano. El bucle real puede cortar por
    #    convergencia en la primera iteración, así que esta sonda prueba
    #    explícitamente que un render POSTERIOR tampoco vuelve a pagar Demucs.
    print("\n  -- SONDA | render_mix extra contra la caché caliente --")
    demucs_before_probe = counter.count
    al.dispatch(
        state, "adjust_stem_parameters", {"intent": state.intent.model_dump()}
    )
    extra = al.dispatch(state, "render_mix", {"with_versions": False})
    print(f"    render extra: ok={extra.ok} | {extra.detail}")
    print(
        f"    Demucs durante el render extra: "
        f"{counter.count - demucs_before_probe} corrida(s)"
    )

    # ── Reporte ──────────────────────────────────────────────────────────
    print(f"\n{RULE}")
    print("RESULTADO")
    print(RULE)
    print(f"  diagnóstico        : {state.diagnosis}")
    print(f"  intención final    : {state.intent.model_dump()}")
    print(f"  iteraciones de mix : {state.iteration}")
    print(f"  stems en disco     : {len(state.stems)} de 4")

    master_payload = timed.payload_of("send_to_master")
    for label in (
        "integrated_lufs",
        "true_peak_db",
        "loudness_range_lra",
        "crest_factor_db",
        "lra",
        "output_bit_depth",
        "execution_time_seconds",
    ):
        if master_payload.get(label) is not None:
            print(f"  master {label:<19}: {master_payload[label]}")

    print("\n  -- ARTEFACTOS --")
    for label, path in (("mezcla", state.mix_path), ("master", state.master_path)):
        if path and Path(path).is_file():
            target = Path(path)
            print(f"  {label:<7}: {target}  ({target.stat().st_size / 1024:.0f} KB)")
        else:
            print(f"  {label:<7}: NO se generó")

    # ── Validación de caché ──────────────────────────────────────────────
    renders = timed.calls.get("render_mix", 0)
    separates = timed.calls.get("trigger_stem_separation", 0)

    print(f"\n{RULE}")
    print("VALIDACIÓN DE CACHÉ - ¿se vuelve a pagar Demucs?")
    print(RULE)
    print(f"  llamadas a trigger_stem_separation : {separates}")
    print(f"  llamadas a render_mix              : {renders}")
    print(f"  corridas REALES de Demucs          : {counter.count}")
    for index, secs in enumerate(counter.seconds, start=1):
        print(f"    - corrida #{index}: {secs:.2f}s")

    if counter.count == 1 and renders >= 1:
        print(
            f"\n  VEREDICTO: Demucs corrió 1 vez y hubo {renders} render(s)."
            "\n  Los renders posteriores leyeron los stems del manifiesto:"
            " la caché funciona."
        )
    elif counter.count == 0:
        print(
            "\n  VEREDICTO: Demucs no corrió (los stems ya estaban en disco)."
            "\n  La caché se usó desde el arranque; corré sin --keep-cache para"
            " ver el caso completo."
        )
    else:
        print(
            f"\n  VEREDICTO: Demucs corrió {counter.count} veces con {renders}"
            " render(s).\n  La caché NO está evitando el trabajo — revisar el"
            " manifiesto y el input de build_mix."
        )

    # ── Tiempos ──────────────────────────────────────────────────────────
    print(f"\n{RULE}")
    print("TIEMPOS")
    print(RULE)
    print(f"  gemini (suma de turnos) : {transport.total_seconds:7.2f}s")
    for phase, secs in transport.seconds:
        print(f"    - {phase:<8}: {secs:7.2f}s")
    print(f"  demucs (suma)           : {sum(counter.seconds):7.2f}s")
    print("  herramientas:")
    for name, secs in sorted(timed.seconds.items(), key=lambda kv: -kv[1]):
        print(f"    - {name:<26}: {secs:7.2f}s  ({timed.calls[name]} llamada/s)")
    print(f"  TOTAL del bucle         : {overall_elapsed:7.2f}s")

    print(f"\n{RULE}")
    print("FIN")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
