"""Gemini transport for the agentic mix loop (native Python SDK).

Implements ``agentic_loop.ModelTransport`` on top of ``google-genai`` — the
Python twin of ``@google/genai`` that ``apps/agent/`` already uses in
TypeScript. Same model ids, same fallback chain, so the mix agent and the chat
agent degrade identically when a model retires.

Decisions worth knowing:

* **The transcript is transport-neutral.** ``agentic_loop`` records plain dicts
  (``text`` / ``function_call`` / ``response``) and this module maps them to the
  SDK's ``Content`` model. That keeps the loop testable without a network.
* **A function response goes on a ``user`` turn.** The SDK's own schema says
  ``role`` "Must be either 'user' or 'model'"; there is no ``tool`` role.
* **A turn can carry several calls.** Gemini returns parallel function calls,
  so ``ModelTurn.tool_calls`` is a list and the loop executes all of them.
* **Failures are typed, never silent.** A missing key, an exhausted chain or an
  empty reply raises ``GeminiUnavailableError``; the loop lets it out rather
  than inventing a diagnosis.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import types

from audiomind.config import settings
from audiomind.processing.agentic_loop import (
    ModelTurn,
    ToolCall,
    TransportUnavailableError,
)

log = logging.getLogger(__name__)

#: Primary model, then the same retirement ladder the TS agent uses.
DEFAULT_MODEL = "gemini-3.7-flash"
MODEL_FALLBACKS: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.5-flash")

#: Low temperature: this agent moves knobs, it does not brainstorm.
DEFAULT_TEMPERATURE = 0.3


class GeminiUnavailableError(TransportUnavailableError):
    """The model could not answer. Never substituted with a guess."""


def _function_declarations(
    tools: Sequence[dict[str, Any]],
) -> list[types.FunctionDeclaration]:
    """Turn ``agentic_loop.tool_definitions()`` into SDK declarations.

    ``parameters_json_schema`` is the documented slot for a raw JSON Schema, so
    the Pydantic models stay the single source of truth for what the model sees.
    """
    return [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=tool["parameters"],
        )
        for tool in tools
    ]


def _to_contents(
    transcript: Sequence[dict[str, Any]],
) -> list[types.Content]:
    """Map the neutral transcript onto the SDK's ``Content`` model."""
    contents: list[types.Content] = []

    for entry in transcript:
        if "text" in entry:
            role = "model" if entry.get("role") == "model" else "user"
            text = entry["text"]
            if text:
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=text)])
                )
        elif "function_call" in entry:
            call = entry["function_call"]
            contents.append(
                types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name=call["name"], args=call.get("args") or {}
                            )
                        )
                    ],
                )
            )
        elif "response" in entry:
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=entry["name"], response=entry["response"]
                        )
                    ],
                )
            )

    return contents


class GeminiTransport:
    """``ModelTransport`` backed by ``google-genai``."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        fallbacks: Sequence[str] | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        client: genai.Client | None = None,
    ) -> None:
        # ``settings`` first: it is the only source that sees the backend's
        # ``.env`` file. pydantic-settings loads that file into the settings
        # object and NOT into ``os.environ``, so a key written there was
        # invisible to this constructor. ``os.environ`` stays as the last
        # resort for a key exported into the process environment.
        self.api_key = (
            api_key or settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        )
        if client is None and not self.api_key:
            raise GeminiUnavailableError(
                "Falta GEMINI_API_KEY. Completala en apps/audiomind/.env "
                "(GEMINI_API_KEY=...) o exportala en el entorno del backend."
            )
        self._client = client or genai.Client(api_key=self.api_key)
        primary = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        chain = fallbacks if fallbacks is not None else MODEL_FALLBACKS
        # Same de-duplication the TS agent does: a custom primary that is also
        # a fallback must not be tried twice.
        self.models: tuple[str, ...] = tuple(dict.fromkeys([primary, *chain]))
        self.temperature = temperature

    # -- ModelTransport -----------------------------------------------------

    def turn(
        self,
        *,
        phase: str,
        system: str,
        transcript: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ModelTurn:
        """One model turn: text, or the tool calls to execute.

        Tries each model in the chain in order. A model that fails for any
        reason moves out of the way for the next one; when the whole chain is
        exhausted the last error is raised as ``GeminiUnavailableError``.
        """
        contents = _to_contents(transcript)
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            tools=[types.Tool(function_declarations=_function_declarations(tools))]
            if tools
            else None,
        )

        last_error: Exception | None = None
        for model in self.models:
            try:
                response = self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:  # noqa: BLE001 — any failure tries the next
                last_error = exc
                log.warning("Gemini %s falló en %s: %s", model, phase, exc)
                continue

            calls = [
                ToolCall(name=c.name or "", args=dict(c.args or {}))
                for c in (response.function_calls or [])
                if c.name
            ]
            if calls:
                return ModelTurn(tool_calls=calls)

            text = (response.text or "").strip()
            if text:
                return ModelTurn(text=text)

            last_error = GeminiUnavailableError(
                "Gemini no devolvió contenido. Puede haber cortado por filtros "
                "de seguridad o por longitud."
            )

        raise GeminiUnavailableError(
            f"Falló la llamada a Gemini en {phase}. Se probó: "
            f"{', '.join(self.models)}. Último error: {last_error}"
        ) from last_error
